"""Sprint 12 — Run summary + shareable badge generator.

This module exposes:

* :func:`build_badge` — a single-line ASCII badge string of the form::

      WHISPERDEEP seed=<S> floors=<F> turns=<T> archetype=<A> v1 <CHK>

  where ``<CHK>`` is the first 6 hex chars of the SHA-256 of the
  badge prefix (everything up to and including ``v1``). Two runs
  with identical (seed, floors, turns, archetype) produce identical
  badges; the checksum is reversible by any future tool that knows
  the format.

* :func:`build_run_summary` — a multi-line plain-text summary
  including the name, seed, floors, turns, score, floor-0 archetype,
  the badge string, and an ISO timestamp.

Layering invariants:

* This module imports **only** stdlib + ``typing`` + (optional
  Game/Archetype/Leaderboard types via TYPE_CHECKING).
* It does NOT import :mod:`whisperdeep.llm`, :mod:`whisperdeep.render`,
  :mod:`whisperdeep.panel`, or :mod:`whisperdeep.whisperer`.
"""
from __future__ import annotations

import datetime as _datetime
import hashlib
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:  # pragma: no cover -- type-only
    from .game import Game


__all__ = [
    "BADGE_VERSION",
    "BADGE_HEADER",
    "build_badge",
    "build_run_summary",
]


BADGE_VERSION: str = "v1"
BADGE_HEADER: str = "== Run Summary =="


def _iso_utc_now() -> str:
    now = _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


def _archetype_id(game: "Game") -> str:
    helper = getattr(game, "_archetype_id_for_floor", None)
    if callable(helper):
        try:
            a = helper(0)
            if isinstance(a, str) and a:
                return a
        except Exception:  # noqa: BLE001 -- defensive
            pass
    try:
        floor = game.world.get_floor(0)
        a = getattr(floor, "archetype", None)
        if a is not None:
            ident = getattr(a, "id", None)
            if isinstance(ident, str) and ident:
                return ident
    except Exception:  # noqa: BLE001 -- defensive
        pass
    return "unknown"


def build_badge(game: "Game", *, name: Optional[str] = None) -> str:
    """Return the canonical badge line for ``game``.

    The line format is::

        WHISPERDEEP seed=<S> floors=<F> turns=<T> archetype=<A> v1 <CHK>

    The 6-char ``<CHK>`` is the first 6 hex chars of the SHA-256 of the
    badge prefix (i.e. everything up to and including ``v1``).
    """
    seed = getattr(game, "seed", None)
    if seed is None:
        seed = 0
    floors = int(getattr(game, "max_floor_reached", 0)) + 1
    turns = int(getattr(game, "turns", 0))
    archetype = _archetype_id(game)
    prefix = (
        f"WHISPERDEEP seed={int(seed)} floors={floors} turns={turns} "
        f"archetype={archetype} {BADGE_VERSION}"
    )
    chk = hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:6]
    return f"{prefix} {chk}"


def build_run_summary(
    game: "Game",
    *,
    name: Optional[str] = None,
    fixed_timestamp: Optional[str] = None,
    chronicle_path: Optional[str] = None,
    leaderboard_rank: Optional[int] = None,
) -> str:
    """Return a multi-line plain-text run summary string.

    The summary always begins with :data:`BADGE_HEADER` so callers
    (and grep) can find it deterministically. With ``fixed_timestamp``
    set, two invocations of this function on Games sharing the same
    state produce byte-identical summaries.
    """
    display_name = name if (isinstance(name, str) and name.strip()) else "the unnamed"
    seed = getattr(game, "seed", None)
    if seed is None:
        seed = 0
    floors = int(getattr(game, "max_floor_reached", 0)) + 1
    turns = int(getattr(game, "turns", 0))
    score = floors * 100 + turns
    archetype = _archetype_id(game)
    timestamp = fixed_timestamp if fixed_timestamp else _iso_utc_now()
    badge = build_badge(game, name=display_name)

    lines: List[str] = []
    lines.append(BADGE_HEADER)
    lines.append(f"name      : {display_name}")
    lines.append(f"seed      : {int(seed)}")
    lines.append(f"floors    : {floors}")
    lines.append(f"turns     : {turns}")
    lines.append(f"score     : {score}")
    lines.append(f"archetype : {archetype}")
    lines.append(f"timestamp : {timestamp}")
    if chronicle_path:
        lines.append(f"chronicle : {chronicle_path}")
    if leaderboard_rank is not None:
        lines.append(f"rank      : #{leaderboard_rank}")
    lines.append(f"badge     : {badge}")
    return "\n".join(lines)
