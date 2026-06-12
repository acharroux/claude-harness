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
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .entity import Player
from .floor import Floor
from .world import World


class Game:
    def __init__(self, world: World) -> None:
        self.world = world
        self.current_floor_index: int = 0
        # Spawn the player on floor 0. We pick the first room's center if
        # available, otherwise the first walkable tile.
        floor0 = world.get_floor(0)
        spawn = self._choose_spawn(floor0)
        self.player = Player(x=spawn[0], y=spawn[1])
        # Number of player-driven actions taken (turn counter).
        self.turns: int = 0

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
        (We still consider a wall bump a "turn" so future combat / time
        systems behave consistently. Sprint 2 only requires position-unchanged,
        which holds either way.)
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
        return True

    def descend(self) -> bool:
        """If standing on '>', go to the next floor and place the player at '<'.

        Returns True on success, False if not standing on '>' or already on
        the last floor.
        """
        floor = self.floor
        tile = floor.get(self.player.x, self.player.y)
        if not tile.is_downstairs:
            return False
        if self.world.is_last(self.current_floor_index):
            return False
        self.current_floor_index += 1
        new_floor = self.floor
        target = new_floor.upstairs_pos
        if target is None:
            # Should not happen for non-first floors, but be defensive.
            target = self._choose_spawn(new_floor)
        self.player.x, self.player.y = target
        return True

    def ascend(self) -> bool:
        """If standing on '<', go to the previous floor and place the player at '>'.

        Returns True on success, False if not standing on '<' or already on
        floor 0.
        """
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
        return True

    # ---- helpers ---------------------------------------------------------
    def teleport(self, x: int, y: int) -> None:
        """Test/integration helper: place the player on an arbitrary walkable tile."""
        if not self.floor.walkable(x, y):
            raise ValueError(f"({x},{y}) is not walkable on floor {self.current_floor_index}")
        self.player.x = x
        self.player.y = y
