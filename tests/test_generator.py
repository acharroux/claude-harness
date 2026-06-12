"""Tests for the dungeon generator (Sprint 2)."""
from __future__ import annotations

import hashlib
from collections import deque

import pytest

from whisperdeep import generator
from whisperdeep.floor import Floor
from whisperdeep.tiles import TileKind


# ---------- helpers ----------------------------------------------------------

def floor_hash(floor: Floor) -> str:
    snap = floor.snapshot()
    h = hashlib.sha256()
    for row in snap:
        h.update("".join(row).encode())
        h.update(b"\n")
    return h.hexdigest()


def bfs_walkable(floor: Floor, start):
    seen = {start}
    q = deque([start])
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if (nx, ny) in seen:
                continue
            if not floor.in_bounds(nx, ny):
                continue
            if not floor.get(nx, ny).walkable:
                continue
            seen.add((nx, ny))
            q.append((nx, ny))
    return seen


# ---------- C1: module exists -----------------------------------------------

def test_generator_module_importable():
    import whisperdeep.generator as g  # noqa: F401
    assert hasattr(g, "generate")
    assert hasattr(g, "DungeonGenerator")


# ---------- C2: API ----------------------------------------------------------

def test_generate_returns_floor_with_requested_dims():
    floor = generator.generate(80, 40, seed=12345)
    assert floor.width == 80
    assert floor.height == 40
    # Tile access works at all in-bounds coordinates.
    for y in (0, 39, 20):
        for x in (0, 79, 40):
            t = floor.get(x, y)
            assert t.kind in TileKind


# ---------- C3: determinism (same seed -> same floor) -----------------------

def test_same_seed_produces_identical_floor():
    a = generator.generate(60, 30, seed=42)
    b = generator.generate(60, 30, seed=42)
    assert a.snapshot() == b.snapshot()


# ---------- C4: determinism (different seeds differ) -----------------------

def test_different_seeds_produce_different_floors():
    hashes = {floor_hash(generator.generate(60, 30, seed=s)) for s in (1, 2, 3, 4, 5)}
    assert len(hashes) >= 4


# ---------- C5: rooms exist and don't overlap -------------------------------

def test_floor_has_multiple_non_overlapping_rooms():
    floor = generator.generate(80, 40, seed=2024)
    assert len(floor.rooms) >= 4
    rooms = floor.rooms
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            # interior overlap check (zero padding)
            assert not a.overlaps(b, padding=0), f"rooms overlap: {a} & {b}"


# ---------- C6: connectivity ------------------------------------------------

def test_all_walkable_tiles_reachable():
    for seed in (10, 20, 30):
        floor = generator.generate(80, 40, seed=seed)
        walkables = floor.walkable_tiles()
        assert walkables, "no walkable tiles"
        reached = bfs_walkable(floor, walkables[0])
        assert len(reached) == len(walkables), (
            f"seed {seed}: only {len(reached)}/{len(walkables)} reachable"
        )


# ---------- C7: doors at room/corridor boundaries ---------------------------

def test_doors_exist_and_have_valid_adjacency():
    door_counts = []
    for seed in (1, 2, 3, 4, 5):
        floor = generator.generate(80, 40, seed=seed)
        door_positions = [
            (x, y)
            for x, y in floor.iter_coords()
            if floor.get(x, y).is_door
        ]
        door_counts.append(len(door_positions))

        # Build the set of room interior tiles.
        room_set = set()
        for room in floor.rooms:
            for x, y in room.interior_tiles():
                room_set.add((x, y))

        for dx_, dy_ in door_positions:
            neighbors = [
                (dx_ + 1, dy_), (dx_ - 1, dy_),
                (dx_, dy_ + 1), (dx_, dy_ - 1),
            ]
            adj_room_floor = any((nx, ny) in room_set for nx, ny in neighbors)
            adj_walkable = sum(
                1 for nx, ny in neighbors
                if floor.in_bounds(nx, ny) and floor.get(nx, ny).walkable
            )
            assert adj_room_floor, f"door at {(dx_, dy_)} has no adjacent room floor"
            assert adj_walkable >= 2, (
                f"door at {(dx_, dy_)} only has {adj_walkable} walkable neighbors"
            )

    avg = sum(door_counts) / len(door_counts)
    assert avg >= 1, f"average door count too low: {avg}"


# ---------- C8: stair counts per floor --------------------------------------

def test_stair_counts_for_three_floor_world():
    from whisperdeep.world import World
    world = World(master_seed=999, num_floors=3, width=80, height=40)
    f0 = world.get_floor(0)
    f1 = world.get_floor(1)
    f2 = world.get_floor(2)

    def count(f, kind):
        return sum(1 for x, y in f.iter_coords() if f.get(x, y).kind == kind)

    assert count(f0, TileKind.UPSTAIRS) == 0
    assert count(f0, TileKind.DOWNSTAIRS) == 1
    assert count(f1, TileKind.UPSTAIRS) == 1
    assert count(f1, TileKind.DOWNSTAIRS) == 1
    assert count(f2, TileKind.UPSTAIRS) == 1
    assert count(f2, TileKind.DOWNSTAIRS) == 0


# ---------- C9: stairs are walkable -----------------------------------------

def test_stairs_are_walkable_and_reachable():
    from whisperdeep.world import World
    world = World(master_seed=7, num_floors=3, width=80, height=40)
    for i in range(3):
        floor = world.get_floor(i)
        walkables = floor.walkable_tiles()
        reached = bfs_walkable(floor, walkables[0])
        for x, y in floor.iter_coords():
            t = floor.get(x, y)
            if t.is_upstairs or t.is_downstairs:
                assert t.walkable, f"stairs at {(x, y)} not walkable"
                assert (x, y) in reached, f"stairs at {(x, y)} unreachable"


# ---------- C14: world supports >=3 floors with distinct seeds --------------

def test_world_three_floors_distinct_seeds():
    from whisperdeep.world import World
    world = World(master_seed=999, num_floors=3, width=80, height=40)
    h0 = floor_hash(world.get_floor(0))
    h1 = floor_hash(world.get_floor(1))
    h2 = floor_hash(world.get_floor(2))
    assert h0 != h1
    # Three floors should be distinct in practice for different seeds.
    assert len({h0, h1, h2}) == 3


# ---------- bonus: Floor.in_bounds and snapshot round-trip ------------------

def test_floor_in_bounds_and_walkable():
    floor = generator.generate(50, 25, seed=11)
    assert floor.in_bounds(0, 0)
    assert not floor.in_bounds(-1, 0)
    assert not floor.in_bounds(50, 0)
    assert not floor.in_bounds(0, 25)
    walkables = floor.walkable_tiles()
    assert all(floor.walkable(x, y) for x, y in walkables)
