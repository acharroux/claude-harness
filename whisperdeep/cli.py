"""Command-line entrypoint for Whisperdeep.

Usage:
    python -m whisperdeep --seed 7
    python -m whisperdeep --seed 7 --headless
    python -m whisperdeep --seed 7 --headless --whisperer offline
    python -m whisperdeep --seed 7 --headless --no-whisperer
    python -m whisperdeep --seed 7 --headless --dump-whispers w.json

Sprint 7 plumbing: ``--whisperer`` chooses the adapter (default ``offline``),
``--no-whisperer`` disables the whisperer entirely, and ``--dump-whispers
PATH`` writes the whisper log to disk as JSON. Whispers are NOT rendered in
the dungeon frame in this sprint; the only stdout difference between a
default run and a ``--no-whisperer`` run is a single banner line of the form
``# whisperer: <adapter>`` printed before the frame.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .game import Game
from .render import render_frame
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


def run_headless(args: argparse.Namespace, out=sys.stdout) -> int:
    game = make_game(args)
    # Adapter banner: print only when the Whisperer is active. C15 requires
    # the dungeon glyph rows to be byte-identical to a pre-Whisperer run
    # modulo this single banner line.
    if not args.no_whisperer:
        out.write(f"# whisperer: {args.whisperer}\n")
    out.write(render_frame(game))
    out.write("\n")
    _dump_whispers_if_requested(game, args.dump_whispers)
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
    print(render_frame(game))
    print("[Whisperdeep] hjkl/yubn = move, > descend, < ascend, q quit")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            _dump_whispers_if_requested(game, args.dump_whispers)
            return 0
        if not line:
            continue
        cmd = line[0]
        if cmd == "q":
            _dump_whispers_if_requested(game, args.dump_whispers)
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
        print(render_frame(game))


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.headless:
        return run_headless(args)
    return run_interactive(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
