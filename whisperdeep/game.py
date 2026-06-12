"""Game state and turn/action handling.

The Game ties together a World, a Player, and the floor index the player is
currently on. It exposes the actions the input layer (or a test harness) can
invoke: move, descend, ascend.

Movement rules (Sprint 1 + Sprint 2):
- '#' walls are impassable; bumping into a wall is a no-op.
- '.' floor, '+' doors, '<' upstairs, '>' downstairs are walkable.
- Stepping onto '>' does NOT auto-descend; the player must invoke `descend()`.
- Same for '<' / `ascend()`. This keeps movement and floor transitions
  cleanly separable for testing.

Sprint 7 wires the Whisperer into the Game lifecycle. When ``whisperer=True``
(the default), :meth:`Game.from_seed` creates an EventBus, picks an adapter
via the lazily-imported adapter factory, and constructs a Whisperer that
subscribes to the bus. The Game publishes ``run_started`` on construction
and ``descended`` whenever the player descends a staircase. When
``whisperer=False`` the Game is unchanged from Sprint 2 (no bus, no
whisperer, no events).

Sprint 8 adds two more event sources to the Game's lifecycle:

* :meth:`Game.observe_kind` — a public hook that publishes a ``first_sight``
  event (idempotent per kind for the run). Tests and (future) higher-fidelity
  monster/item systems can call this to trigger the first-sight naming
  pipeline.
* Room-entered detection on :meth:`Game.from_seed`, :meth:`Game.descend`,
  and :meth:`Game.try_move`. The Game publishes a ``room_entered`` event
  whenever the player crosses into a room they haven't been in this run.
  Per-(floor, room_id) dedupe is enforced by the Whisperer; the Game also
  short-circuits the publish if it can recognize a re-entry locally so
  identical events aren't even raised.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Set, Tuple

from .entity import Player
from .events import Event, EventBus, EventType
from .floor import Floor
from .world import World


class Game:
    def __init__(
        self,
        world: World,
        *,
        events: Optional[EventBus] = None,
        whisperer: Optional[object] = None,
        audio: Optional[object] = None,
    ) -> None:
        self.world = world
        self.current_floor_index: int = 0
        # Sprint 12: opt-in audio adapter. None disables audio entirely.
        self.audio = audio
        if audio is not None and events is not None:
            self._wire_audio(events, audio)
        # Spawn the player on floor 0. We pick the first room's center if
        # available, otherwise the first walkable tile.
        floor0 = world.get_floor(0)
        spawn = self._choose_spawn(floor0)
        self.player = Player(x=spawn[0], y=spawn[1])
        # Number of player-driven actions taken (turn counter).
        self.turns: int = 0
        # Sprint 7: optional event bus + whisperer.
        self.events: Optional[EventBus] = events
        self.whisperer = whisperer
        # Sprint 8: per-run dedupe of (floor, room_id) for Game-side
        # short-circuiting BEFORE publishing redundant events. The
        # Whisperer also dedupes; this is just a courtesy / cheaper path.
        self._rooms_seen_local: Set[Tuple[int, int]] = set()
        # Per-run dedupe of observed kinds for first_sight idempotency at
        # the Game layer. The Whisperer also dedupes; either layer alone
        # suffices, but keeping both honest is cheap.
        self._kinds_observed: Set[str] = set()
        # Sprint 10: lifecycle bookkeeping.
        self._run_ended: bool = False
        # Track the deepest floor index visited; used by the chronicle to
        # report 'floors_reached'.
        self.max_floor_reached: int = 0
        # Track the seed (forwarded by from_seed) so chronicles can include
        # it without rummaging through the World.
        self.seed: Optional[int] = None

    # ---- factories -------------------------------------------------------
    @classmethod
    def from_seed(
        cls,
        seed: int,
        *,
        num_floors: int = 3,
        width: int = 80,
        height: int = 40,
        whisperer: bool = True,
        adapter: str = "offline",
        budget: Optional[int] = None,
        model: Optional[str] = None,
        forced_archetype: Optional[str] = None,
        audio: Optional[object] = None,
    ) -> "Game":
        """Construct a Game directly from a master seed.

        When ``whisperer`` is True (default), an EventBus and Whisperer are
        wired up; the Game publishes ``run_started`` immediately and will
        publish ``descended`` on staircase descent. When False, no bus or
        whisperer is created and gameplay does not publish events (Sprint 2
        behavior preserved).

        Sprint 11: ``forced_archetype`` (an archetype id string) overrides the
        seed-derived archetype assignment for every floor in the run. Used
        by the ``--archetype`` CLI flag.
        """
        world = World(
            master_seed=seed,
            num_floors=num_floors,
            width=width,
            height=height,
            forced_archetype=forced_archetype,
        )
        if not whisperer:
            game = cls(world, audio=audio)
            game.seed = seed
            game._adapter_name = "none"
            return game
        # Lazy imports keep Game's module-level imports adapter-free.
        from .adapter_factory import make_adapter
        from .whisperer import DEFAULT_BUDGET, Whisperer

        bus = EventBus()
        llm = make_adapter(adapter, seed=seed, model=model)
        wh = Whisperer(
            adapter=llm,
            bus=bus,
            seed=seed,
            budget=budget if budget is not None else DEFAULT_BUDGET,
        )
        game = cls(world, events=bus, whisperer=wh, audio=audio)
        # Sprint 10: stash the seed and adapter name on the Game so
        # downstream consumers (e.g., the Chronicle generator) can read
        # them without poking at the World/adapter internals.
        game.seed = seed
        game._adapter_name = adapter
        # Publish the run_started event AFTER subscribing.
        bus.publish(
            Event(
                type=EventType.RUN_STARTED.value,
                payload={
                    "seed": seed,
                    "num_floors": num_floors,
                    "archetype": game._archetype_id_for_floor(0),
                },
                turn=0,
                floor=0,
            )
        )
        # Sprint 8: also publish a room_entered for the spawn room so the
        # atmospheric prose pipeline fires on the very first frame.
        game._maybe_publish_room_entered(turn=0)
        return game

    # ---- accessors -------------------------------------------------------
    @property
    def floor(self) -> Floor:
        return self.world.get_floor(self.current_floor_index)

    # ---- spawn -----------------------------------------------------------
    @staticmethod
    def _choose_spawn(floor: Floor) -> Tuple[int, int]:
        if floor.rooms:
            return floor.rooms[0].center
        walkables = floor.walkable_tiles()
        if not walkables:
            raise RuntimeError("Floor has no walkable tiles to spawn on")
        return walkables[0]

    # ---- actions ---------------------------------------------------------
    def try_move(self, dx: int, dy: int) -> bool:
        """Attempt to move the player by (dx,dy). Returns True iff moved.

        A wall bump increments the turn counter but does NOT move the player.
        """
        nx = self.player.x + dx
        ny = self.player.y + dy
        if not self.floor.in_bounds(nx, ny):
            self.turns += 1
            return False
        if not self.floor.get(nx, ny).walkable:
            self.turns += 1
            return False
        self.player.x = nx
        self.player.y = ny
        self.turns += 1
        # Sprint 8: detect room transitions and publish room_entered.
        self._maybe_publish_room_entered(turn=self.turns)
        return True

    def descend(self) -> bool:
        """If standing on '>', go to the next floor and place the player at '<'.

        Returns True on success, False if not standing on '>' or already on
        the last floor. On success and when the bus is wired, publishes a
        ``descended`` event.
        """
        floor = self.floor
        tile = floor.get(self.player.x, self.player.y)
        if not tile.is_downstairs:
            return False
        if self.world.is_last(self.current_floor_index):
            return False
        from_floor = self.current_floor_index
        self.current_floor_index += 1
        if self.current_floor_index > self.max_floor_reached:
            self.max_floor_reached = self.current_floor_index
        new_floor = self.floor
        target = new_floor.upstairs_pos
        if target is None:
            target = self._choose_spawn(new_floor)
        self.player.x, self.player.y = target
        self.turns += 1
        if self.events is not None:
            self.events.publish(
                Event(
                    type=EventType.DESCENDED.value,
                    payload={
                        "from": from_floor,
                        "to": self.current_floor_index,
                        "archetype": self._archetype_id_for_floor(self.current_floor_index),
                    },
                    turn=self.turns,
                    floor=self.current_floor_index,
                )
            )
        # Sprint 8: also publish room_entered for the landing room on the
        # new floor.
        self._maybe_publish_room_entered(turn=self.turns)
        return True

    def ascend(self) -> bool:
        """If standing on '<', go to the previous floor and place the player at '>'."""
        floor = self.floor
        tile = floor.get(self.player.x, self.player.y)
        if not tile.is_upstairs:
            return False
        if self.world.is_first(self.current_floor_index):
            return False
        self.current_floor_index -= 1
        new_floor = self.floor
        target = new_floor.downstairs_pos
        if target is None:
            target = self._choose_spawn(new_floor)
        self.player.x, self.player.y = target
        # Sprint 8: ascend also fires room_entered (on the room the player
        # arrives in). This is symmetric with descend; tests don't require
        # it but it keeps behavior consistent.
        self._maybe_publish_room_entered(turn=self.turns)
        return True

    # ---- helpers ---------------------------------------------------------
    def teleport(self, x: int, y: int) -> None:
        """Test/integration helper: place the player on an arbitrary walkable tile."""
        if not self.floor.walkable(x, y):
            raise ValueError(f"({x},{y}) is not walkable on floor {self.current_floor_index}")
        self.player.x = x
        self.player.y = y
        # Sprint 8: a teleport may put the player in a new room, so check.
        self._maybe_publish_room_entered(turn=self.turns)

    # ---- Sprint 8: room detection + observe_kind hook -------------------
    def _current_room_id(self) -> Optional[int]:
        """Return the integer index of the room the player is currently in.

        Uses :class:`Floor.rooms` and :meth:`Room.contains`. Returns None
        when the player is in a corridor / on a stair tile that no room
        contains.
        """
        floor = self.floor
        rooms = getattr(floor, "rooms", None) or []
        for idx, r in enumerate(rooms):
            if r.contains(self.player.x, self.player.y):
                return idx
        return None

    def _maybe_publish_room_entered(self, *, turn: int) -> None:
        """Publish a ``room_entered`` event for the player's current room.

        Skips when the bus is not wired, when the player is not currently
        inside any room (corridor / stair tile), and when the
        (floor, room_id) pair has already been published this run.
        """
        if self.events is None:
            return
        room_id = self._current_room_id()
        if room_id is None:
            return
        key = (self.current_floor_index, room_id)
        if key in self._rooms_seen_local:
            return
        self._rooms_seen_local.add(key)
        self.events.publish(
            Event(
                type=EventType.ROOM_ENTERED.value,
                payload={
                    "floor": self.current_floor_index,
                    "room_id": room_id,
                    "archetype": self._archetype_id_for_floor(self.current_floor_index),
                },
                turn=turn,
                floor=self.current_floor_index,
            )
        )

    def observe_kind(self, kind: str, category: str = "monster") -> bool:
        """Publish a ``first_sight`` event for ``kind`` (idempotent).

        Returns True if a new first_sight event was published this run for
        this kind, False if the kind was already seen (no-op) or if the
        Game has no Whisperer wired (also a no-op).

        ``category`` should be ``"monster"`` or ``"item"``; other values
        are accepted and forwarded verbatim to the event payload.
        """
        if not isinstance(kind, str) or not kind:
            return False
        if self.events is None:
            # Whisperer disabled; the hook is a documented no-op.
            return False
        if kind in self._kinds_observed:
            return False
        self._kinds_observed.add(kind)
        self.events.publish(
            Event(
                type=EventType.FIRST_SIGHT.value,
                payload={
                    "kind": kind,
                    "category": category,
                    "archetype": self._archetype_id_for_floor(self.current_floor_index),
                },
                turn=self.turns,
                floor=self.current_floor_index,
            )
        )
        return True

    # ---- Sprint 12: audio wiring ----------------------------------------
    def _wire_audio(self, bus: "EventBus", audio: object) -> None:
        """Subscribe ``audio.play`` to the event bus via EVENT_TO_CUE.

        Imported lazily so the audio module remains optional.
        """
        from .audio import EVENT_TO_CUE

        def _handle(ev: Event) -> None:
            cue = EVENT_TO_CUE.get(ev.type)
            if cue:
                try:
                    audio.play(cue)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 -- audio must never crash run
                    pass

        bus.subscribe("*", _handle)

    def attach_audio(self, audio: object) -> None:
        """Attach an audio adapter post-construction.

        For Games constructed without an event bus (whisperer=False) this
        merely stores the adapter; without a bus there is no event source
        to drive cues, but explicit calls to ``self.audio.play(...)``
        still work.
        """
        self.audio = audio
        if audio is not None and self.events is not None:
            self._wire_audio(self.events, audio)

    # ---- Sprint 11: archetype lookup helper -----------------------------
    def _archetype_id_for_floor(self, floor_index: int) -> Optional[str]:
        """Return the archetype id for ``floor_index``, or None if unset.

        Defensive: floors built outside the World may have ``archetype`` None.
        """
        try:
            f = self.world.get_floor(floor_index)
        except Exception:  # noqa: BLE001 -- defensive
            return None
        a = getattr(f, "archetype", None)
        if a is None:
            return None
        return getattr(a, "id", None)

    # ---- Sprint 10: run lifecycle hook ----------------------------------
    def end_run(self, cause: str = "quit", summary: Optional[dict] = None) -> bool:
        """Publish the canonical run_ended + epitaph events for this run.

        Idempotent: a second call returns False without publishing.

        When the Whisperer is disabled (``self.events is None``), this is a
        documented safe no-op that returns False without raising.

        Returns True if events were actually published; False otherwise.
        """
        if self._run_ended:
            return False
        if self.events is None:
            # No bus -> no events. Mark ended so subsequent calls are
            # also a clean no-op.
            self._run_ended = True
            return False
        self._run_ended = True
        # Bump the turn for end-of-run events so they don't get coalesced
        # with run_started / room_entered whispers that fired at turn 0
        # (the Sprint-7 per-turn cap is keyed on the turn integer).
        end_turn = max(self.turns, 0) + 1
        payload = {
            "cause": cause,
            "floors_reached": self.max_floor_reached + 1,
            "turns": self.turns,
            "archetype": self._archetype_id_for_floor(self.current_floor_index),
        }
        if isinstance(summary, dict):
            payload["summary"] = summary
        self.events.publish(
            Event(
                type=EventType.RUN_ENDED.value,
                payload=payload,
                turn=end_turn,
                floor=self.current_floor_index,
            )
        )
        # Bump the turn again so the epitaph is not coalesced with
        # run_ended either.
        epitaph_turn = end_turn + 1
        self.events.publish(
            Event(
                type=EventType.EPITAPH.value,
                payload={
                    "cause": cause,
                    "archetype": self._archetype_id_for_floor(self.current_floor_index),
                },
                turn=epitaph_turn,
                floor=self.current_floor_index,
            )
        )
        return True
