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

from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional

from .events import EVENT_TYPES, Event, EventBus
from .llm import AdapterResult, LLMAdapter, LLMUnavailable, OfflineAdapter


DEFAULT_PER_TURN_CAP: int = 3
DEFAULT_BUDGET: int = 10_000


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

    # ---- internals --------------------------------------------------------
    def _handle_event(self, event: Event) -> None:
        # Throttling: per-turn cap.
        turn = event.turn
        count = self._turn_counts.get(turn, 0)
        if count >= self.per_turn_cap:
            return
        # Coalesce: same (turn, type) -> only one whisper per turn even
        # under the cap. This protects against teleport-style spam of
        # identical event types in a single turn.
        seen = self._seen_turn_types.setdefault(turn, set())
        if event.type in seen:
            return
        seen.add(event.type)
        self._turn_counts[turn] = count + 1

        # Choose adapter and fallback flag.
        text, tokens, adapter_name, fallback, error_reason = self._produce(event)
        whisper = Whisper(
            text=text,
            source_event_type=event.type,
            source_turn=event.turn,
            source_floor=event.floor,
            adapter_name=adapter_name,
            fallback=fallback,
            tokens=tokens,
            error_reason=error_reason,
        )
        self.whispers.append(whisper)

    def _produce(self, event: Event):
        """Run the primary adapter, falling back on failure or budget exhaustion.

        Returns ``(text, tokens, adapter_name, fallback, error_reason)``.
        """
        prompt = self._build_prompt(event)
        # Budget check FIRST: if already exhausted, go straight to fallback.
        if self.budget_exhausted or self.tokens_used >= self.budget:
            self.budget_exhausted = True
            return self._call_fallback(prompt, event, error_reason=None)

        try:
            result = self.adapter.complete(
                prompt, max_tokens=64, event_type=event.type
            )
        except Exception as exc:  # noqa: BLE001 -- documented resilience
            self.failure_count += 1
            reason = f"{type(exc).__name__}: {exc}"
            return self._call_fallback(prompt, event, error_reason=reason)

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

    def _call_fallback(self, prompt: str, event: Event, *, error_reason: Optional[str]):
        try:
            result = self.fallback_adapter.complete(
                prompt, max_tokens=64, event_type=event.type
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
    def _build_prompt(event: Event) -> str:
        # Single-shot, single-line prompt. Real providers can elaborate.
        payload_bits = ", ".join(
            f"{k}={v}" for k, v in (event.payload or {}).items()
        )
        return (
            f"Event: {event.type} | turn={event.turn} | floor={event.floor}"
            + (f" | {payload_bits}" if payload_bits else "")
        )


__all__ = ["Whisperer", "Whisper", "DEFAULT_PER_TURN_CAP", "DEFAULT_BUDGET"]
