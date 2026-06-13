"""Whisperer service: turns gameplay events into in-character prose.

The Whisperer subscribes to an :class:`whisperdeep.events.EventBus`, builds a
prompt from each incoming :class:`whisperdeep.events.Event`, queries an
:class:`whisperdeep.llm.LLMAdapter`, and records the returned text along
with metadata as a :class:`Whisper`.

Sprint 7 is plumbing only: the produced whispers live in ``whisperer.whispers``
and are NOT yet rendered in the dungeon frame. Sprint 8 will add the panel UI.

Guardrails baked into this module:
* **Per-turn cap.** No more than ``per_turn_cap`` whispers are produced for
  any single ``turn`` value, regardless of how many events fire (defaults to
  3). Excess events are silently dropped.
* **Token budget.** Cumulative reported tokens are tracked. Once the budget
  is exhausted, subsequent whispers are served from the offline fallback
  pool with ``fallback=True`` and consume zero chargeable tokens.
* **Adapter failure resilience.** Any exception raised by the primary
  adapter is caught, recorded (``failure_count`` + per-whisper
  ``error_reason``), and the whisper is served from the fallback pool with
  ``fallback=True``. The Whisperer never re-raises out of its event handler.

Layering: this module imports only ``events`` and the ``llm`` ABC + the
``OfflineAdapter`` it needs as a built-in fallback. It does NOT import
concrete real-provider adapter classes.
"""
from __future__ import annotations

import random as _random
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

from .events import EVENT_TYPES, Event, EventBus
from .llm import AdapterResult, LLMAdapter, LLMUnavailable, OfflineAdapter


DEFAULT_PER_TURN_CAP: int = 3
DEFAULT_BUDGET: int = 10_000

# Sprint 8 placeholder convention for first_sight prose. The pool entries
# contain ``{name}`` (Python ``str.format`` style); the Whisperer mints a
# name for the kind on first sight and substitutes it into the produced
# whisper text. ``${name}`` is also recognized for compatibility.
FIRST_SIGHT_PLACEHOLDERS: tuple = ("{name}", "${name}")

# A small, deterministic pool of "evocative" name tokens used to mint a
# short name for an unfamiliar kind when the OfflineAdapter is in use. The
# Whisperer combines one of these with the kind string (e.g. "skitterer")
# so the registered name is still recognizably tied to its kind. The pool
# is intentionally kept short and stable so determinism tests are
# tractable.
_NAME_ADJECTIVES: tuple = (
    "creeping",
    "hollow",
    "ashen",
    "patient",
    "wretched",
    "wandering",
    "rusted",
    "silent",
    "feverish",
    "long-armed",
    "small",
    "watchful",
    "slow",
    "bone-pale",
    "dust-eaten",
    "candle-thin",
)


@dataclass
class Whisper:
    """A single whisper produced by the Whisperer.

    Carries enough metadata to be reproducible and auditable.
    """

    text: str
    source_event_type: str
    source_turn: int
    source_floor: Optional[int]
    adapter_name: str
    fallback: bool
    tokens: int = 0
    error_reason: Optional[str] = None
    # Sprint 11: thematic archetype id of the source floor at publish time.
    # None for floors without an archetype (defensive); otherwise one of
    # the registered ids (e.g., 'crypt', 'mushroom_forest', ...).
    archetype: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class Whisperer:
    """Subscribes to an EventBus and produces whispers.

    Parameters
    ----------
    adapter
        Primary :class:`LLMAdapter` used to generate prose. Required.
    bus
        Optional :class:`EventBus` to attach to immediately. If omitted,
        call :meth:`attach` later.
    budget
        Maximum cumulative tokens before whispers degrade to the offline
        fallback (and stop accumulating chargeable tokens).
    seed
        Seed used for the built-in offline fallback adapter and (if the
        primary adapter is itself an OfflineAdapter that didn't get a seed)
        for prose selection. Optional.
    per_turn_cap
        Maximum whispers produced for a single turn value. Default 3.
    fallback_adapter
        Adapter used when the primary fails or the budget is exhausted. If
        omitted, a fresh :class:`OfflineAdapter` is created (seeded by
        ``seed``).
    event_types
        Iterable of event-type names to listen for. Defaults to the seven
        canonical types from :data:`EVENT_TYPES`.
    """

    def __init__(
        self,
        adapter: LLMAdapter,
        bus: Optional[EventBus] = None,
        *,
        budget: int = DEFAULT_BUDGET,
        seed: Optional[int] = None,
        per_turn_cap: int = DEFAULT_PER_TURN_CAP,
        fallback_adapter: Optional[LLMAdapter] = None,
        event_types: Optional[List[str]] = None,
    ) -> None:
        if adapter is None:
            raise ValueError("Whisperer requires an adapter")
        self.adapter: LLMAdapter = adapter
        self.budget: int = int(budget)
        self.per_turn_cap: int = int(per_turn_cap)
        self.seed = seed
        self.fallback_adapter: LLMAdapter = (
            fallback_adapter if fallback_adapter is not None else OfflineAdapter(seed=seed)
        )
        self._listen_set = set(event_types) if event_types is not None else set(EVENT_TYPES)
        # Mutable state.
        self.whispers: List[Whisper] = []
        self.tokens_used: int = 0
        self.failure_count: int = 0
        self.budget_exhausted: bool = False
        # Per-turn coalescing: turn -> count of whispers already produced.
        self._turn_counts: Dict[int, int] = {}
        # Track most-recent (turn, type) so duplicate same-type spam in a
        # single turn coalesces to one whisper even before per_turn_cap.
        self._seen_turn_types: Dict[int, set] = {}
        # Sprint 8: per-run registries.
        # ``names`` maps a kind string (e.g. "goblin") to the name minted
        # the first time the player saw that kind. Idempotent across the
        # whole run — re-firing first_sight for the same kind never
        # mutates this map.
        self.names: Dict[str, str] = {}
        # ``_seen_rooms`` records (floor, room_id) pairs that have already
        # produced a room_entered whisper this run; used to dedupe.
        self._seen_rooms: set = set()
        # Deterministic RNG used for name minting; seeded the same way as
        # the offline adapter so the same seed produces the same names.
        self._name_rng = _random.Random(seed)
        self._unsubs: List[Callable[[], None]] = []
        self._bus: Optional[EventBus] = None
        if bus is not None:
            self.attach(bus)

    # ---- public API -------------------------------------------------------
    def attach(self, bus: EventBus) -> None:
        """Subscribe to ``bus`` for the configured event types."""
        if self._bus is bus:
            return
        # Clean up any prior attachment.
        self.detach()
        self._bus = bus
        for et in self._listen_set:
            self._unsubs.append(bus.subscribe(et, self._handle_event))

    def detach(self) -> None:
        for unsub in self._unsubs:
            try:
                unsub()
            except Exception:  # noqa: BLE001
                pass
        self._unsubs.clear()
        self._bus = None

    def get_whispers(self) -> List[Whisper]:
        """Return the list of produced whispers (mutable; same as ``self.whispers``)."""
        return self.whispers

    def dump(self) -> List[Dict[str, object]]:
        """Return the whispers as a list of plain dicts (for JSON)."""
        return [w.to_dict() for w in self.whispers]

    # ---- Sprint 8: name registry ----------------------------------------
    def get_name(self, kind: str) -> Optional[str]:
        """Return the registered name for ``kind``, or ``None`` if unseen."""
        return self.names.get(kind)

    def _mint_name(self, kind: str, category: Optional[str]) -> str:
        """Deterministically mint a short evocative name for ``kind``.

        The name is built from a deterministic adjective drawn from a small
        fixed pool plus the raw ``kind`` string, e.g. ``"creeping goblin"``.
        Determinism: the per-Whisperer RNG is seeded from the constructor
        ``seed`` argument, so two Whisperers built with the same seed (and
        the same first_sight call sequence) mint identical names.
        """
        adj = _NAME_ADJECTIVES[self._name_rng.randrange(len(_NAME_ADJECTIVES))]
        return f"{adj} {kind}"

    def _ensure_name_for_first_sight(self, event: Event) -> Optional[str]:
        """Idempotent name minting for a first_sight event.

        Returns the registered name (newly minted or pre-existing), or
        ``None`` if the event payload lacked a usable ``kind``.
        """
        payload = event.payload or {}
        kind = payload.get("kind")
        if not isinstance(kind, str) or not kind:
            return None
        if kind in self.names:
            return self.names[kind]
        category = payload.get("category")
        if not isinstance(category, str):
            category = None
        name = self._mint_name(kind, category)
        self.names[kind] = name
        return name

    # ---- internals --------------------------------------------------------
    def _handle_event(self, event: Event) -> None:
        # Sprint 8: dedupe room_entered by (floor, room_id) BEFORE the
        # per-turn cap so re-entering a room never spends a whisper slot.
        if event.type == "room_entered":
            key = self._room_key(event)
            if key is None:
                return
            if key in self._seen_rooms:
                return
            self._seen_rooms.add(key)

        # Sprint 8: dedupe first_sight by kind so the second sighting of
        # the same kind never produces a second whisper (and never re-mints
        # a name).
        if event.type == "first_sight":
            payload = event.payload or {}
            kind = payload.get("kind") if isinstance(payload, dict) or hasattr(payload, "get") else None
            if isinstance(kind, str) and kind in self.names:
                # Already registered: idempotent skip.
                return

        # Throttling: per-turn cap.
        turn = event.turn
        count = self._turn_counts.get(turn, 0)
        if count >= self.per_turn_cap:
            return
        # Coalesce: same (turn, type) -> only one whisper per turn even
        # under the cap. This protects against teleport-style spam of
        # identical event types in a single turn. Sprint 8: coalesce keys
        # for first_sight and room_entered are (type, distinguishing-key)
        # so distinct kinds / distinct rooms within one turn are NOT
        # collapsed even though they share the type.
        seen = self._seen_turn_types.setdefault(turn, set())
        coalesce_key = self._coalesce_key(event)
        if coalesce_key in seen:
            return
        seen.add(coalesce_key)
        self._turn_counts[turn] = count + 1

        # Sprint 11: pluck the archetype id off the event payload (set by
        # the Game when the floor has an archetype). Used both for
        # archetype-aware prose selection and to tag the produced Whisper.
        archetype_id: Optional[str] = None
        payload = event.payload or {}
        if hasattr(payload, "get"):
            raw = payload.get("archetype")
            if isinstance(raw, str) and raw:
                archetype_id = raw

        # Sprint 8: for first_sight, mint a name BEFORE the adapter call so
        # the prompt and the substitution have access to it.
        minted_name: Optional[str] = None
        if event.type == "first_sight":
            minted_name = self._ensure_name_for_first_sight(event)

        # Choose adapter and fallback flag.
        text, tokens, adapter_name, fallback, error_reason = self._produce(
            event, archetype=archetype_id
        )

        # Sprint 8: substitute the minted name into first_sight prose.
        if event.type == "first_sight" and minted_name:
            text = self._substitute_name(text, minted_name)

        whisper = Whisper(
            text=text,
            source_event_type=event.type,
            source_turn=event.turn,
            source_floor=event.floor,
            adapter_name=adapter_name,
            fallback=fallback,
            tokens=tokens,
            error_reason=error_reason,
            archetype=archetype_id,
        )
        self.whispers.append(whisper)

    @staticmethod
    def _room_key(event: Event) -> Optional[tuple]:
        """Return ``(floor, room_id)`` for a room_entered event, or None."""
        payload = event.payload or {}
        if not hasattr(payload, "get"):
            return None
        room_id = payload.get("room_id")
        # Prefer the payload's floor; fall back to event.floor.
        floor = payload.get("floor", event.floor)
        if room_id is None:
            return None
        return (floor, room_id)

    @staticmethod
    def _coalesce_key(event: Event) -> tuple:
        """Per-turn coalesce key for an event.

        For most types the key is the type itself (matching Sprint-7
        behavior: 50 ``entered_room`` events on a single turn collapse to
        one whisper). For ``first_sight`` and ``room_entered`` we add a
        secondary discriminator so distinct kinds / distinct rooms within
        the same turn are NOT collapsed.
        """
        if event.type == "first_sight":
            payload = event.payload or {}
            kind = payload.get("kind") if hasattr(payload, "get") else None
            return (event.type, kind)
        if event.type == "room_entered":
            payload = event.payload or {}
            if hasattr(payload, "get"):
                return (event.type, payload.get("floor", event.floor),
                        payload.get("room_id"))
            return (event.type,)
        return (event.type,)

    @staticmethod
    def _substitute_name(text: str, name: str) -> str:
        """Replace any documented placeholder in ``text`` with ``name``."""
        out = text
        for ph in FIRST_SIGHT_PLACEHOLDERS:
            out = out.replace(ph, name)
        return out

    def _produce(self, event: Event, *, archetype: Optional[str] = None):
        """Run the primary adapter, falling back on failure or budget exhaustion.

        Returns ``(text, tokens, adapter_name, fallback, error_reason)``.
        """
        prompt = self._build_prompt(event)
        # Budget check FIRST: if already exhausted, go straight to fallback.
        if self.budget_exhausted or self.tokens_used >= self.budget:
            self.budget_exhausted = True
            return self._call_fallback(prompt, event, error_reason=None, archetype=archetype)

        try:
            result = self._adapter_complete(
                self.adapter, prompt, event_type=event.type, archetype=archetype
            )
        except Exception as exc:  # noqa: BLE001 -- documented resilience
            self.failure_count += 1
            reason = f"{type(exc).__name__}: {exc}"
            return self._call_fallback(prompt, event, error_reason=reason, archetype=archetype)

        # Successful primary call. Account tokens.
        self.tokens_used += int(result.tokens or 0)
        # If the call itself pushed us at-or-past the budget, mark exhausted
        # but DO NOT retroactively re-flag this whisper as fallback — the
        # contract requires fallback=True only for whispers AFTER the budget
        # is exceeded.
        if self.tokens_used >= self.budget:
            self.budget_exhausted = True
        text = result.text if result.text else ""
        return text, int(result.tokens or 0), result.adapter_name, False, None

    def _call_fallback(self, prompt: str, event: Event, *, error_reason: Optional[str], archetype: Optional[str] = None):
        try:
            result = self._adapter_complete(
                self.fallback_adapter,
                prompt,
                event_type=event.type,
                archetype=archetype,
            )
            text = result.text or ""
            adapter_name = result.adapter_name
        except Exception as exc:  # noqa: BLE001 -- last-ditch
            # Even the fallback failed; produce a synthetic whisper so the
            # game is never starved.
            self.failure_count += 1
            text = "(the deep is silent for a moment)"
            adapter_name = "synthetic"
            error_reason = error_reason or f"{type(exc).__name__}: {exc}"
        # Fallback whispers do NOT consume the budget.
        return text, 0, adapter_name, True, error_reason

    @staticmethod
    def _adapter_complete(
        adapter: LLMAdapter,
        prompt: str,
        *,
        event_type: Optional[str],
        archetype: Optional[str],
    ) -> AdapterResult:
        """Invoke ``adapter.complete`` while staying compatible with adapters
        whose ``complete`` predates the Sprint-11 ``archetype`` keyword.
        """
        try:
            return adapter.complete(
                prompt,
                max_tokens=64,
                event_type=event_type,
                archetype=archetype,
            )
        except TypeError:
            # Adapter is older / third-party; retry without the keyword.
            return adapter.complete(
                prompt, max_tokens=64, event_type=event_type
            )

    @staticmethod
    def _build_prompt(event: Event) -> str:
        # Single-shot, single-line prompt. Real providers can elaborate.
        payload_bits = ", ".join(
            f"{k}={v}" for k, v in (event.payload or {}).items()
        )
        return (
            f"Event: {event.type} | turn={event.turn} | floor={event.floor}"
            + (f" | {payload_bits}" if payload_bits else "")
        )


__all__ = [
    "Whisperer",
    "Whisper",
    "DEFAULT_PER_TURN_CAP",
    "DEFAULT_BUDGET",
    "FIRST_SIGHT_PLACEHOLDERS",
]
