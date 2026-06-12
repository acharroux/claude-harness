"""Sprint 10 — Chronicle Generator.

Builds an end-of-run Markdown chronicle for a Whisperdeep run. The
chronicle is a self-contained piece of dark-fantasy prose that
summarises the run as: a title, a metadata block, a bulleted list of
notable events, and a final whispered epitaph.

Design choices documented in this module's tests and the project docs:

* **Format**: plain Markdown, no HTML, no terminal rendering.
* **Sections**, in order:
      1. ``# <Name> — A Whisperdeep Chronicle``  (H1)
      2. ``## Metadata``                          (key:value bullet list)
      3. ``## Notable Events``                    (chronological bullets)
      4. ``## Epitaph``                           (one Markdown blockquote)
* **Metadata keys** (all present, machine-readable as ``- key: value``
  bullet lines): ``seed``, ``name``, ``floors_reached``, ``turns``,
  ``adapter``, ``timestamp``.
* **Timestamp policy**: ISO-8601 UTC with a trailing ``Z`` suffix,
  computed at chronicle build time. Tests inject a fixed timestamp via
  the ``fixed_timestamp`` keyword so chronicle output is byte-stable.
* **Notable Events**: every whisper recorded by the Game's Whisperer is
  rendered as a single bullet. The bullet text format is:
  ``- [<source_event_type>@t<turn>:f<floor>] <text>``. This guarantees a
  stable, machine-checkable format regardless of which whispers fired.
* **Epitaph**: one Markdown blockquote (``> ``) line. Rendered text
  equals the most-recent ``epitaph`` source-event-type whisper. When
  no epitaph whisper exists (e.g. ``end_run`` was never called), a
  placeholder line is used.

Layering: this module imports stdlib + ``typing`` + the ``Game`` /
``Whisper`` types. It does **not** import ``whisperdeep.llm``,
``whisperdeep.render``, or ``whisperdeep.panel``. It does not modify
``whisperdeep.events``; the new ``epitaph`` event type is declared in
``whisperdeep/events.py`` (additive change).

Cross-run "death legends" (the Whisperer reading prior chronicles in a
future run) are **out of scope** for Sprint 10 and explicitly deferred.
"""
from __future__ import annotations

import datetime as _datetime
import os as _os
import re as _re
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:  # pragma: no cover -- type-only imports
    from .game import Game
    from .whisperer import Whisper


__all__ = [
    "build_chronicle",
    "write_chronicle",
    "default_chronicle_path",
    "slugify_name",
    "DEFAULT_NAME",
    "CHRONICLE_DIR",
]


DEFAULT_NAME: str = "the unnamed"
CHRONICLE_DIR: str = "chronicles"
PLACEHOLDER_EPITAPH: str = "The chronicle is closed without ceremony."


# ---------------------------------------------------------------------------
# Filename helpers
# ---------------------------------------------------------------------------


_SLUG_INVALID_RE = _re.compile(r"[^a-z0-9]+")


def slugify_name(name: str) -> str:
    """Return a filesystem-safe lowercase slug for ``name``.

    Empty / whitespace-only names degrade to ``"unnamed"``.
    """
    if not isinstance(name, str):
        name = str(name)
    lowered = name.strip().lower()
    if not lowered:
        return "unnamed"
    slug = _SLUG_INVALID_RE.sub("-", lowered).strip("-")
    return slug or "unnamed"


def default_chronicle_path(game: "Game", name: Optional[str] = None,
                           *, root: Optional[str] = None) -> str:
    """Compute the default chronicle path for ``game``.

    The path lives under ``<root>/chronicles/`` (default ``root`` is the
    current working directory). The filename embeds the seed, the
    slugified character name, and the deepest floor reached, so two
    chronicles for distinct seeds or names land in distinct files.
    """
    seed = getattr(game, "seed", None)
    if seed is None:
        seed = "unknown"
    slug = slugify_name(name if name is not None else DEFAULT_NAME)
    floor = getattr(game, "max_floor_reached", 0) + 1
    fname = f"seed-{seed}-{slug}-floor-{floor}.md"
    base = Path(root) if root is not None else Path.cwd()
    return str(base / CHRONICLE_DIR / fname)


# ---------------------------------------------------------------------------
# Build / write
# ---------------------------------------------------------------------------


def _iso_utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with a trailing 'Z' suffix."""
    now = _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0)
    # ``isoformat`` on an aware UTC datetime emits '+00:00'; we prefer
    # the canonical 'Z' suffix.
    return now.isoformat().replace("+00:00", "Z")


def _coerce_whispers(game: "Game") -> list:
    """Return the Whisperer's whispers list, or ``[]`` when absent."""
    wh = getattr(game, "whisperer", None)
    if wh is None:
        return []
    items = getattr(wh, "whispers", None)
    if items is None:
        return []
    return list(items)


def _whisper_text(w: object) -> str:
    text = getattr(w, "text", None)
    if text is None and isinstance(w, dict):
        text = w.get("text")
    return text if isinstance(text, str) else ""


def _whisper_event_type(w: object) -> str:
    et = getattr(w, "source_event_type", None)
    if et is None and isinstance(w, dict):
        et = w.get("source_event_type")
    return et if isinstance(et, str) else ""


def _whisper_turn(w: object) -> int:
    t = getattr(w, "source_turn", None)
    if t is None and isinstance(w, dict):
        t = w.get("source_turn")
    try:
        return int(t)
    except (TypeError, ValueError):
        return 0


def _whisper_floor(w: object) -> str:
    f = getattr(w, "source_floor", None)
    if f is None and isinstance(w, dict):
        f = w.get("source_floor")
    if f is None:
        return "-"
    try:
        return str(int(f))
    except (TypeError, ValueError):
        return str(f)


def _adapter_name(game: "Game") -> str:
    # Prefer the explicit name stashed by Game.from_seed. Fall back to
    # introspecting the whisperer's adapter.
    name = getattr(game, "_adapter_name", None)
    if isinstance(name, str) and name:
        return name
    wh = getattr(game, "whisperer", None)
    adapter = getattr(wh, "adapter", None)
    return getattr(adapter, "name", "none") if adapter is not None else "none"


def build_chronicle(
    game: "Game",
    *,
    name: Optional[str] = None,
    fixed_timestamp: Optional[str] = None,
) -> str:
    """Return the run's Markdown chronicle as a string.

    Parameters
    ----------
    game
        The :class:`Game` whose state and whisper log are summarised.
    name
        Character name to embed in the title and metadata block. When
        omitted, the placeholder ``DEFAULT_NAME`` is used.
    fixed_timestamp
        When provided, used verbatim as the ``timestamp`` metadata value
        (intended for deterministic tests). When omitted, the current
        UTC time is rendered as ISO-8601 with a 'Z' suffix.
    """
    display_name = name if (isinstance(name, str) and name.strip()) else DEFAULT_NAME
    timestamp = fixed_timestamp if fixed_timestamp else _iso_utc_now()

    seed = getattr(game, "seed", None)
    if seed is None:
        seed = "unknown"
    floors_reached = getattr(game, "max_floor_reached", 0) + 1
    turns = getattr(game, "turns", 0)
    adapter = _adapter_name(game)

    whispers = _coerce_whispers(game)

    lines: list = []

    # Section 1: H1 title.
    lines.append(f"# {display_name} — A Whisperdeep Chronicle")
    lines.append("")

    # Section 2: Metadata block (machine-readable bullet list).
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- seed: {seed}")
    lines.append(f"- name: {display_name}")
    lines.append(f"- floors_reached: {floors_reached}")
    lines.append(f"- turns: {turns}")
    lines.append(f"- adapter: {adapter}")
    lines.append(f"- timestamp: {timestamp}")
    # Sprint 12 (additive): record daily/seed_string provenance when set.
    daily = getattr(game, "_daily", None)
    if daily:
        lines.append("- daily: true")
    seed_string = getattr(game, "_seed_string", None)
    if isinstance(seed_string, str) and seed_string:
        lines.append(f"- seed_string: {seed_string}")
    lines.append("")

    # Section 3: Notable Events.
    lines.append("## Notable Events")
    lines.append("")
    if not whispers:
        lines.append("- (no whispers were recorded during this run)")
        lines.append("")
    else:
        for w in whispers:
            text = _whisper_text(w)
            et = _whisper_event_type(w) or "whisper"
            t = _whisper_turn(w)
            f = _whisper_floor(w)
            lines.append(f"- [{et}@t{t}:f{f}] {text}")
        lines.append("")

    # Section 4: Epitaph.
    lines.append("## Epitaph")
    lines.append("")
    epitaph_text = _select_epitaph(whispers)
    lines.append(f"> {epitaph_text}")
    lines.append("")

    return "\n".join(lines)


def _select_epitaph(whispers: Iterable[object]) -> str:
    """Return the most-recent epitaph whisper's text, or the placeholder."""
    last: Optional[str] = None
    for w in whispers:
        if _whisper_event_type(w) == "epitaph":
            t = _whisper_text(w)
            if t:
                last = t
    if last:
        return last
    return PLACEHOLDER_EPITAPH


def write_chronicle(
    game: "Game",
    path: str,
    *,
    name: Optional[str] = None,
    fixed_timestamp: Optional[str] = None,
) -> str:
    """Write the chronicle for ``game`` to ``path`` and return the path.

    The parent directory is created if it does not exist. The file is
    written as UTF-8 to support unicode names.
    """
    text = build_chronicle(game, name=name, fixed_timestamp=fixed_timestamp)
    p = Path(path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        fh.write(text)
    return str(p)
