"""Tile primitives for the dungeon grid.

A tile has a `kind` (wall/floor/door/upstairs/downstairs) which determines its
glyph and walkability. Glyphs follow the documented legend:

    '#' wall
    '.' floor
    '+' door
    '<' upstairs
    '>' downstairs
    '@' player    (rendered by the entity layer, never stored as a tile)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TileKind(str, Enum):
    WALL = "wall"
    FLOOR = "floor"
    DOOR = "door"
    UPSTAIRS = "upstairs"
    DOWNSTAIRS = "downstairs"


_GLYPH_BY_KIND = {
    TileKind.WALL: "#",
    TileKind.FLOOR: ".",
    TileKind.DOOR: "+",
    TileKind.UPSTAIRS: "<",
    TileKind.DOWNSTAIRS: ">",
}

_WALKABLE = {TileKind.FLOOR, TileKind.DOOR, TileKind.UPSTAIRS, TileKind.DOWNSTAIRS}


@dataclass
class Tile:
    kind: TileKind = TileKind.WALL

    @property
    def glyph(self) -> str:
        return _GLYPH_BY_KIND[self.kind]

    @property
    def walkable(self) -> bool:
        return self.kind in _WALKABLE

    @property
    def is_wall(self) -> bool:
        return self.kind == TileKind.WALL

    @property
    def is_floor(self) -> bool:
        return self.kind == TileKind.FLOOR

    @property
    def is_door(self) -> bool:
        return self.kind == TileKind.DOOR

    @property
    def is_upstairs(self) -> bool:
        return self.kind == TileKind.UPSTAIRS

    @property
    def is_downstairs(self) -> bool:
        return self.kind == TileKind.DOWNSTAIRS

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Tile({self.kind.value})"


def wall() -> Tile:
    return Tile(TileKind.WALL)


def floor() -> Tile:
    return Tile(TileKind.FLOOR)


def door() -> Tile:
    return Tile(TileKind.DOOR)


def upstairs() -> Tile:
    return Tile(TileKind.UPSTAIRS)


def downstairs() -> Tile:
    return Tile(TileKind.DOWNSTAIRS)
