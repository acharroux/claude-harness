# Whisperdeep

A roguelike with a living dungeon master.

This is the game built sprint-by-sprint inside this repository by the
Planner–Generator–Evaluator harness. The harness tooling itself lives in
`harness/` and is documented in [the top-level README](../README.md).

> **Status — Sprint 2: Dungeon Generation v1.** The game now boots with a
> seedable rooms-and-corridors dungeon, doors, multi-floor descent, and an
> ASCII render loop. Combat, FOV, items, and the Whisperer (LLM-backed dungeon
> master) come in later sprints — see `harness-state/product-spec.md`.

---

## Quick start

Whisperdeep targets **Python 3.11+**. From the repository root:

```sh
python -m whisperdeep --seed 1
```

Headless mode (prints the initial frame and exits) — useful for snapshot tests
and CI:

```sh
python -m whisperdeep --seed 1 --headless
```

## Glyph legend

The renderer uses a strict ASCII glyph set:

| Glyph | Meaning              |
| :---: | :------------------- |
| `#`   | wall (impassable)    |
| `.`   | floor (walkable)     |
| `+`   | door (walkable)      |
| `<`   | upstairs             |
| `>`   | downstairs           |
| `@`   | the player           |

Walls block movement; bumping into a wall is a no-op (the player's position
does not change). Doors are walkable — you simply step onto them. Stairs are
walkable too; to actually change floor, press `>` on a downstairs tile or
`<` on an upstairs tile.

## Controls (interactive mode)

| Key      | Action                              |
| :------: | :---------------------------------- |
| h/j/k/l  | move west / south / north / east    |
| y/u/b/n  | move diagonally (NW/NE/SW/SE)       |
| `.`      | wait one turn                       |
| `>`      | descend stairs (when on `>`)        |
| `<`      | ascend stairs (when on `<`)         |
| q        | quit                                |

## Dungeon generator

The generator (`whisperdeep.generator`) is a deterministic
rooms-and-corridors algorithm. Given a `(width, height, seed)` triple it
always produces the same floor.

```python
from whisperdeep.generator import generate
floor = generate(width=80, height=40, seed=12345)
```

### Tunable parameters

The `DungeonGenerator` class (and `generate()`) accept the following keyword
arguments:

| Parameter              | Default | Meaning                                                 |
| ---------------------- | :-----: | ------------------------------------------------------- |
| `max_rooms`            | 14      | Upper bound on rooms placed per floor.                  |
| `room_min_size`        | 5       | Minimum room width and height (interior, in tiles).     |
| `room_max_size`        | 11      | Maximum room width and height (interior, in tiles).     |
| `max_placement_tries`  | 200     | How many random rectangles to try before giving up.     |
| `place_upstairs`       | `True`  | If `True`, the floor receives a `<` tile.               |
| `place_downstairs`     | `True`  | If `True`, the floor receives a `>` tile.               |

Floors are connected by L-shaped corridors between consecutive rooms in
placement order. Doors (`+`) are placed only on corridor tiles that sit
between two walls and an open room interior, i.e. classic doorways — never
in the open and never at junctions.

### Multi-floor worlds

A `World` packages together a dungeon of several floors:

```python
from whisperdeep.world import World
world = World(master_seed=999, num_floors=3, width=80, height=40)
floor0 = world.get_floor(0)   # no upstairs, has '>'
floor1 = world.get_floor(1)   # has '<' and '>'
floor2 = world.get_floor(2)   # has '<', no '>'
```

Each floor's seed is derived from the master seed plus its index, so a
single master seed reproduces the entire dungeon. Floors are generated
lazily on first access and persisted thereafter — descending and ascending
preserves the previous floor's exact layout.

## Command-line flags

| Flag                  | Default | Meaning                                                 |
| --------------------- | :-----: | ------------------------------------------------------- |
| `--seed N`            | 1       | Master seed for dungeon generation. Same seed → same dungeon. |
| `--width N`           | 80      | Floor width in tiles.                                   |
| `--height N`          | 40      | Floor height in tiles.                                  |
| `--floors N`          | 3       | Number of dungeon floors.                               |
| `--headless`          | off     | Print the initial frame and exit (no input loop).       |
| `--frames N`          | 0       | Reserved for future scripted snapshot tests.            |

The `--seed` flag is end-to-end deterministic: two invocations with the same
seed produce byte-identical initial frames; different seeds produce
different frames.

## Tests

```sh
pytest tests/test_generator.py tests/test_game.py
```

Test coverage includes determinism (same seed = same floor), connectivity
(every walkable tile reachable from any other), stair invariants (correct
`<` / `>` counts per floor), door adjacency, floor persistence across
descent/ascent, wall-bump no-op, and the `--seed` CLI flag.

## Project layout

```
whisperdeep/
  __init__.py
  __main__.py        # `python -m whisperdeep`
  cli.py             # argument parsing and entry points
  tiles.py           # Tile + TileKind, glyph legend
  floor.py           # Floor (2D grid) and Room
  generator.py       # DungeonGenerator — rooms and corridors
  world.py           # multi-floor World
  entity.py          # Entity / Player
  game.py            # Game state, movement, descend/ascend
  render.py          # ASCII frame renderer
tests/
  test_generator.py  # generator unit tests
  test_game.py       # game/movement/CLI tests
```
