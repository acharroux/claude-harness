"""Command-line entrypoint for Whisperdeep.

Usage:
    python -m whisperdeep --seed 7
    python -m whisperdeep --seed 7 --headless
    python -m whisperdeep --seed 7 --headless --whisperer offline
    python -m whisperdeep --seed 7 --headless --no-whisperer
    python -m whisperdeep --seed 7 --headless --dump-whispers w.json
    python -m whisperdeep --seed 7 --headless --no-panel
    python -m whisperdeep --seed 7 --headless --panel-width 40
    python -m whisperdeep --daily --daily-date 2026-06-12
    python -m whisperdeep --seed-string whispergrove
    python -m whisperdeep --print-leaderboard
    python -m whisperdeep --print-badge
    python -m whisperdeep --print-help-overlay
    python -m whisperdeep --list-bindings

Sprint 7 plumbing: ``--whisperer`` chooses the adapter (default ``offline``),
``--no-whisperer`` disables the whisperer entirely, and ``--dump-whispers
PATH`` writes the whisper log to disk as JSON.

Sprint 8 panel: by default ``--headless`` now prints the dungeon grid
WITH a whisper panel composited to the right of the grid (two-space
gutter). ``--no-panel`` suppresses the panel without disabling the
whisperer (whispers still accumulate in the log and ``--dump-whispers``
keeps working). ``--panel-width N`` sets the panel column width
(default ``30``). ``--no-whisperer`` remains the strongest off-switch:
no bus, no whispers, no panel.

Sprint 12 polish: rebindable keys (``--keys PATH`` / ``--list-bindings``
/ ``--print-help-overlay``), opt-in audio (``--audio CHOICE`` /
``--dump-audio PATH``), local leaderboard (``--leaderboard PATH`` /
``--no-leaderboard`` / ``--print-leaderboard``), shareable seed strings
and daily seed (``--seed-string`` / ``--daily`` / ``--daily-date``),
shareable run badges (``--print-badge`` / ``--no-badge``), and the
end-of-run run summary (``--summary`` / ``--no-summary``).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from typing import List, Optional

from .game import Game
from .panel import DEFAULT_PANEL_WIDTH
from .render import render_frame, render_frame_with_whispers
from .world import World
from .archetypes import (
    ARCHETYPES,
    ARCHETYPE_BY_ID,
    archetype_summary_line,
    get_archetype,
)
from . import audio as audio_module
from . import keybinds as keybinds_module
from . import leaderboard as leaderboard_module
from . import summary as summary_module


WHISPERER_CHOICES = ("offline", "null", "anthropic", "openai")
AUDIO_CHOICES = ("null", "log")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="whisperdeep",
        description=(
            "Whisperdeep — a roguelike with a living dungeon master. "
            "Sprint 12: keybinds, audio, leaderboard, badges, run summary."
        ),
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Master seed for dungeon generation (default: 1).",
    )
    p.add_argument(
        "--width",
        type=int,
        default=80,
        help="Floor width in tiles (default: 80).",
    )
    p.add_argument(
        "--height",
        type=int,
        default=40,
        help="Floor height in tiles (default: 40).",
    )
    p.add_argument(
        "--floors",
        type=int,
        default=3,
        help="Number of dungeon floors (default: 3).",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Print the initial frame and exit (no interactive loop).",
    )
    p.add_argument(
        "--frames",
        type=int,
        default=0,
        help=(
            "Headless: also print N additional frames after applying simple "
            "scripted moves (used for snapshot tests). 0 = initial only."
        ),
    )
    # Sprint 7 flags
    p.add_argument(
        "--whisperer",
        choices=WHISPERER_CHOICES,
        default="offline",
        help=(
            "Whisperer adapter: offline (default, deterministic prose pool), "
            "null (no whispers), anthropic (real provider, requires "
            "ANTHROPIC_API_KEY), or openai (real provider, requires "
            "OPENAI_API_KEY)."
        ),
    )
    p.add_argument(
        "--whisperer-model",
        default="claude-haiku-4-5",
        metavar="MODEL",
        help=(
            "Model name for the anthropic/openai whisperer adapter "
            "(default: claude-haiku-4-5). Examples: claude-haiku-4-5, "
            "claude-sonnet-4-6."
        ),
    )
    p.add_argument(
        "--no-whisperer",
        dest="no_whisperer",
        action="store_true",
        help=(
            "Disable the Whisperer entirely. No EventBus is created and no "
            "whisper banner is printed. Output is byte-identical to the "
            "pre-Whisperer Sprint-2 frame for the same seed."
        ),
    )
    p.add_argument(
        "--whisper-budget",
        type=int,
        default=None,
        help="Override the Whisperer's token budget (default: built-in).",
    )
    p.add_argument(
        "--dump-whispers",
        metavar="PATH",
        default=None,
        help=(
            "Write the produced whispers as a JSON array to PATH. Each "
            "entry includes text, source_event_type, source_turn, "
            "source_floor, adapter_name, and fallback (bool). Useful for "
            "deterministic snapshot tests."
        ),
    )
    # Sprint 8 panel flags
    p.add_argument(
        "--no-panel",
        dest="no_panel",
        action="store_true",
        help=(
            "Suppress the whisper panel in the rendered frame. The "
            "Whisperer still runs and whispers still accumulate in the "
            "log (--dump-whispers continues to work); only the on-screen "
            "panel is hidden. Use --no-whisperer to disable the Whisperer "
            "entirely."
        ),
    )
    p.add_argument(
        "--panel-width",
        type=int,
        default=DEFAULT_PANEL_WIDTH,
        help=(
            f"Width of the whisper panel in columns "
            f"(default: {DEFAULT_PANEL_WIDTH})."
        ),
    )
    # Sprint 10 chronicle flags
    p.add_argument(
        "--name",
        type=str,
        default=None,
        help=(
            "Character name to embed in the run chronicle. When omitted, "
            "a placeholder ('the unnamed') is used."
        ),
    )
    p.add_argument(
        "--chronicle",
        metavar="PATH",
        default=None,
        help=(
            "Write a Markdown chronicle of the run to PATH at end-of-run. "
            "Triggers Game.end_run() so a final epitaph is published. "
            "When omitted, no chronicle is written (default-off)."
        ),
    )
    p.add_argument(
        "--chronicle-fixed-timestamp",
        metavar="ISO",
        default=None,
        help=(
            "Override the chronicle's timestamp with ISO (intended for "
            "deterministic snapshot tests)."
        ),
    )
    p.add_argument(
        "--no-chronicle",
        dest="no_chronicle",
        action="store_true",
        help=(
            "Explicitly disable chronicle writing even if --chronicle is "
            "passed. Mainly useful for tests."
        ),
    )
    # Sprint 11 archetype flags
    p.add_argument(
        "--archetype",
        metavar="ID",
        default=None,
        help=(
            "Force a single archetype across ALL floors of the run "
            "(overrides the seed-derived assignment). Useful for "
            "screenshots and tests. Pass --list-archetypes to see the "
            "registered ids."
        ),
    )
    p.add_argument(
        "--list-archetypes",
        dest="list_archetypes",
        action="store_true",
        help=(
            "Print one line per registered archetype (id, name, glyph "
            "overrides, monster pool size) and exit 0 without starting "
            "a run."
        ),
    )
    # Sprint 12: keybinds
    p.add_argument(
        "--keys",
        metavar="PATH",
        default=None,
        help=(
            "Load a keybindings JSON file at startup. The file's bindings "
            "drive the interactive loop. When omitted, the WHISPERDEEP_KEYS "
            "environment variable is consulted; otherwise default bindings "
            "are used."
        ),
    )
    p.add_argument(
        "--list-bindings",
        dest="list_bindings",
        action="store_true",
        help=(
            "Print the active keybindings (one line per command) and exit 0 "
            "without starting a run."
        ),
    )
    p.add_argument(
        "--print-help-overlay",
        dest="print_help_overlay",
        action="store_true",
        help=(
            "Print the in-game help overlay (commands + bindings) and exit 0 "
            "without starting a run."
        ),
    )
    # Sprint 12: audio
    p.add_argument(
        "--audio",
        choices=AUDIO_CHOICES,
        default="null",
        help=(
            "Audio adapter (OPT-IN, OFF by default). Choices: null (silent, "
            "default), log (records cue names — used by tests). No real "
            "audio backend ships in this sprint."
        ),
    )
    p.add_argument(
        "--dump-audio",
        metavar="PATH",
        default=None,
        help=(
            "Write the recorded audio cues as a JSON list to PATH. Only "
            "produces non-empty output when --audio log is set; the null "
            "adapter records nothing and writes []."
        ),
    )
    # Sprint 12: leaderboard
    p.add_argument(
        "--leaderboard",
        metavar="PATH",
        default=None,
        help=(
            "Path to the local leaderboard JSON file. Defaults to "
            "./leaderboard.json. New entries are appended at end-of-run "
            "when --chronicle is set."
        ),
    )
    p.add_argument(
        "--no-leaderboard",
        dest="no_leaderboard",
        action="store_true",
        help="Disable the leaderboard entirely (no read or write).",
    )
    p.add_argument(
        "--print-leaderboard",
        dest="print_leaderboard",
        action="store_true",
        help=(
            "Print the top-10 entries from the leaderboard at PATH and "
            "exit 0 without starting a run."
        ),
    )
    p.add_argument(
        "--leaderboard-fixed-timestamp",
        metavar="ISO",
        default=None,
        help=(
            "Override the leaderboard entry's timestamp with ISO (intended "
            "for deterministic snapshot tests)."
        ),
    )
    # Sprint 12: daily / seed-string
    p.add_argument(
        "--daily",
        action="store_true",
        help=(
            "Use a date-derived seed (today's UTC date as YYYYMMDD). "
            "Mutually exclusive with --seed and --seed-string."
        ),
    )
    p.add_argument(
        "--daily-date",
        metavar="YYYY-MM-DD",
        default=None,
        help=(
            "Override the date used by --daily (intended for tests). "
            "Format: YYYY-MM-DD."
        ),
    )
    p.add_argument(
        "--seed-string",
        metavar="TEXT",
        default=None,
        help=(
            "Derive the seed from a human-readable string (SHA-256 hash, "
            "first 8 bytes mod 2^31). Mutually exclusive with --seed and "
            "--daily."
        ),
    )
    # Sprint 12: badge / summary
    p.add_argument(
        "--print-badge",
        dest="print_badge",
        action="store_true",
        help=(
            "Print the run badge for the current configuration and exit 0."
        ),
    )
    p.add_argument(
        "--no-badge",
        dest="no_badge",
        action="store_true",
        help=(
            "When --chronicle is set, suppress the sibling .badge.txt "
            "file."
        ),
    )
    p.add_argument(
        "--summary",
        action="store_true",
        help=(
            "Print the end-of-run summary block to stdout. Default-on for "
            "headless runs when --chronicle is set; off otherwise."
        ),
    )
    p.add_argument(
        "--no-summary",
        dest="no_summary",
        action="store_true",
        help="Suppress the end-of-run summary block.",
    )
    return p


# ---------------------------------------------------------------------------
# Seed resolution
# ---------------------------------------------------------------------------


def _resolve_seed(args: argparse.Namespace) -> int:
    """Resolve the master seed from --seed / --daily / --seed-string.

    Returns the int seed. Raises ``SystemExit`` (via the parser's error
    handler is awkward here) — instead the caller catches ``ValueError``
    and prints to stderr.
    """
    chosen = []
    if args.seed is not None:
        chosen.append("--seed")
    if args.daily:
        chosen.append("--daily")
    if args.seed_string is not None:
        chosen.append("--seed-string")
    if len(chosen) > 1:
        raise ValueError(
            f"flags are mutually exclusive: {', '.join(chosen)}"
        )
    if args.daily:
        if args.daily_date:
            try:
                d = _dt.datetime.strptime(args.daily_date, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError(
                    f"invalid --daily-date: {args.daily_date!r} "
                    f"(expected YYYY-MM-DD)"
                )
        else:
            d = _dt.datetime.now(_dt.timezone.utc).date()
        return leaderboard_module.daily_seed_for_date(d)
    if args.seed_string is not None:
        return leaderboard_module.stable_seed_from_string(args.seed_string)
    if args.seed is not None:
        return int(args.seed)
    return 1  # default


# ---------------------------------------------------------------------------
# Game construction & helpers
# ---------------------------------------------------------------------------


def make_game(args: argparse.Namespace, *, seed: Optional[int] = None) -> Game:
    """Build a Game honoring the CLI flags."""
    forced = getattr(args, "archetype", None)
    if seed is None:
        seed = _resolve_seed(args)
    audio_choice = getattr(args, "audio", "null")
    audio_adapter = audio_module.make_adapter(audio_choice)
    if args.no_whisperer:
        game = Game.from_seed(
            seed=seed,
            num_floors=args.floors,
            width=args.width,
            height=args.height,
            whisperer=False,
            forced_archetype=forced,
            audio=audio_adapter,
        )
    else:
        game = Game.from_seed(
            seed=seed,
            num_floors=args.floors,
            width=args.width,
            height=args.height,
            whisperer=True,
            adapter=args.whisperer,
            budget=args.whisper_budget,
            model=args.whisperer_model,
            forced_archetype=forced,
            audio=audio_adapter,
        )
    # Sprint 12: stamp daily/seed_string provenance on the game so the
    # chronicle metadata block can reflect them.
    game._daily = bool(getattr(args, "daily", False))
    ss = getattr(args, "seed_string", None)
    game._seed_string = ss if isinstance(ss, str) and ss else None
    return game


def _dump_whispers_if_requested(game: Game, path: Optional[str]) -> None:
    if not path:
        return
    if game.whisperer is None:
        # Honor --dump-whispers even when the whisperer is off: write [].
        payload = []
    else:
        payload = game.whisperer.dump()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


def _dump_audio_if_requested(game: Game, path: Optional[str]) -> None:
    if not path:
        return
    cues: list = []
    adapter = getattr(game, "audio", None)
    if adapter is not None:
        recorded = getattr(adapter, "cues", None)
        if isinstance(recorded, list):
            cues = list(recorded)
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cues, fh, indent=2)


def _write_chronicle_if_requested(game: Game, args: argparse.Namespace) -> None:
    """Sprint 10: end the run and write a chronicle when --chronicle is set."""
    if getattr(args, "no_chronicle", False):
        return
    chronicle_path = getattr(args, "chronicle", None)
    if not chronicle_path:
        return
    try:
        game.end_run(cause="quit")
    except Exception:  # pragma: no cover -- defensive
        pass
    from .chronicle import write_chronicle as _write
    _write(
        game,
        chronicle_path,
        name=getattr(args, "name", None),
        fixed_timestamp=getattr(args, "chronicle_fixed_timestamp", None),
    )


def _write_badge_if_requested(game: Game, args: argparse.Namespace) -> Optional[str]:
    """Write <chronicle>.badge.txt when --chronicle is set and --no-badge is not.

    Returns the badge string (always built, even when not written).
    """
    badge = summary_module.build_badge(game, name=getattr(args, "name", None))
    if getattr(args, "no_badge", False):
        return badge
    chronicle_path = getattr(args, "chronicle", None)
    if not chronicle_path:
        return badge
    if getattr(args, "no_chronicle", False):
        return badge
    badge_path = chronicle_path + ".badge.txt"
    parent = os.path.dirname(os.path.abspath(badge_path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(badge_path, "w", encoding="utf-8") as fh:
        fh.write(badge + "\n")
    return badge


def _append_leaderboard_if_requested(
    game: Game, args: argparse.Namespace
) -> Optional[int]:
    """Append a leaderboard entry when --chronicle is set and not disabled.

    Returns the rank (1-based) of the new entry in the post-write list, or
    None when no entry was appended.
    """
    if getattr(args, "no_leaderboard", False):
        return None
    if getattr(args, "no_chronicle", False):
        return None
    if not getattr(args, "chronicle", None):
        return None
    path = getattr(args, "leaderboard", None) or leaderboard_module.DEFAULT_PATH
    fixed_ts = (
        getattr(args, "leaderboard_fixed_timestamp", None)
        or getattr(args, "chronicle_fixed_timestamp", None)
    )
    entry = leaderboard_module.build_entry(
        game,
        name=getattr(args, "name", None),
        timestamp=fixed_ts,
    )
    try:
        entries = leaderboard_module.append_entry(path, entry)
    except OSError as exc:
        sys.stderr.write(
            f"warning: could not write leaderboard {path!r}: {exc}\n"
        )
        return None
    # Find rank: identify our entry by (seed, name, score, timestamp).
    for idx, e in enumerate(entries, start=1):
        if (
            e.get("seed") == entry["seed"]
            and e.get("name") == entry["name"]
            and e.get("score") == entry["score"]
            and e.get("timestamp") == entry["timestamp"]
        ):
            return idx
    return None


def _print_summary_if_requested(
    game: Game,
    args: argparse.Namespace,
    *,
    rank: Optional[int] = None,
    out=sys.stdout,
) -> None:
    """Print the end-of-run summary block when configured to."""
    if getattr(args, "no_summary", False):
        return
    summary_default_on = bool(getattr(args, "chronicle", None))
    if not (getattr(args, "summary", False) or summary_default_on):
        return
    fixed_ts = (
        getattr(args, "leaderboard_fixed_timestamp", None)
        or getattr(args, "chronicle_fixed_timestamp", None)
    )
    text = summary_module.build_run_summary(
        game,
        name=getattr(args, "name", None),
        fixed_timestamp=fixed_ts,
        chronicle_path=getattr(args, "chronicle", None),
        leaderboard_rank=rank,
    )
    out.write(text)
    out.write("\n")


# ---------------------------------------------------------------------------
# Headless / interactive entrypoints
# ---------------------------------------------------------------------------


def run_headless(args: argparse.Namespace, out=sys.stdout) -> int:
    seed = _resolve_seed(args)
    game = make_game(args, seed=seed)
    # Adapter banner: print only when the Whisperer is active.
    if not args.no_whisperer:
        out.write(f"# whisperer: {args.whisperer}\n")
    if args.no_whisperer or args.no_panel:
        out.write(render_frame(game))
    else:
        out.write(
            render_frame_with_whispers(game, panel_width=args.panel_width)
        )
    out.write("\n")
    _dump_whispers_if_requested(game, args.dump_whispers)
    _write_chronicle_if_requested(game, args)
    _write_badge_if_requested(game, args)
    rank = _append_leaderboard_if_requested(game, args)
    _dump_audio_if_requested(game, args.dump_audio)
    _print_summary_if_requested(game, args, rank=rank, out=out)
    return 0


# ---------------------------------------------------------------------------
# Interactive loop dispatcher
# ---------------------------------------------------------------------------


def dispatch_command(
    game: Game,
    kb: keybinds_module.KeyBindings,
    line: str,
) -> str:
    """Map a single input line to a command effect; mutate ``game`` accordingly.

    Returns a status string describing what happened (for tests + the
    interactive loop). Lines starting with ``:`` are command-name
    invocations; otherwise the first key of the line is looked up in
    ``kb``.

    Supported `:`-commands include all canonical command names plus
    ``:bindings`` (an alias for ``:help``), ``:bind``, ``:unbind``,
    ``:summary``.

    Returns one of:
    * ``"moved"`` / ``"blocked"`` (movement)
    * ``"descended"`` / ``"ascended"`` / ``"no-stairs"``
    * ``"waited"``
    * ``"quit"``
    * ``"help"`` (caller should print format_help_overlay(kb))
    * ``"redraw"``
    * ``"summary"``
    * ``"unknown: <text>"``
    """
    if not line:
        return "noop"
    if line.startswith(":"):
        parts = line[1:].split()
        if not parts:
            return "noop"
        cmd = parts[0]
        rest = parts[1:]
        if cmd in ("bind",):
            if len(rest) < 2:
                return "unknown: :bind requires <command> <key>"
            command, key = rest[0], rest[1]
            try:
                kb.bind(command, key)
            except ValueError as exc:
                return f"unknown: {exc}"
            return "rebound"
        if cmd in ("unbind",):
            if len(rest) < 1:
                return "unknown: :unbind requires <key>"
            kb.unbind(rest[0])
            return "unbound"
        if cmd in ("bindings", "keys"):
            return "help"
        # otherwise treat the rest as a canonical command name
        if cmd in keybinds_module.COMMANDS or cmd in (
            "bindings",
            "summary",
        ):
            return _apply_command(game, cmd)
        return f"unknown: {cmd}"
    # Single-key path: read the first key (or whole input line as key).
    key = line
    cmd = kb.command_for(key)
    if cmd is None:
        # Fall back to single-character lookup.
        cmd = kb.command_for(key[0])
    if cmd is None:
        return f"unknown: {key!r}"
    return _apply_command(game, cmd)


_MOVES = {
    "move_west": (-1, 0),
    "move_east": (1, 0),
    "move_north": (0, -1),
    "move_south": (0, 1),
    "move_nw": (-1, -1),
    "move_ne": (1, -1),
    "move_sw": (-1, 1),
    "move_se": (1, 1),
}


def _apply_command(game: Game, cmd: str) -> str:
    if cmd in _MOVES:
        dx, dy = _MOVES[cmd]
        moved = game.try_move(dx, dy)
        return "moved" if moved else "blocked"
    if cmd == "wait":
        game.turns += 1
        return "waited"
    if cmd == "descend":
        ok = game.descend()
        return "descended" if ok else "no-stairs"
    if cmd == "ascend":
        ok = game.ascend()
        return "ascended" if ok else "no-stairs"
    if cmd == "quit":
        return "quit"
    if cmd in ("help", "bindings"):
        return "help"
    if cmd == "redraw":
        return "redraw"
    if cmd == "summary":
        return "summary"
    return f"unknown: {cmd}"


def run_interactive(  # pragma: no cover -- reads stdin
    args: argparse.Namespace,
    kb: Optional[keybinds_module.KeyBindings] = None,
) -> int:
    """Interactive loop using stdin one-line commands."""
    seed = _resolve_seed(args)
    game = make_game(args, seed=seed)
    if kb is None:
        kb = keybinds_module.load_keybindings(getattr(args, "keys", None))
    if not args.no_whisperer:
        print(f"# whisperer: {args.whisperer}")
    if args.no_whisperer or args.no_panel:
        print(render_frame(game))
    else:
        print(render_frame_with_whispers(game, panel_width=args.panel_width))
    print("[Whisperdeep] type ? for help, q to quit, : for commands")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        result = dispatch_command(game, kb, line)
        if result == "quit":
            break
        if result == "help":
            print(keybinds_module.format_help_overlay(kb))
            continue
        if result == "summary":
            text = summary_module.build_run_summary(
                game,
                name=getattr(args, "name", None),
            )
            print(text)
            continue
        if result.startswith("unknown:"):
            print(result)
            continue
        if args.no_whisperer or args.no_panel:
            print(render_frame(game))
        else:
            print(render_frame_with_whispers(game, panel_width=args.panel_width))
    _dump_whispers_if_requested(game, args.dump_whispers)
    _write_chronicle_if_requested(game, args)
    _write_badge_if_requested(game, args)
    rank = _append_leaderboard_if_requested(game, args)
    _dump_audio_if_requested(game, args.dump_audio)
    # Force-on summary at end of interactive run.
    if not getattr(args, "no_summary", False):
        text = summary_module.build_run_summary(
            game,
            name=getattr(args, "name", None),
            fixed_timestamp=getattr(args, "chronicle_fixed_timestamp", None),
            chronicle_path=getattr(args, "chronicle", None),
            leaderboard_rank=rank,
        )
        print(text)
    return 0


# ---------------------------------------------------------------------------
# One-shot info commands
# ---------------------------------------------------------------------------


def _print_archetypes(out=sys.stdout) -> int:
    for arche in ARCHETYPES:
        out.write(archetype_summary_line(arche))
        out.write("\n")
    return 0


def _print_bindings(args: argparse.Namespace, out=sys.stdout) -> int:
    """Print one line per command + active bindings, exit 0."""
    try:
        kb = keybinds_module.load_keybindings(getattr(args, "keys", None))
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    for cmd in keybinds_module.COMMANDS:
        keys = kb.keys_for(cmd)
        if keys:
            shown = ", ".join(keybinds_module._display_key(k) for k in keys)
        else:
            shown = "(unbound)"
        out.write(f"{cmd}: {shown}\n")
    return 0


def _print_help_overlay(args: argparse.Namespace, out=sys.stdout) -> int:
    try:
        kb = keybinds_module.load_keybindings(getattr(args, "keys", None))
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    out.write(keybinds_module.format_help_overlay(kb))
    out.write("\n")
    return 0


def _print_leaderboard(args: argparse.Namespace, out=sys.stdout) -> int:
    path = getattr(args, "leaderboard", None) or leaderboard_module.DEFAULT_PATH
    entries = leaderboard_module.read_leaderboard(path)
    if not entries:
        out.write("(no leaderboard entries yet)\n")
        return 0
    out.write(leaderboard_module.format_top_n(entries, n=10))
    out.write("\n")
    return 0


def _print_badge(args: argparse.Namespace, out=sys.stdout) -> int:
    try:
        seed = _resolve_seed(args)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    game = make_game(args, seed=seed)
    badge = summary_module.build_badge(game, name=getattr(args, "name", None))
    out.write(badge)
    out.write("\n")
    return 0


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    # Sprint 11: --list-archetypes is a one-shot info command.
    if getattr(args, "list_archetypes", False):
        return _print_archetypes()
    # Sprint 12: keybinds info commands.
    if getattr(args, "list_bindings", False):
        return _print_bindings(args)
    if getattr(args, "print_help_overlay", False):
        return _print_help_overlay(args)
    # Sprint 12: leaderboard info command.
    if getattr(args, "print_leaderboard", False):
        return _print_leaderboard(args)
    # Validate --archetype up front so a bad id fails before any work.
    forced = getattr(args, "archetype", None)
    if forced is not None and forced not in ARCHETYPE_BY_ID:
        valid = ", ".join(sorted(ARCHETYPE_BY_ID))
        sys.stderr.write(
            f"error: unknown archetype id: {forced!r}. "
            f"Valid ids: {valid}. "
            f"Run with --list-archetypes for a summary.\n"
        )
        return 2
    # Validate --keys early so a bad keys file fails fast.
    if getattr(args, "keys", None) is not None:
        try:
            keybinds_module.load_keybindings(args.keys)
        except ValueError as exc:
            sys.stderr.write(f"error: {exc}\n")
            return 2
    # Validate seed flags.
    try:
        _resolve_seed(args)
    except ValueError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    # Sprint 12: --print-badge is a one-shot info command (after seed validation).
    if getattr(args, "print_badge", False):
        return _print_badge(args)
    if args.headless:
        return run_headless(args)
    return run_interactive(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
