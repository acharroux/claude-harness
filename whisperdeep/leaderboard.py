"""Sprint 12 — Local leaderboard, daily seed, and shareable seed strings.

This module ships:

* :func:`stable_seed_from_string` — a documented, stable, cross-process
  hash of a UTF-8 string to a 31-bit unsigned int. It uses SHA-256 and
  is **not** Python's built-in :func:`hash` (which is salted per
  process).
* :func:`daily_seed_for_date` — the daily seed derived from a UTC
  date. Equal to ``int(YYYYMMDD)``.
* :func:`score_for` — the canonical run score
  (``floors_reached * 100 + turns``).
* :func:`build_entry` — produce a leaderboard entry dict.
* :func:`read_leaderboard` / :func:`append_entry` — persist a JSON
  list of entries (sorted by score DESC then timestamp ASC, capped at
  :data:`MAX_ENTRIES`).

Layering invariants:

* This module imports **only** stdlib + ``typing`` + (optional
  Game/Archetype types via TYPE_CHECKING).
* It does NOT import :mod:`whisperdeep.llm`, :mod:`whisperdeep.render`,
  :mod:`whisperdeep.panel`, :mod:`whisperdeep.whisperer`,
  or :mod:`whisperdeep.audio`.
"""
from __future__ import annotations

import datetime as _datetime
import hashlib
import json
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover -- type-only
    from .game import Game


__all__ = [
    "MAX_ENTRIES",
    "DEFAULT_PATH",
    "score_for",
    "read_leaderboard",
    "append_entry",
    "build_entry",
    "stable_seed_from_string",
    "daily_seed_for_date",
    "format_top_n",
]


#: Maximum number of entries kept in a leaderboard file. Excess is
#: dropped on append (lowest scores discarded first).
MAX_ENTRIES: int = 50

#: Default leaderboard path used by the CLI when ``--leaderboard`` is
#: omitted. Resolved relative to the current working directory at
#: write time.
DEFAULT_PATH: str = "leaderboard.json"


# ---------------------------------------------------------------------------
# Seed derivations
# ---------------------------------------------------------------------------


def stable_seed_from_string(s: str) -> int:
    """Deterministically hash ``s`` to a 31-bit unsigned int.

    Algorithm: take SHA-256 of the UTF-8 bytes, take the first 8 bytes
    as a big-endian unsigned int, then mod 2**31. This is stable across
    Python versions and platforms (unlike ``hash(s)`` which is salted
    per process).

    Empty strings raise :class:`ValueError`.
    """
    if not isinstance(s, str):
        raise ValueError("seed string must be a str")
    if s == "":
        raise ValueError("seed string must be non-empty")
    digest = hashlib.sha256(s.encode("utf-8")).digest()
    n = int.from_bytes(digest[:8], "big", signed=False)
    return n % (2 ** 31)


def daily_seed_for_date(date: Optional[_datetime.date] = None) -> int:
    """Return the daily seed for ``date`` (defaults to today's UTC date).

    The seed is ``int(YYYYMMDD)``; e.g. 2026-06-12 -> 20260612.
    """
    if date is None:
        date = _datetime.datetime.now(_datetime.timezone.utc).date()
    return int(date.strftime("%Y%m%d"))


# ---------------------------------------------------------------------------
# Score & entry helpers
# ---------------------------------------------------------------------------


def score_for(game: "Game") -> int:
    """Return ``floors_reached * 100 + turns`` for ``game``.

    Defensively reads ``getattr`` so passing a duck-typed test stub
    works.
    """
    floors = int(getattr(game, "max_floor_reached", 0)) + 1
    turns = int(getattr(game, "turns", 0))
    return floors * 100 + turns


def _archetype_id(game: "Game") -> str:
    helper = getattr(game, "_archetype_id_for_floor", None)
    if callable(helper):
        try:
            a = helper(0)
            if isinstance(a, str) and a:
                return a
        except Exception:  # noqa: BLE001 -- defensive
            pass
    # Fallback: poke the world directly.
    try:
        world = game.world
        floor = world.get_floor(0)
        a = getattr(floor, "archetype", None)
        if a is not None:
            ident = getattr(a, "id", None)
            if isinstance(ident, str) and ident:
                return ident
    except Exception:  # noqa: BLE001 -- defensive
        pass
    return "unknown"


def build_entry(
    game: "Game",
    *,
    name: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a leaderboard entry dict for ``game``.

    Required keys: ``seed``, ``name``, ``floors_reached``, ``turns``,
    ``score``, ``archetype``, ``timestamp``.
    """
    seed = getattr(game, "seed", None)
    if seed is None:
        seed = 0
    floors_reached = int(getattr(game, "max_floor_reached", 0)) + 1
    turns = int(getattr(game, "turns", 0))
    if timestamp is None:
        timestamp = _iso_utc_now()
    display_name = name if (isinstance(name, str) and name.strip()) else "the unnamed"
    return {
        "seed": int(seed),
        "name": display_name,
        "floors_reached": floors_reached,
        "turns": turns,
        "score": floors_reached * 100 + turns,
        "archetype": _archetype_id(game),
        "timestamp": timestamp,
    }


def _iso_utc_now() -> str:
    now = _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def read_leaderboard(path: str) -> List[Dict[str, Any]]:
    """Return the parsed entries at ``path``.

    Returns ``[]`` when the file does not exist, the JSON is malformed,
    or the parsed value is not a list. This is intentional graceful
    degradation; a corrupt local file should never crash the game.
    """
    if not isinstance(path, str) or not path:
        return []
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for entry in data:
        if isinstance(entry, dict):
            out.append(entry)
    return out


def _sort_key(entry: Dict[str, Any]):
    score = entry.get("score", 0)
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 0
    timestamp = entry.get("timestamp", "")
    if not isinstance(timestamp, str):
        timestamp = ""
    return (-score, timestamp)


def _atomic_write_json(path: str, payload: Any) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def append_entry(path: str, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Read, append, sort (score DESC then timestamp ASC), cap, write back.

    Returns the new list of entries actually written to disk.
    """
    if not isinstance(entry, dict):
        raise TypeError("entry must be a dict")
    entries = read_leaderboard(path)
    entries.append(dict(entry))
    entries.sort(key=_sort_key)
    if len(entries) > MAX_ENTRIES:
        entries = entries[:MAX_ENTRIES]
    _atomic_write_json(path, entries)
    return entries


# ---------------------------------------------------------------------------
# Pretty-printing
# ---------------------------------------------------------------------------


def format_top_n(
    entries: List[Dict[str, Any]],
    n: int = 10,
) -> str:
    """Return a multi-line plain-text summary of the top ``n`` entries."""
    if not entries:
        return "(no leaderboard entries yet)"
    lines: List[str] = []
    lines.append(
        f"{'Rank':<5} {'Name':<16} {'Seed':>10} {'Floors':>7} {'Turns':>7} "
        f"{'Score':>7} {'Archetype':<14} Timestamp"
    )
    lines.append("-" * 90)
    top = entries[:n]
    for idx, entry in enumerate(top, start=1):
        name = str(entry.get("name", ""))[:16]
        seed = entry.get("seed", "")
        floors = entry.get("floors_reached", 0)
        turns = entry.get("turns", 0)
        score = entry.get("score", 0)
        archetype = str(entry.get("archetype", ""))[:14]
        timestamp = str(entry.get("timestamp", ""))
        lines.append(
            f"{idx:<5} {name:<16} {seed!s:>10} {floors!s:>7} {turns!s:>7} "
            f"{score!s:>7} {archetype:<14} {timestamp}"
        )
    return "\n".join(lines)
