"""Tests mapped to Sprint 1's contract (Foundation & Grid World).

Each test is annotated with the contract criterion it covers. Sprint 2's
bootstrap delivered the Sprint 1 scaffold; this file is an explicit, criterion-
by-criterion verification that the Sprint 1 contract is honored.

Contract: harness-state/sprints/sprint-01/contract.json
"""
from __future__ import annotations

import importlib
import io
import subprocess
import sys
from contextlib import redirect_stdout, redirect_stderr

import pytest

from whisperdeep import tiles as tiles_module
from whisperdeep.cli import build_parser, run_headless
from whisperdeep.entity import Entity, Player
from whisperdeep.floor import Floor
from whisperdeep.game import Game
from whisperdeep.render import render_floor, render_frame
from whisperdeep.tiles import Tile, TileKind
from whisperdeep.world import World


# ---------- C1: package importable ------------------------------------------

def test_c1_package_importable():
    mod = importlib.import_module("whisperdeep")
    assert mod is not None
    assert hasattr(mod, "__version__")


# ---------- C2: __main__ runnable -------------------------------------------

def test_c2_main_module_help_exits_zero():
    proc = subprocess.run(
        [sys.executable, "-m", "whisperdeep", "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "whisperdeep" in proc.stdout.lower()


# ---------- C3: distinct modules --------------------------------------------

def test_c3_modules_all_exist_and_import():
    for name in ("tiles", "floor", "entity", "game", "render"):
        mod = importlib.import_module(f"whisperdeep.{name}")
        assert mod is not None, f"module {name} failed to import"


# ---------- C4: tile abstraction --------------------------------------------

def test_c4_wall_tile_glyph_and_walkable():
    w = tiles_module.wall()
    assert w.glyph == "#"
    assert w.walkable is False


def test_c4_floor_tile_glyph_and_walkable():
    f = tiles_module.floor()
    assert f.glyph == "."
    assert f.walkable is True


def test_c4_tile_kinds_enum_has_required_kinds():
    # Sprint 1 spec legend: walls and floors are required; doors, stairs are
    # allowed-but-not-required to be placed on the map. The kinds must exist
    # in the data model regardless.
    for name in ("WALL", "FLOOR", "DOOR", "UPSTAIRS", "DOWNSTAIRS"):
        assert hasattr(TileKind, name), f"missing TileKind.{name}"


# ---------- C5: floor / grid ------------------------------------------------

def test_c5_floor_dimensions_and_in_bounds():
    f = Floor(width=20, height=10)
    assert f.width == 20
    assert f.height == 10
    # Every in-bounds tile is accessible.
    for y in range(f.height):
        for x in range(f.width):
            assert f.get(x, y) is not None
    # Out-of-bounds is detectable.
    assert f.in_bounds(-1, 0) is False
    assert f.in_bounds(0, -1) is False
    assert f.in_bounds(20, 0) is False
    assert f.in_bounds(0, 10) is False
    # And raises (rather than silently returning a wrong value) on get.
    with pytest.raises(IndexError):
        f.get(-1, 0)


# ---------- C6: Entity / Player ---------------------------------------------

def test_c6_entity_base_class_exists():
    assert isinstance(Player.__mro__[1], type)
    # Player should inherit (directly or indirectly) from Entity.
    assert issubclass(Player, Entity)


def test_c6_player_position_and_glyph():
    p = Player(x=5, y=7)
    assert p.x == 5
    assert p.y == 7
    assert p.glyph == "@"


# ---------- C7: Game constructible from seed --------------------------------

def test_c7_game_from_seed_factory():
    game = Game.from_seed(seed=1)
    assert game is not None
    assert game.floor is not None
    px, py = game.player.x, game.player.y
    assert game.floor.in_bounds(px, py)


def test_c7_game_via_world_constructor_also_works():
    world = World(master_seed=1)
    game = Game(world)
    assert game.floor.in_bounds(game.player.x, game.player.y)


# ---------- C8: floor renderer dimensions -----------------------------------

def test_c8_render_floor_dimensions_match():
    f = Floor(width=10, height=5)
    out = render_floor(f)
    lines = out.split("\n")
    assert len(lines) == 5
    for line in lines:
        assert len(line) == 10


# ---------- C9: frame renderer overlays player ------------------------------

def test_c9_frame_renderer_places_player_glyph_exactly_once():
    game = Game.from_seed(seed=1)
    px, py = game.player.x, game.player.y
    frame = render_frame(game)
    rows = frame.split("\n")
    assert rows[py][px] == "@"
    assert frame.count("@") == 1


# ---------- C10: glyph legend -----------------------------------------------

def test_c10_frame_uses_documented_glyph_set_only():
    game = Game.from_seed(seed=1)
    frame = render_frame(game)
    allowed = {"#", ".", "+", "<", ">", "@"}
    chars = set(frame) - {"\n"}
    assert chars.issubset(allowed), f"unexpected glyphs in frame: {chars - allowed}"
    # A non-trivial frame must show at least one wall and the player.
    assert "#" in frame
    assert "@" in frame


# ---------- C11: 8-directional movement -------------------------------------

def _make_open_floor_with_player(width: int = 11, height: int = 11) -> Game:
    """Build a Game whose floor is an open arena and place the player at the
    center, so all eight neighbors are walkable.
    """
    # Construct an open-arena Floor directly, then inject it into the World
    # so we don't depend on the dungeon generator (which assumes larger maps).
    f = Floor(width=width, height=height)
    for y in range(f.height):
        for x in range(f.width):
            if x == 0 or y == 0 or x == f.width - 1 or y == f.height - 1:
                f.set(x, y, tiles_module.wall())
            else:
                f.set(x, y, tiles_module.floor())
    # Make the World return this floor without invoking the generator.
    world = World.__new__(World)
    world.master_seed = 1
    world.num_floors = 1
    world.width = width
    world.height = height
    world._floors = {0: f}
    game = Game(world)
    cx, cy = width // 2, height // 2
    game.teleport(cx, cy)
    return game


def _make_custom_world(width: int, height: int, fill_walkable: bool = True) -> World:
    """Build a World whose only floor is fully constructed by us."""
    f = Floor(width=width, height=height)
    if fill_walkable:
        for y in range(f.height):
            for x in range(f.width):
                f.set(x, y, tiles_module.floor())
    world = World.__new__(World)
    world.master_seed = 1
    world.num_floors = 1
    world.width = width
    world.height = height
    world._floors = {0: f}
    return world


def test_c11_eight_directional_movement_on_open_floor():
    game = _make_open_floor_with_player()
    cx, cy = game.player.x, game.player.y
    deltas = [
        (0, -1), (1, -1), (1, 0), (1, 1),
        (0, 1), (-1, 1), (-1, 0), (-1, -1),
    ]
    for dx, dy in deltas:
        game.teleport(cx, cy)
        before = (game.player.x, game.player.y)
        moved = game.try_move(dx, dy)
        assert moved is True, f"move ({dx},{dy}) should have succeeded"
        assert (game.player.x, game.player.y) == (before[0] + dx, before[1] + dy)


# ---------- C12: wall bump no-op --------------------------------------------

def test_c12_wall_bump_is_noop():
    # Build a 3x3 arena: walls everywhere except (1,1).
    world = _make_custom_world(3, 3, fill_walkable=False)
    f = world.get_floor(0)
    f.set(1, 1, tiles_module.floor())
    game = Game(world)
    game.teleport(1, 1)
    before = (game.player.x, game.player.y)
    moved = game.try_move(1, 0)  # into wall at (2,1)
    assert moved is False
    assert (game.player.x, game.player.y) == before


# ---------- C13: out-of-bounds moves are no-ops -----------------------------

def test_c13_oob_moves_are_noops_no_raise():
    world = _make_custom_world(5, 5, fill_walkable=True)
    game = Game(world)
    game.teleport(0, 0)
    # Should not raise.
    assert game.try_move(-1, 0) is False
    assert game.try_move(0, -1) is False
    assert (game.player.x, game.player.y) == (0, 0)


# ---------- C14: turn counter advances --------------------------------------

def test_c14_turn_counter_advances_on_actions():
    game = _make_open_floor_with_player()
    t0 = game.turns
    game.try_move(1, 0)  # valid move
    assert game.turns >= t0 + 1
    # Wall bump: from center, move OOB-ish or into a wall (border).
    cx, cy = game.player.x, game.player.y
    game.teleport(1, 1)  # right next to top-left wall
    t_before_bump = game.turns
    game.try_move(-1, 0)  # bump the left wall
    assert game.turns >= t_before_bump + 1


# ---------- C15: --headless prints frame, exits 0 ---------------------------

def test_c15_headless_run_prints_frame_and_exits_zero():
    parser = build_parser()
    args = parser.parse_args(["--seed", "1", "--headless"])
    out = io.StringIO()
    rc = run_headless(args, out=out)
    assert rc == 0
    text = out.getvalue()
    assert "@" in text
    assert "#" in text


# ---------- C16: --seed reproducibility -------------------------------------

def test_c16_same_seed_byte_identical_headless_output():
    parser = build_parser()
    a1 = io.StringIO()
    a2 = io.StringIO()
    run_headless(parser.parse_args(["--seed", "1", "--headless"]), out=a1)
    run_headless(parser.parse_args(["--seed", "1", "--headless"]), out=a2)
    assert a1.getvalue() == a2.getvalue()


# ---------- C18: explicit tile-walkability test (wall vs floor) -------------

def test_c18_tile_walkability_wall_vs_floor():
    assert tiles_module.wall().walkable is False
    assert tiles_module.floor().walkable is True


# ---------- C20: hygiene -- no third-party imports --------------------------

def test_c20_no_third_party_runtime_imports():
    """Walk every whisperdeep module and assert nothing imports a known
    third-party library. This is a heuristic guard, not a full audit, but it
    catches the obvious failure modes (numpy, tcod, rich, etc.)."""
    import pkgutil
    import whisperdeep

    forbidden = {
        "numpy", "tcod", "rich", "blessed", "blessings",
        "curses",  # platform-fragile; not allowed for Sprint 1 portability
        "pygame", "pyglet", "asciimatics",
        "click", "typer",  # we use argparse from stdlib
        "requests", "httpx",
    }

    for mod_info in pkgutil.iter_modules(whisperdeep.__path__):
        mod = importlib.import_module(f"whisperdeep.{mod_info.name}")
        # Inspect the module's globals for any imported module names.
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            mod_name = getattr(attr, "__module__", None) or getattr(attr, "__name__", None)
            if not isinstance(mod_name, str):
                continue
            top = mod_name.split(".")[0]
            assert top not in forbidden, (
                f"whisperdeep.{mod_info.name} imports forbidden module {top}"
            )


# ---------- C21: stability -- no traceback on stderr ------------------------

def test_c21_headless_subprocess_exit_zero_no_stderr_traceback():
    proc = subprocess.run(
        [sys.executable, "-m", "whisperdeep", "--headless", "--seed", "1"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "Traceback" not in proc.stderr
