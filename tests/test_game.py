"""Tests for game state, movement, descent/ascent, and rendering."""
from __future__ import annotations

import sys
from io import StringIO

import pytest

from whisperdeep import generator
from whisperdeep.cli import build_parser, run_headless
from whisperdeep.game import Game
from whisperdeep.render import render_frame, render_floor
from whisperdeep.tiles import TileKind
from whisperdeep.world import World


# ---------- C10: player spawns inside a room --------------------------------

def test_player_spawns_inside_room_on_walkable_tile():
    world = World(master_seed=12345, num_floors=3)
    game = Game(world)
    px, py = game.player.x, game.player.y
    floor = game.floor
    assert floor.walkable(px, py)
    assert any(r.contains(px, py) for r in floor.rooms), (
        f"player spawn ({px},{py}) not inside any room"
    )


# ---------- C11: descent ----------------------------------------------------

def test_descend_advances_floor_and_places_on_upstairs():
    world = World(master_seed=42, num_floors=3)
    game = Game(world)
    # Teleport to the downstairs.
    floor = game.floor
    assert floor.downstairs_pos is not None
    game.teleport(*floor.downstairs_pos)
    assert game.descend() is True
    assert game.current_floor_index == 1
    new_floor = game.floor
    # Player should be exactly on upstairs (we always place them there).
    assert (game.player.x, game.player.y) == new_floor.upstairs_pos


# ---------- C12: ascent -----------------------------------------------------

def test_ascend_returns_to_previous_floor_on_downstairs():
    world = World(master_seed=42, num_floors=3)
    game = Game(world)
    floor0_downstairs = game.floor.downstairs_pos
    game.teleport(*floor0_downstairs)
    game.descend()
    # On floor 1 now, on the upstairs tile. Ascend.
    assert game.ascend() is True
    assert game.current_floor_index == 0
    assert (game.player.x, game.player.y) == floor0_downstairs


# ---------- C13: floor persistence across descent/ascent -------------------

def test_floor_persists_across_descent_and_ascent():
    world = World(master_seed=42, num_floors=3)
    game = Game(world)
    floor0_snap_before = game.floor.snapshot()
    game.teleport(*game.floor.downstairs_pos)
    game.descend()
    game.ascend()
    floor0_snap_after = game.floor.snapshot()
    assert floor0_snap_before == floor0_snap_after


# ---------- C15: glyph set --------------------------------------------------

def test_render_uses_documented_glyph_set():
    # Sprint 11: this test verifies the Sprint 1/2 default glyph set still
    # works when the floor's archetype preserves the defaults. We pin the
    # archetype to 'crypt' which keeps '#'/'.'/'+' as-is. Stair glyphs
    # ('<', '>') and the player glyph ('@') are reserved across all
    # archetypes.
    world = World(master_seed=1, num_floors=3, forced_archetype="crypt")
    game = Game(world)
    frame = render_frame(game)
    # All wall/floor/player glyphs should be present on floor 0.
    assert "#" in frame
    assert "." in frame
    assert "@" in frame
    # The downstairs glyph is on floor 0 (since num_floors=3, floor 0 is non-final).
    assert ">" in frame
    # Doors usually appear too — check at least once across a few seeds.
    found_door = False
    for seed in (1, 2, 3, 4, 5):
        f = generator.generate(80, 40, seed=seed)
        if any(f.get(x, y).is_door for x, y in f.iter_coords()):
            found_door = True
            break
    assert found_door
    # Upstairs is on floor 1.
    floor1 = world.get_floor(1)
    rendered_f1 = render_floor(floor1)
    assert "<" in rendered_f1


# ---------- C16: initial frame shows generated dungeon ----------------------

def test_initial_frame_shows_dungeon_and_player():
    # Sprint 11: pin the archetype to one that preserves the Sprint 1/2
    # default glyphs ('#', '.', '+') so this Sprint-1 test stays valid.
    world = World(master_seed=1, num_floors=3, forced_archetype="crypt")
    game = Game(world)
    frame = render_frame(game)
    # Walls, floors, player all present.
    assert "#" in frame
    assert "." in frame
    assert "@" in frame
    # The frame should be a recognizable grid (height lines).
    lines = frame.splitlines()
    assert len(lines) == game.floor.height
    assert all(len(line) == game.floor.width for line in lines)


# ---------- C17: wall bumping ------------------------------------------------

def test_player_cannot_walk_through_walls():
    world = World(master_seed=1, num_floors=3)
    game = Game(world)
    floor = game.floor
    # Find a wall adjacent to the player and attempt to walk into it.
    px, py = game.player.x, game.player.y
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = px + dx, py + dy
        if floor.in_bounds(nx, ny) and floor.get(nx, ny).is_wall:
            before = (game.player.x, game.player.y)
            moved = game.try_move(dx, dy)
            assert moved is False
            assert (game.player.x, game.player.y) == before
            return
    # If we somehow can't find an adjacent wall, place the player next to one.
    # Find any floor cell adjacent to a wall.
    for x, y in floor.iter_coords():
        if not floor.walkable(x, y):
            continue
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if floor.in_bounds(nx, ny) and floor.get(nx, ny).is_wall:
                game.player.x, game.player.y = x, y
                before = (x, y)
                moved = game.try_move(dx, dy)
                assert moved is False
                assert (game.player.x, game.player.y) == before
                return
    pytest.fail("could not find a wall to bump into")


# ---------- C18: walking through doors --------------------------------------

def test_player_can_walk_through_doors():
    # Find a seed where a door exists somewhere reachable, then move onto it.
    world = World(master_seed=1, num_floors=3)
    game = Game(world)
    floor = game.floor
    door_positions = [
        (x, y) for x, y in floor.iter_coords() if floor.get(x, y).is_door
    ]
    assert door_positions, "expected at least one door"
    dx, dy = door_positions[0]
    # Pick an adjacent walkable tile to stand on.
    for ox, oy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ax, ay = dx + ox, dy + oy
        if floor.walkable(ax, ay) and not floor.get(ax, ay).is_door:
            game.teleport(ax, ay)
            moved = game.try_move(-ox, -oy)
            assert moved is True
            assert (game.player.x, game.player.y) == (dx, dy)
            assert floor.get(dx, dy).is_door
            return
    pytest.fail("no adjacent walkable to step onto a door")


# ---------- C19: --seed CLI flag --------------------------------------------

def test_cli_seed_flag_controls_dungeon():
    parser = build_parser()
    a1_args = parser.parse_args(["--seed", "7", "--headless"])
    a2_args = parser.parse_args(["--seed", "7", "--headless"])
    b_args = parser.parse_args(["--seed", "8", "--headless"])
    out_a1 = StringIO()
    out_a2 = StringIO()
    out_b = StringIO()
    run_headless(a1_args, out=out_a1)
    run_headless(a2_args, out=out_a2)
    run_headless(b_args, out=out_b)
    assert out_a1.getvalue() == out_a2.getvalue()
    assert out_a1.getvalue() != out_b.getvalue()


# ---------- C21: regression — game launches and accepts a move -------------

def test_game_launches_and_accepts_a_move():
    world = World(master_seed=1, num_floors=3)
    game = Game(world)
    assert game.player.glyph == "@"
    floor = game.floor
    # Find any free direction and step into it.
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = game.player.x + dx, game.player.y + dy
        if floor.walkable(nx, ny):
            assert game.try_move(dx, dy) is True
            return
    pytest.fail("player has no free direction to move from spawn")
