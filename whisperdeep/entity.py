"""Entity model — the Player.

Sprint 1 introduced an Entity layer. For Sprint 2 we just need the Player —
an entity occupying a position on the current floor, rendered as '@'. Future
sprints will introduce monsters and items as additional entity subclasses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Entity:
    x: int
    y: int
    glyph: str = "?"
    name: str = "entity"
    blocks_movement: bool = False


@dataclass
class Player(Entity):
    glyph: str = "@"
    name: str = "you"
    blocks_movement: bool = True

    def move(self, dx: int, dy: int) -> None:
        """Move by an offset. Caller is responsible for collision checks."""
        self.x += dx
        self.y += dy
