"""Floor (a 2D map) and Room data structures.

The Floor is the grid the dungeon generator populates. It owns its tile grid,
its list of rooms, and the locations of any stairs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple

from . import tiles
from .tiles import Tile, TileKind

# Sprint 11: archetypes are pure data; importing here keeps the layering
# straightforward (Floor depends on tiles + archetypes only).
from .archetypes import DEFAULT_GLYPHS, DungeonArchetype


@dataclass(frozen=True)
class Room:
    """An axis-aligned rectangular room.

    Coordinates are inclusive on (x1, y1) and exclusive on (x2, y2) — i.e.
    width = x2 - x1, height = y2 - y1. The walls live OUTSIDE this rectangle;
    the rectangle itself is the interior floor of the room.
    """

    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def center(self) -> Tuple[int, int]:
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)

    def contains(self, x: int, y: int) -> bool:
        return self.x1 <= x < self.x2 and self.y1 <= y < self.y2

    def overlaps(self, other: "Room", padding: int = 1) -> bool:
        """Return True iff the *padded* rectangles overlap.

        Padding=1 ensures rooms don't touch wall-to-wall, which would let a
        corridor pierce two rooms at once.
        """
        return not (
            self.x2 + padding <= other.x1
            or other.x2 + padding <= self.x1
            or self.y2 + padding <= other.y1
            or other.y2 + padding <= self.y1
        )

    def interior_tiles(self) -> Iterable[Tuple[int, int]]:
        for y in range(self.y1, self.y2):
            for x in range(self.x1, self.x2):
                yield x, y


class Floor:
    """A rectangular grid of Tiles."""

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("Floor dimensions must be positive")
        self.width: int = width
        self.height: int = height
        # Row-major: grid[y][x]. All walls by default.
        self.grid: List[List[Tile]] = [
            [tiles.wall() for _ in range(width)] for _ in range(height)
        ]
        self.rooms: List[Room] = []
        self.upstairs_pos: Optional[Tuple[int, int]] = None
        self.downstairs_pos: Optional[Tuple[int, int]] = None
        # The seed actually used to generate this floor (set by the generator).
        self.seed: Optional[int] = None
        # Sprint 11: thematic archetype for this floor (set by World.get_floor
        # before the Floor escapes to callers). Defaults to None for
        # defensively-constructed Floors; render code degrades to Sprint-1/2
        # default glyphs in that case.
        self.archetype: Optional[DungeonArchetype] = None

    # ---- bounds & access -------------------------------------------------
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def get(self, x: int, y: int) -> Tile:
        if not self.in_bounds(x, y):
            raise IndexError(f"({x},{y}) out of bounds for {self.width}x{self.height}")
        return self.grid[y][x]

    def set(self, x: int, y: int, tile: Tile) -> None:
        if not self.in_bounds(x, y):
            raise IndexError(f"({x},{y}) out of bounds for {self.width}x{self.height}")
        self.grid[y][x] = tile

    def kind_at(self, x: int, y: int) -> TileKind:
        return self.get(x, y).kind

    def walkable(self, x: int, y: int) -> bool:
        return self.in_bounds(x, y) and self.get(x, y).walkable

    # ---- iteration -------------------------------------------------------
    def iter_coords(self) -> Iterable[Tuple[int, int]]:
        for y in range(self.height):
            for x in range(self.width):
                yield x, y

    def walkable_tiles(self) -> List[Tuple[int, int]]:
        return [(x, y) for x, y in self.iter_coords() if self.get(x, y).walkable]

    # ---- snapshotting ----------------------------------------------------
    def snapshot(self) -> Tuple[Tuple[str, ...], ...]:
        """Return an immutable snapshot of the tile grid (kinds only).

        Useful for hashing/comparing floor layouts in tests and
        for verifying floor persistence across descent/ascent.
        """
        return tuple(
            tuple(self.grid[y][x].kind.value for x in range(self.width))
            for y in range(self.height)
        )

    def snapshot_glyphs(self) -> Tuple[Tuple[str, ...], ...]:
        """Sprint 11: snapshot rendered glyphs reflecting the archetype.

        Unlike :meth:`snapshot` (which returns the kind name strings),
        ``snapshot_glyphs`` returns single-character glyph strings honoring
        any per-archetype overrides. When ``self.archetype`` is None,
        Sprint-1/2 default glyphs are returned. The shape (rows x cols) is
        identical to :meth:`snapshot`.
        """
        return tuple(
            tuple(self._glyph_at(x, y) for x in range(self.width))
            for y in range(self.height)
        )

    def _glyph_at(self, x: int, y: int) -> str:
        kind = self.grid[y][x].kind
        if self.archetype is not None:
            return self.archetype.glyph_for(kind)
        return DEFAULT_GLYPHS.get(kind, "?")

    def __repr__(self) -> str:  # pragma: no cover
        return f"Floor({self.width}x{self.height}, rooms={len(self.rooms)})"
