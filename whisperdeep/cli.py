"""Command-line entrypoint for Whisperdeep.

Usage:
    python -m whisperdeep --seed 7
    python -m whisperdeep --seed 7 --headless         # print initial frame and exit
    python -m whisperdeep --seed 7 --width 80 --height 40 --floors 3

For Sprint 2 we ship a minimal interactive loop and a robust headless mode
so the contract's snapshot / determinism criteria can be verified without a
TTY. Future sprints will replace the interactive loop with a proper terminal
UI (tcod or similar).
"""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .game import Game
from .render import render_frame
from .world import World


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="whisperdeep",
        description=(
            "Whisperdeep — a roguelike with a living dungeon master. "
            "Sprint 2: rooms-and-corridors dungeon generation, doors, stairs, "
            "and multi-floor descent."
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
    return p


def make_game(seed: int, width: int, height: int, floors: int) -> Game:
    world = World(master_seed=seed, num_floors=floors, width=width, height=height)
    return Game(world)


def run_headless(args: argparse.Namespace, out=sys.stdout) -> int:
    game = make_game(args.seed, args.width, args.height, args.floors)
    out.write(render_frame(game))
    out.write("\n")
    return 0


def run_interactive(args: argparse.Namespace) -> int:  # pragma: no cover
    """Minimal interactive loop using stdin one-character commands.

    This is deliberately tiny — a full TUI lands in a later sprint. It is
    sufficient for C21 (basic regression: launch + move).

    Commands:
        h/j/k/l   move west/south/north/east
        y/u/b/n   diagonals
        .         wait
        >         descend (when on '>')
        <         ascend (when on '<')
        q         quit
    """
    game = make_game(args.seed, args.width, args.height, args.floors)
    moves = {
        "h": (-1, 0), "l": (1, 0), "j": (0, 1), "k": (0, -1),
        "y": (-1, -1), "u": (1, -1), "b": (-1, 1), "n": (1, 1),
        ".": (0, 0),
    }
    print(render_frame(game))
    print("[Whisperdeep] hjkl/yubn = move, > descend, < ascend, q quit")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        cmd = line[0]
        if cmd == "q":
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
