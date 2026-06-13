"""Whisper panel renderer (Sprint 8).

The panel is a fixed-width / fixed-height ASCII block that the CLI
composes alongside the dungeon grid so players can actually read the
Whisperer's output. The panel is plain ASCII (with optional box-drawing
characters), no curses, no colour codes, no input handling.

Layering: this module imports only stdlib + ``typing``. It accepts any
"whisper-like" record — anything with a ``text`` attribute (preferred) or
a ``text`` key (dict). It does NOT import :mod:`whisperdeep.llm` and it
does NOT import :mod:`whisperdeep.events` directly. The dataclass
:class:`whisperdeep.whisperer.Whisper` works without any further
adaptation because it has both a ``text`` attribute and a
``source_event_type`` attribute.

Conventions documented and tested in Sprint 8:

* Panel layout choice: **right-of-grid**. The composite renderer in
  :mod:`whisperdeep.render` glues each grid row to the corresponding
  panel row with a two-space gutter, so every line of the composite
  output looks like ``"<grid_row>  <panel_row>"``.
* Panel width default: ``30`` columns. Panel height default: ``12`` rows.
  Both are overridable.
* Newest at the **bottom** (most-recent whisper is the last visible row).
* When more whispers exist than fit, the OLDEST visible whispers are
  silently dropped: the panel is a sliding window over the most-recent
  whispers. The original whisper log is never mutated.
* Per-category prefix markers (visually distinguishable):

      ``room_entered``    -> ``~`` (atmospheric prose)
      ``first_sight``     -> ``*`` (a new name has been minted)
      everything else     -> ``>`` (generic whisper)

* Long whispers are wrapped to the panel width on word boundaries; words
  longer than the available width are hard-broken so the panel never
  overflows. Each whisper's first wrapped row carries the prefix marker;
  continuation rows are indented by two spaces so the visual grouping is
  obvious.
* Empty rows are padded to the full panel width so adjacent grid rows in
  the composite layout don't shift around.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence


DEFAULT_PANEL_WIDTH: int = 30
DEFAULT_PANEL_HEIGHT: int = 12
GUTTER: str = "  "  # two-space gutter between grid and panel

# Per-category visual marker. Stable; documented in module docstring.
CATEGORY_MARKERS: dict = {
    "room_entered": "~",
    "first_sight": "*",
}
DEFAULT_MARKER: str = ">"
CONTINUATION_INDENT: str = "  "


def _whisper_text(w: Any) -> str:
    """Extract the text from a whisper-like record (attribute or dict)."""
    text = getattr(w, "text", None)
    if text is None and hasattr(w, "get"):
        text = w.get("text")
    if text is None:
        return ""
    return str(text)


def _whisper_category(w: Any) -> Optional[str]:
    """Extract the source_event_type from a whisper-like record."""
    cat = getattr(w, "source_event_type", None)
    if cat is None and hasattr(w, "get"):
        cat = w.get("source_event_type")
    if cat is None:
        return None
    return str(cat)


def _marker_for(category: Optional[str]) -> str:
    if not category:
        return DEFAULT_MARKER
    return CATEGORY_MARKERS.get(category, DEFAULT_MARKER)


def _wrap_text(text: str, width: int) -> List[str]:
    """Wrap ``text`` into lines no longer than ``width``.

    Words longer than ``width`` are hard-broken. Returns at least one
    line (possibly empty) so callers don't have to special-case a no-op.
    """
    if width <= 0:
        return [""]
    words = text.split()
    if not words:
        return [""]
    lines: List[str] = []
    current = ""
    for word in words:
        # Hard-break extremely long words.
        while len(word) > width:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:width])
            word = word[width:]
        if not current:
            candidate = word
        else:
            candidate = current + " " + word
        if len(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def _render_one_whisper(
    w: Any,
    width: int,
    *,
    marker: Optional[str] = None,
) -> List[str]:
    """Render a single whisper as a list of width-padded lines.

    The first line carries the per-category marker followed by a space.
    Continuation lines are indented to align with the marker's text
    column. Lines are padded out to exactly ``width`` characters.
    """
    text = _whisper_text(w)
    cat = _whisper_category(w)
    mk = marker if marker is not None else _marker_for(cat)
    prefix = f"{mk} "
    indent = CONTINUATION_INDENT
    body_width = max(1, width - len(prefix))
    wrapped_body = _wrap_text(text, body_width)
    lines: List[str] = []
    for i, body in enumerate(wrapped_body):
        if i == 0:
            row = prefix + body
        else:
            row = indent + body[: max(0, width - len(indent))]
        # Pad / truncate to exactly width.
        if len(row) > width:
            row = row[:width]
        else:
            row = row.ljust(width)
        lines.append(row)
    return lines


def render_panel(
    whispers: Iterable[Any],
    *,
    width: int = DEFAULT_PANEL_WIDTH,
    height: int = DEFAULT_PANEL_HEIGHT,
) -> str:
    """Render a fixed-size ASCII whisper panel.

    Parameters
    ----------
    whispers
        An iterable of whisper-like records. Each must expose a ``text``
        attribute or be a mapping with a ``text`` key. ``source_event_type``
        is optional and selects the per-category marker.
    width
        Panel width in characters (default ``30``). Every output line is
        exactly this many characters wide. Must be ``>= 1``.
    height
        Panel height in lines (default ``12``). The output always has
        exactly this many lines, even when fewer whispers are available.

    Returns
    -------
    str
        A multiline string; ``height`` lines joined by ``"\\n"``. The
        function is pure and never mutates ``whispers``.
    """
    if width < 1:
        width = 1
    if height < 1:
        height = 1
    # Snapshot the whispers so callers can pass any iterable without us
    # consuming a generator they still need.
    snap: Sequence[Any] = list(whispers) if not isinstance(whispers, (list, tuple)) else whispers

    # Newest-at-the-bottom: render whispers in given order, then the panel
    # window keeps the LAST ``height`` lines. Older whispers fall out
    # naturally because their lines are dropped from the front.
    all_lines: List[str] = []
    for w in snap:
        all_lines.extend(_render_one_whisper(w, width))
    if len(all_lines) >= height:
        visible = all_lines[len(all_lines) - height:]
    else:
        # Pad the TOP with blank lines so the newest whisper sits at the
        # bottom of the panel.
        pad = [" " * width] * (height - len(all_lines))
        visible = pad + all_lines
    # Defensive: enforce width and length once more.
    out_lines: List[str] = []
    for ln in visible[:height]:
        if len(ln) > width:
            ln = ln[:width]
        elif len(ln) < width:
            ln = ln.ljust(width)
        out_lines.append(ln)
    while len(out_lines) < height:
        out_lines.append(" " * width)
    return "\n".join(out_lines)


__all__ = [
    "render_panel",
    "DEFAULT_PANEL_WIDTH",
    "DEFAULT_PANEL_HEIGHT",
    "CATEGORY_MARKERS",
    "DEFAULT_MARKER",
    "GUTTER",
]
