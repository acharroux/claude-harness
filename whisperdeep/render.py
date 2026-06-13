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

Sprint 8 additions:

* :func:`render_panel` — re-exported from :mod:`whisperdeep.panel` so
  callers can pull the panel renderer from a single module.
* :func:`render_frame_with_whispers` — composes the dungeon grid and the
  whisper panel side-by-side (right-of-grid layout, two-space gutter)
  WITHOUT modifying :func:`render_frame`'s output. The original
  :func:`render_frame` returns the same byte string regardless of whether
  a Whisperer is wired in.
"""
from __future__ import annotations

from typing import Iterable, Optional

from .archetypes import (
    ANSI_RESET,
    DEFAULT_GLYPHS,
    palette_key_for_kind,
    palette_to_ansi,
)
from .floor import Floor
from .game import Game
from .panel import (
    DEFAULT_PANEL_HEIGHT,
    DEFAULT_PANEL_WIDTH,
    GUTTER,
    render_panel,
)
from .tiles import TileKind


def _glyph_for_floor_cell(floor: Floor, x: int, y: int) -> str:
    """Return the rendered glyph for a single cell, honoring archetype overrides.

    Falls back to Sprint-1/2 defaults when the floor has no archetype or
    when the archetype does not override that kind. Player ('@') is never
    handled here -- callers overlay it themselves.
    """
    kind = floor.get(x, y).kind
    archetype = getattr(floor, "archetype", None)
    if archetype is not None:
        return archetype.glyph_for(kind)
    return DEFAULT_GLYPHS.get(kind, floor.get(x, y).glyph)


def render_floor(floor: Floor) -> str:
    """Render a floor (no entities) as a multiline string."""
    lines = []
    for y in range(floor.height):
        row = []
        for x in range(floor.width):
            row.append(_glyph_for_floor_cell(floor, x, y))
        lines.append("".join(row))
    return "\n".join(lines)


def render_floor_glyphs(floor: Floor):
    """Return the floor's glyph snapshot (alias for :meth:`Floor.snapshot_glyphs`).

    Sprint 11: provided as a top-level helper for parity with
    :func:`render_floor`. The result is a tuple of tuples of single-character
    glyph strings (after archetype glyph overrides are applied).
    """
    return floor.snapshot_glyphs()


def render_frame(game: Game) -> str:
    """Render the current floor with the player overlaid as '@'.

    Sprint 8 contract: this function is byte-identical regardless of
    whether the Game has a Whisperer attached. It is the original Sprint-2
    renderer and produces ONLY the dungeon grid. To get the composite
    grid+panel output, call :func:`render_frame_with_whispers`.

    Sprint 11: the per-cell glyph honors the floor's archetype overrides.
    The player glyph ('@') and the stair glyphs ('<', '>') are reserved
    and never substituted.
    """
    floor = game.floor
    rows = []
    for y in range(floor.height):
        row = []
        for x in range(floor.width):
            if x == game.player.x and y == game.player.y:
                row.append(game.player.glyph)
            else:
                row.append(_glyph_for_floor_cell(floor, x, y))
        rows.append("".join(row))
    return "\n".join(rows)


def colorize_frame(game: Game) -> str:
    """Sprint 11: render :func:`render_frame` with ANSI colour codes applied.

    Each cell is wrapped in an ANSI foreground escape sequence drawn from
    the floor's archetype palette (256-color or truecolor depending on the
    palette value type). Cells whose palette key cannot be resolved are
    emitted as plain ASCII (no ESC), so the output stays robust.

    The plain-text glyphs (after stripping ANSI sequences) are identical to
    :func:`render_frame`. Default ``render_frame`` continues to emit zero
    ESC characters; colour is opt-in via this helper. Full panel/colour
    wiring lands in Sprint 12.
    """
    floor = game.floor
    archetype = getattr(floor, "archetype", None)
    palette = archetype.palette if archetype is not None else {}
    rows = []
    for y in range(floor.height):
        row_parts = []
        for x in range(floor.width):
            if x == game.player.x and y == game.player.y:
                glyph = game.player.glyph
                ansi = palette_to_ansi(palette, "player_fg") if palette else ""
            else:
                kind = floor.get(x, y).kind
                glyph = _glyph_for_floor_cell(floor, x, y)
                key = palette_key_for_kind(kind)
                ansi = palette_to_ansi(palette, key) if palette else ""
            if ansi:
                row_parts.append(f"{ansi}{glyph}{ANSI_RESET}")
            else:
                row_parts.append(glyph)
        rows.append("".join(row_parts))
    return "\n".join(rows)


def render_frame_with_whispers(
    game: Game,
    *,
    panel_width: int = DEFAULT_PANEL_WIDTH,
    panel_height: Optional[int] = None,
) -> str:
    """Render the dungeon grid AND a whisper panel side-by-side.

    Layout: right-of-grid. Each row of the output is
    ``"<grid_row><gutter><panel_row>"``. The panel height defaults to the
    floor height so every grid row gets a panel row beside it; pass
    ``panel_height`` to override.

    If the Game has no Whisperer (``game.whisperer is None``), the panel
    is empty (rendered as blank padding, since callers may still want a
    consistent layout). For "no panel at all" callers should call
    :func:`render_frame` instead.
    """
    grid = render_frame(game)
    grid_rows = grid.split("\n")
    if panel_height is None:
        panel_height = len(grid_rows)
    whispers = []
    if game.whisperer is not None:
        whispers = list(getattr(game.whisperer, "whispers", []) or [])
    panel = render_panel(whispers, width=panel_width, height=panel_height)
    panel_rows = panel.split("\n")
    # Pad whichever side is shorter with blank rows of the appropriate
    # width so the output is rectangular.
    grid_width = max((len(r) for r in grid_rows), default=0)
    n_rows = max(len(grid_rows), len(panel_rows))
    out: list = []
    for i in range(n_rows):
        g = grid_rows[i] if i < len(grid_rows) else (" " * grid_width)
        p = panel_rows[i] if i < len(panel_rows) else (" " * panel_width)
        # Ensure grid row is padded to a stable width for clean composition.
        if len(g) < grid_width:
            g = g.ljust(grid_width)
        out.append(f"{g}{GUTTER}{p}")
    return "\n".join(out)


GLYPH_LEGEND = {
    "#": "wall",
    ".": "floor",
    "+": "door",
    "<": "upstairs",
    ">": "downstairs",
    "@": "player",
}


__all__ = [
    "render_floor",
    "render_floor_glyphs",
    "render_frame",
    "render_frame_with_whispers",
    "render_panel",
    "colorize_frame",
    "GLYPH_LEGEND",
    "DEFAULT_PANEL_WIDTH",
    "DEFAULT_PANEL_HEIGHT",
]
