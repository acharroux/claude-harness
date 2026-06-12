"""Command-line entrypoint for Whisperdeep.

Usage:
    python -m whisperdeep --seed 7
    python -m whisperdeep --seed 7 --headless
    python -m whisperdeep --seed 7 --headless --whisperer offline
    python -m whisperdeep --seed 7 --headless --no-whisperer
    python -m whisperdeep --seed 7 --headless --dump-whispers w.json
    python -m whisperdeep --seed 7 --headless --no-panel
    python -m whisperdeep --seed 7 --headless --panel-width 40

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
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .game import Game
from .panel import DEFAULT_PANEL_WIDTH
from .render import render_frame, render_frame_with_whispers
from .world import World


WHISPERER_CHOICES = ("offline", "null", "anthropic", "openai")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="whisperdeep",
        description=(
            "Whisperdeep — a roguelike with a living dungeon master. "
            "Sprint 7: Whisperer adapter + event bus plumbing. "
            "Whispers are not yet rendered in the frame (Sprint 8)."
        ),
    )
    p.add_argument(
        "--seed",
        type=int,
        default=1,
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
    return p


def make_game(args: argparse.Namespace) -> Game:
    """Build a Game honoring the CLI flags."""
    if args.no_whisperer:
        return Game.from_seed(
            seed=args.seed,
            num_floors=args.floors,
            width=args.width,
            height=args.height,
            whisperer=False,
        )
    return Game.from_seed(
        seed=args.seed,
        num_floors=args.floors,
        width=args.width,
        height=args.height,
        whisperer=True,
        adapter=args.whisperer,
        budget=args.whisper_budget,
        model=args.whisperer_model,
    )


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


def _write_chronicle_if_requested(game: Game, args: argparse.Namespace) -> None:
    """Sprint 10: end the run and write a chronicle when --chronicle is set.

    Calling this helper is a no-op when ``--chronicle`` is unset or
    ``--no-chronicle`` is set.
    """
    if getattr(args, "no_chronicle", False):
        return
    chronicle_path = getattr(args, "chronicle", None)
    if not chronicle_path:
        return
    # Ensure run lifecycle events (run_ended + epitaph) fire before we
    # snapshot the whisper log into the chronicle.
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


def run_headless(args: argparse.Namespace, out=sys.stdout) -> int:
    game = make_game(args)
    # Adapter banner: print only when the Whisperer is active.
    if not args.no_whisperer:
        out.write(f"# whisperer: {args.whisperer}\n")
    # Sprint 8: default headless renders the composite frame (grid + panel)
    # so players can read the Whisperer. ``--no-panel`` and
    # ``--no-whisperer`` both fall back to the original Sprint-2 grid.
    if args.no_whisperer or args.no_panel:
        out.write(render_frame(game))
    else:
        out.write(
            render_frame_with_whispers(game, panel_width=args.panel_width)
        )
    out.write("\n")
    _dump_whispers_if_requested(game, args.dump_whispers)
    _write_chronicle_if_requested(game, args)
    return 0


def run_interactive(args: argparse.Namespace) -> int:  # pragma: no cover
    """Minimal interactive loop using stdin one-character commands."""
    game = make_game(args)
    moves = {
        "h": (-1, 0), "l": (1, 0), "j": (0, 1), "k": (0, -1),
        "y": (-1, -1), "u": (1, -1), "b": (-1, 1), "n": (1, 1),
        ".": (0, 0),
    }
    if not args.no_whisperer:
        print(f"# whisperer: {args.whisperer}")
    if args.no_whisperer or args.no_panel:
        print(render_frame(game))
    else:
        print(render_frame_with_whispers(game, panel_width=args.panel_width))
    print("[Whisperdeep] hjkl/yubn = move, > descend, < ascend, q quit")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            _dump_whispers_if_requested(game, args.dump_whispers)
            _write_chronicle_if_requested(game, args)
            return 0
        if not line:
            continue
        cmd = line[0]
        if cmd == "q":
            _dump_whispers_if_requested(game, args.dump_whispers)
            _write_chronicle_if_requested(game, args)
            return 0
        elif cmd in moves:
            dx, dy = moves[cmd]
            game.try_move(dx, dy)
        elif cmd == ">":
            game.descend()
        elif cmd == "<":
            game.ascend()
        else:
            print(f"unknown command: {cmd!r}")
            continue
        if args.no_whisperer or args.no_panel:
            print(render_frame(game))
        else:
            print(render_frame_with_whispers(game, panel_width=args.panel_width))


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.headless:
        return run_headless(args)
    return run_interactive(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
