"""Procedural dungeon generation — rooms-and-corridors.

A simple, deterministic generator that:

1. Tries to place N non-overlapping rectangular rooms via random placement +
   rejection sampling.
2. Carves each room interior to floor tiles.
3. Connects rooms in the order they were placed using L-shaped (HV or VH)
   tunnels of floor tiles. Connection is between room centers.
4. Places doors at the boundary between corridors and room interiors.
5. Places upstairs in the first room and downstairs in the last room.

All randomness flows from a single `random.Random(seed)` so generation is
deterministic for a given (width, height, seed) tuple.

Public API
----------
- ``DungeonGenerator(width, height, seed, **params)`` — configurable generator.
- ``generate(width, height, seed, **params)`` — module-level convenience.

Tunable parameters (kwargs)
---------------------------
- ``max_rooms`` (default 14)
- ``room_min_size`` (default 5)
- ``room_max_size`` (default 11)
- ``max_placement_tries`` (default 200)
- ``place_upstairs`` (default True) — whether the floor gets a '<' tile
- ``place_downstairs`` (default True) — whether the floor gets a '>' tile
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import tiles
from .floor import Floor, Room
from .tiles import TileKind


@dataclass
class GeneratorParams:
    max_rooms: int = 14
    room_min_size: int = 5
    room_max_size: int = 11
    max_placement_tries: int = 200
    place_upstairs: bool = True
    place_downstairs: bool = True


class DungeonGenerator:
    def __init__(
        self,
        width: int,
        height: int,
        seed: int,
        *,
        max_rooms: int = 14,
        room_min_size: int = 5,
        room_max_size: int = 11,
        max_placement_tries: int = 200,
        place_upstairs: bool = True,
        place_downstairs: bool = True,
    ) -> None:
        self.width = width
        self.height = height
        self.seed = seed
        self.params = GeneratorParams(
            max_rooms=max_rooms,
            room_min_size=room_min_size,
            room_max_size=room_max_size,
            max_placement_tries=max_placement_tries,
            place_upstairs=place_upstairs,
            place_downstairs=place_downstairs,
        )
        self.rng = random.Random(seed)

    # ---- public API ------------------------------------------------------
    def generate(self) -> Floor:
        floor = Floor(self.width, self.height)
        floor.seed = self.seed

        rooms = self._place_rooms()
        floor.rooms = rooms

        # Carve room interiors.
        for room in rooms:
            for x, y in room.interior_tiles():
                floor.set(x, y, tiles.floor())

        # Connect rooms in placement order with L-shaped corridors.
        # Track which tiles came from corridors (vs room interiors) so we can
        # detect transitions for door placement.
        corridor_tiles: set = set()
        for i in range(1, len(rooms)):
            cx_a, cy_a = rooms[i - 1].center
            cx_b, cy_b = rooms[i].center
            for cx, cy in self._l_corridor(cx_a, cy_a, cx_b, cy_b):
                # Don't overwrite room floors; just record the corridor path.
                if floor.get(cx, cy).is_wall:
                    floor.set(cx, cy, tiles.floor())
                    corridor_tiles.add((cx, cy))

        # Place doors where corridors enter rooms.
        self._place_doors(floor, rooms, corridor_tiles)

        # Place stairs.
        if rooms:
            if self.params.place_upstairs:
                ux, uy = rooms[0].center
                floor.set(ux, uy, tiles.upstairs())
                floor.upstairs_pos = (ux, uy)
            if self.params.place_downstairs:
                # Last room (or only room if there's just one).
                target = rooms[-1] if len(rooms) > 1 else rooms[0]
                dx, dy = target.center
                # If upstairs was placed at this exact tile (single-room
                # corner case), nudge to a different interior tile.
                if floor.upstairs_pos == (dx, dy):
                    for ix, iy in target.interior_tiles():
                        if (ix, iy) != floor.upstairs_pos:
                            dx, dy = ix, iy
                            break
                floor.set(dx, dy, tiles.downstairs())
                floor.downstairs_pos = (dx, dy)

        return floor

    # ---- room placement --------------------------------------------------
    def _place_rooms(self) -> List[Room]:
        rooms: List[Room] = []
        rng = self.rng
        p = self.params
        for _ in range(p.max_placement_tries):
            if len(rooms) >= p.max_rooms:
                break
            w = rng.randint(p.room_min_size, p.room_max_size)
            h = rng.randint(p.room_min_size, p.room_max_size)
            # Leave a 1-tile wall border so we can carve doors etc.
            x1 = rng.randint(1, self.width - w - 1)
            y1 = rng.randint(1, self.height - h - 1)
            candidate = Room(x1, y1, x1 + w, y1 + h)

            if any(candidate.overlaps(r) for r in rooms):
                continue
            rooms.append(candidate)
        return rooms

    # ---- corridor carving ------------------------------------------------
    def _l_corridor(
        self, x1: int, y1: int, x2: int, y2: int
    ) -> List[Tuple[int, int]]:
        """Yield tiles forming an L-shaped corridor from (x1,y1) to (x2,y2).

        The orientation (HV vs VH) is chosen by the RNG for variety.
        """
        path: List[Tuple[int, int]] = []
        if self.rng.random() < 0.5:
            # Horizontal first, then vertical.
            for x in range(min(x1, x2), max(x1, x2) + 1):
                path.append((x, y1))
            for y in range(min(y1, y2), max(y1, y2) + 1):
                path.append((x2, y))
        else:
            for y in range(min(y1, y2), max(y1, y2) + 1):
                path.append((x1, y))
            for x in range(min(x1, x2), max(x1, x2) + 1):
                path.append((x, y2))
        return path

    # ---- door placement --------------------------------------------------
    def _place_doors(
        self,
        floor: Floor,
        rooms: List[Room],
        corridor_tiles: set,
    ) -> None:
        """Place door tiles at corridor-room transitions.

        A corridor tile becomes a door if at least one of its 4-neighbors is
        the interior of a room AND at least one other 4-neighbor is also
        walkable (so the door is on a transition, not a dead end). We also
        require the orthogonal neighbors (relative to the door axis) to be
        walls, which is the classical "doorway in a wall" pattern.
        """
        room_interior_set = set()
        for room in rooms:
            for x, y in room.interior_tiles():
                room_interior_set.add((x, y))

        for cx, cy in corridor_tiles:
            # Skip if no longer a floor (e.g. overwritten somehow).
            if not floor.get(cx, cy).is_floor:
                continue
            # 4-neighbors.
            n = (cx, cy - 1)
            s = (cx, cy + 1)
            e = (cx + 1, cy)
            w = (cx - 1, cy)
            neighbors = [n, s, e, w]

            adjacent_to_room = any(p in room_interior_set for p in neighbors)
            if not adjacent_to_room:
                continue

            # Count walkable neighbors. A door must have >= 2 walkable
            # neighbors (one on each side), one of which is room interior.
            walkable_neighbors = [
                p for p in neighbors if floor.in_bounds(*p) and floor.get(*p).walkable
            ]
            if len(walkable_neighbors) < 2:
                continue

            # Determine the door's "axis": if both N and S walkable -> vertical
            # corridor (door is on a vertical corridor, sides E/W should be
            # walls). If E and W walkable -> horizontal corridor.
            n_walk = floor.in_bounds(*n) and floor.get(*n).walkable
            s_walk = floor.in_bounds(*s) and floor.get(*s).walkable
            e_walk = floor.in_bounds(*e) and floor.get(*e).walkable
            w_walk = floor.in_bounds(*w) and floor.get(*w).walkable

            if n_walk and s_walk and not e_walk and not w_walk:
                floor.set(cx, cy, tiles.door())
            elif e_walk and w_walk and not n_walk and not s_walk:
                floor.set(cx, cy, tiles.door())
            # Otherwise the corridor tile is at a junction; leave it as floor.


def generate(width: int, height: int, seed: int, **kwargs) -> Floor:
    """Module-level convenience: build a Floor with the given seed."""
    return DungeonGenerator(width, height, seed, **kwargs).generate()
