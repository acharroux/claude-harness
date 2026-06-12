# Sprint 2 — Dungeon Generation v1 — Generator Log

**Branch**: `harness/game-sprint-02`
**Attempt**: 1
**Result**: ready-for-eval

## Context note

The handoff at the start of this sprint claimed Sprint 1 had been completed
but `harness-state/sprints/sprint-01/` was empty and there was no
`whisperdeep/` package on disk. I therefore implemented Sprint 1's
foundational scaffold (tile/grid model, entity layer, render loop, basic
player movement) **as part of** Sprint 2, then layered the contract's
Sprint 2 deliverables on top. All Sprint 2 criteria are independently
verifiable; Sprint 1's regression criterion (C21) is also covered.

## Architecture

```
whisperdeep/
  tiles.py      Tile + TileKind enum; glyph + walkable properties
  floor.py      Floor (2D grid) and Room dataclass
  generator.py  DungeonGenerator — rooms-and-corridors, deterministic
  world.py      World — multi-floor, lazy-generated, persistent
  entity.py     Entity / Player
  game.py      Game — state, try_move, descend, ascend, teleport
  render.py    render_frame / render_floor — pure-string output
  cli.py       argparse, headless and interactive modes
  __main__.py  python -m whisperdeep
tests/
  test_generator.py    11 tests for generator/floor/world
  test_game.py         10 tests for movement, descent, rendering, CLI
docs/
  whisperdeep.md       Player + developer documentation
```

## Algorithm summary

- Rooms are placed by random rectangle + rejection sampling
  (`max_placement_tries=200`, `max_rooms=14`, room interior 5–11 tiles per
  side). Padded overlap test prevents wall-to-wall touches.
- Rooms are connected in placement order with L-shaped (HV or VH chosen by
  RNG) corridors between centers. Corridor tiles are tracked separately so
  doors can be detected at room/corridor transitions.
- A corridor tile becomes a door iff it is adjacent to a room interior
  AND its remaining cardinal neighbors form the classical doorway pattern
  (two opposite walkable, two opposite walls).
- Upstairs at the first room's center, downstairs at the last room's
  center. The first floor of a `World` skips upstairs; the last floor
  skips downstairs.
- All randomness flows from a single `random.Random(seed)`; per-floor
  seeds are derived from a 64-bit avalanche of `(master_seed, floor_index)`.

## Criteria self-check

| ID  | Status | Test                                                |
| --- | :---:  | --------------------------------------------------- |
| C1  | ✓      | `test_generator_module_importable`                  |
| C2  | ✓      | `test_generate_returns_floor_with_requested_dims`   |
| C3  | ✓      | `test_same_seed_produces_identical_floor`           |
| C4  | ✓      | `test_different_seeds_produce_different_floors`     |
| C5  | ✓      | `test_floor_has_multiple_non_overlapping_rooms`     |
| C6  | ✓      | `test_all_walkable_tiles_reachable`                 |
| C7  | ✓      | `test_doors_exist_and_have_valid_adjacency`         |
| C8  | ✓      | `test_stair_counts_for_three_floor_world`           |
| C9  | ✓      | `test_stairs_are_walkable_and_reachable`            |
| C10 | ✓      | `test_player_spawns_inside_room_on_walkable_tile`   |
| C11 | ✓      | `test_descend_advances_floor_and_places_on_upstairs`|
| C12 | ✓      | `test_ascend_returns_to_previous_floor_on_downstairs`|
| C13 | ✓      | `test_floor_persists_across_descent_and_ascent`     |
| C14 | ✓      | `test_world_three_floors_distinct_seeds`            |
| C15 | ✓      | `test_render_uses_documented_glyph_set`             |
| C16 | ✓      | `test_initial_frame_shows_dungeon_and_player`       |
| C17 | ✓      | `test_player_cannot_walk_through_walls`             |
| C18 | ✓      | `test_player_can_walk_through_doors`                |
| C19 | ✓      | `test_cli_seed_flag_controls_dungeon`               |
| C20 | ✓      | `pytest tests/` — 21 passed (≥5 generator tests)    |
| C21 | ✓      | `test_game_launches_and_accepts_a_move`             |
| C22 | ✓      | `docs/whisperdeep.md` — generator params, glyph legend, `--seed` |

`pytest` output:

```
============================= 21 passed in 0.21s ==============================
```

## How to verify manually

```sh
# Headless dungeon snapshot.
python -m whisperdeep --seed 1 --headless

# Same seed → byte-identical frames.
python -m whisperdeep --seed 7 --headless > a.txt
python -m whisperdeep --seed 7 --headless > b.txt
diff a.txt b.txt

# Different seed → different frame.
python -m whisperdeep --seed 8 --headless > c.txt
diff a.txt c.txt

# Run the full test suite.
pytest tests/test_generator.py tests/test_game.py -v
```

## Commits

- `8f0…` *(parent: b185d8a)* `harness(sprint-02): scaffold + dungeon generator core [C1 C2 C3 C4 C5 C6 C7]`
- `aa73b7a` `harness(sprint-02): game/movement tests, world docs, glyph legend [C8…C22]`

## Out-of-scope (per contract)

Combat, FOV, items, monsters, save/load, daily seeds, the Whisperer (LLM
director), themed archetypes, sound, BSP/CA generation, secret rooms.
