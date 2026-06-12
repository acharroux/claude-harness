"""World: a sequence of dungeon Floors derived from a master seed.

The World owns the set of generated Floors. Each floor's seed is derived
deterministically from the master seed plus the floor index (so the same
master seed always reproduces the same dungeon). Floors are generated lazily
on first access but all state is preserved across descent/ascent — once a
floor exists it is kept for the life of the World.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .archetypes import DungeonArchetype, assign_archetype, get_archetype
from .floor import Floor
from .generator import DungeonGenerator


def derive_floor_seed(master_seed: int, floor_index: int) -> int:
    """Derive a stable per-floor seed from a master seed.

    Uses a simple mixing function so different (master, index) pairs yield
    different floor layouts while remaining fully deterministic.
    """
    # Mix bits with a 64-bit-safe formula. Avoids collisions for sequential
    # indices and small masters.
    x = (master_seed * 2654435761 + floor_index * 40503 + 0x9E3779B1) & 0xFFFFFFFFFFFFFFFF
    # Final avalanche.
    x ^= (x >> 33)
    x = (x * 0xFF51AFD7ED558CCD) & 0xFFFFFFFFFFFFFFFF
    x ^= (x >> 33)
    return x


class World:
    def __init__(
        self,
        master_seed: int,
        num_floors: int = 3,
        width: int = 80,
        height: int = 40,
        eager: bool = False,
        forced_archetype: Optional[str] = None,
    ) -> None:
        if num_floors < 1:
            raise ValueError("num_floors must be >= 1")
        self.master_seed = master_seed
        self.num_floors = num_floors
        self.width = width
        self.height = height
        # Sprint 11: when set, every floor gets this archetype regardless of
        # the seed-derived assignment. Driven by ``--archetype ID`` from the
        # CLI; resolved up front so a bad id raises immediately.
        self._forced_archetype: Optional[DungeonArchetype] = (
            get_archetype(forced_archetype) if forced_archetype else None
        )
        self._floors: Dict[int, Floor] = {}
        if eager:
            for i in range(num_floors):
                self.get_floor(i)

    # ---- floor access ----------------------------------------------------
    def get_floor(self, index: int) -> Floor:
        if index < 0 or index >= self.num_floors:
            raise IndexError(
                f"Floor index {index} out of range [0, {self.num_floors})"
            )
        if index not in self._floors:
            seed = derive_floor_seed(self.master_seed, index)
            # First floor has no upstairs; last floor has no downstairs.
            place_upstairs = index > 0
            place_downstairs = index < self.num_floors - 1
            gen = DungeonGenerator(
                self.width,
                self.height,
                seed,
                place_upstairs=place_upstairs,
                place_downstairs=place_downstairs,
            )
            floor = gen.generate()
            # Sprint 11: assign the archetype BEFORE returning to callers.
            if self._forced_archetype is not None:
                floor.archetype = self._forced_archetype
            else:
                floor.archetype = assign_archetype(self.master_seed, index)
            self._floors[index] = floor
        return self._floors[index]

    def is_first(self, index: int) -> bool:
        return index == 0

    def is_last(self, index: int) -> bool:
        return index == self.num_floors - 1

    def __len__(self) -> int:
        return self.num_floors
