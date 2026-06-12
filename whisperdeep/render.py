"""ASCII renderer — produce a frame string for a Game.

This module is intentionally framework-free: it converts game state to a
string. The CLI / future TUI is responsible for printing it. Tests can call
``render_frame`` directly to compare frames byte-for-byte.

Glyph legend:

    '#' wall
    '.' floor
    '+' door
    '<' upstairs
    '>' downstairs
    '@' player
"""
from __future__ import annotations

from typing import Iterable

from .floor import Floor
from .game import Game


def render_floor(floor: Floor) -> str:
    """Render a floor (no entities) as a multiline string."""
    lines = []
    for y in range(floor.height):
        row = []
        for x in range(floor.width):
            row.append(floor.get(x, y).glyph)
        lines.append("".join(row))
    return "\n".join(lines)


def render_frame(game: Game) -> str:
    """Render the current floor with the player overlaid as '@'."""
    floor = game.floor
    rows = []
    for y in range(floor.height):
        row = []
        for x in range(floor.width):
            if x == game.player.x and y == game.player.y:
                row.append(game.player.glyph)
            else:
                row.append(floor.get(x, y).glyph)
        rows.append("".join(row))
    return "\n".join(rows)


GLYPH_LEGEND = {
    "#": "wall",
    ".": "floor",
    "+": "door",
    "<": "upstairs",
    ">": "downstairs",
    "@": "player",
}
