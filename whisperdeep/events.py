"""In-game Event Bus for Whisperdeep (Sprint 7).

Provides a small, dependency-free pub/sub primitive for the rest of the
engine to publish gameplay milestones without importing the Whisperer or any
LLM adapter. Layering invariant: this module imports nothing from
``whisperdeep.whisperer`` or ``whisperdeep.llm``.

Canonical event types are exposed as both an ``EventType`` enum and an
``EVENT_TYPES`` tuple so other modules and tests can reference them without
magic strings.

Public API:
    Event           -- frozen dataclass carrying type/payload/turn/floor
    EventType       -- enum of canonical event names
    EVENT_TYPES     -- iterable tuple of the canonical event-type strings
    EventBus        -- publish/subscribe coordinator
    WILDCARD        -- the constant '*' for wildcard subscriptions
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Canonical event types
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """Closed set of canonical Whisperdeep event names.

    Sprint 7 introduced the original seven types. Sprint 8 ADDS
    ``FIRST_SIGHT`` (a player's first encounter with a particular kind of
    monster or item) and ``ROOM_ENTERED`` (the player walking into a
    previously-unseen room) in a strictly additive way: the original seven
    names remain present and unchanged.
    """

    RUN_STARTED = "run_started"
    RUN_ENDED = "run_ended"
    ENTERED_ROOM = "entered_room"
    KILLED_MONSTER = "killed_monster"
    LOW_HP = "low_hp"
    FOUND_ITEM = "found_item"
    DESCENDED = "descended"
    # Sprint 8 additions (additive only):
    FIRST_SIGHT = "first_sight"
    ROOM_ENTERED = "room_entered"


# Tuple form so it's iterable, hashable, and trivially serializable.
EVENT_TYPES: Tuple[str, ...] = tuple(et.value for et in EventType)


WILDCARD: str = "*"


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    """A single in-game event.

    Fields:
        type    canonical event name (string; one of EVENT_TYPES typically).
        payload event-specific data; an empty mapping by default.
        turn    game turn at which the event was published.
        floor   floor index, or None if not applicable.
    """

    type: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    turn: int = 0
    floor: Optional[int] = None


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


Subscriber = Callable[[Event], None]


class EventBus:
    """Synchronous, ordered, in-process pub/sub bus.

    Subscribers register for a specific event type or for the wildcard
    ``'*'`` to receive every event. ``publish`` invokes each matching
    subscriber exactly once, in registration order.

    The bus catches and swallows subscriber exceptions so a misbehaving
    listener can't break the event loop. Counts of swallowed errors are
    available on ``failure_count`` for tests.
    """

    def __init__(self) -> None:
        # Registration order is preserved by Python list ordering. We keep a
        # single flat list of (type_filter, callback) so we dispatch in
        # registration order regardless of which slot a sub falls into.
        self._subs: List[Tuple[str, Subscriber]] = []
        self.failure_count: int = 0
        self.published_count: int = 0

    # ---- subscription -----------------------------------------------------
    def subscribe(self, event_type: str, callback: Subscriber) -> Callable[[], None]:
        """Register a subscriber for ``event_type`` (or '*').

        Returns an unsubscribe function for convenience.
        """
        if not callable(callback):
            raise TypeError("callback must be callable")
        entry = (event_type, callback)
        self._subs.append(entry)

        def _unsub() -> None:
            try:
                self._subs.remove(entry)
            except ValueError:
                pass

        return _unsub

    # Alias matching the contract's "subscribe (or `on`)" wording.
    def on(self, event_type: str, callback: Subscriber) -> Callable[[], None]:
        return self.subscribe(event_type, callback)

    # ---- publication ------------------------------------------------------
    def publish(self, event: Event) -> None:
        """Dispatch ``event`` to every matching subscriber.

        Type-targeted subscribers and wildcard subscribers are invoked in the
        order they were registered (a single flat list). Each matching
        subscriber receives the event exactly once.
        """
        if not isinstance(event, Event):
            raise TypeError(f"publish() expects Event, got {type(event).__name__}")
        self.published_count += 1
        # Snapshot subs so a callback that subscribes/unsubscribes during
        # dispatch doesn't mutate the iteration set.
        for type_filter, cb in list(self._subs):
            if type_filter == event.type or type_filter == WILDCARD:
                try:
                    cb(event)
                except Exception:  # noqa: BLE001 -- bus must never propagate
                    self.failure_count += 1

    # Alias matching the contract's "publish (or `emit`)" wording.
    def emit(self, event: Event) -> None:
        self.publish(event)

    # ---- introspection ----------------------------------------------------
    def subscriber_count(self, event_type: Optional[str] = None) -> int:
        if event_type is None:
            return len(self._subs)
        return sum(1 for t, _ in self._subs if t == event_type)


__all__ = [
    "Event",
    "EventType",
    "EVENT_TYPES",
    "EventBus",
    "WILDCARD",
]
