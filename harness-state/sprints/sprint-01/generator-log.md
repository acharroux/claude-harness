# Sprint 1 — Foundation & Grid World — Generator Log

## Context

Sprint 1's contract (`harness-state/sprints/sprint-01/contract.json`) was
negotiated *after* Sprint 2 had already shipped. Per `handoff.json`, Sprint 1
was not implemented in a previous turn, and Sprint 2 bootstrapped the full
foundation (tile/floor/entity/game/render scaffolding, ASCII renderer,
8-directional movement, headless CLI) **alongside** the rooms-and-corridors
generator.

That meant most of Sprint 1's contract was already satisfied by code on disk.
This log records the audit and the small additions needed to satisfy every
Sprint 1 criterion *explicitly*, with tests that map to the contract item-by-
item rather than relying on Sprint 2's tests as side-effect coverage.

## What was already in place (from Sprint 2's bootstrap)

| Criterion | Where |
|-----------|-------|
| C1 — `whisperdeep` package importable | `whisperdeep/__init__.py` |
| C2 — `python -m whisperdeep` runnable | `whisperdeep/__main__.py` |
| C3 — distinct modules | `tiles.py`, `floor.py`, `entity.py`, `game.py`, `render.py` |
| C4 — Tile abstraction with WALL/FLOOR + glyph + walkable | `whisperdeep/tiles.py` |
| C5 — Floor with width/height/in_bounds/get | `whisperdeep/floor.py` |
| C6 — Entity base + Player with x/y/'@' | `whisperdeep/entity.py` |
| C7 — Game ties world+player, takes a seed | `whisperdeep/game.py`, `whisperdeep/cli.py:make_game` |
| C8 — `render_floor` produces height×width ASCII | `whisperdeep/render.py` |
| C9 — `render_frame` overlays player as '@' once | `whisperdeep/render.py` |
| C10 — glyph legend `# . + < > @` only | `whisperdeep/render.py` (legend dict) |
| C11 — 8-directional movement | `Game.try_move(dx, dy)` |
| C12 — wall bump no-op | `Game.try_move` checks `floor.get(nx,ny).walkable` |
| C13 — OOB move no-op (no raise) | `Game.try_move` checks `in_bounds` first |
| C14 — turn counter | `Game.turns`, incremented on every action |
| C15 — `--headless` prints frame, exit 0 | `whisperdeep/cli.py:run_headless` |
| C16 — `--seed` accepted, byte-identical for same seed | `whisperdeep/cli.py:build_parser` |
| C17 — pytest suite passes | `tests/test_generator.py`, `tests/test_game.py` (21 tests) |
| C19 — README/docs documents run, glyphs, flags | `docs/whisperdeep.md` |
| C20 — zero third-party runtime deps | only `random`, `argparse`, `dataclasses`, `enum` used |
| C21 — clean stderr, no traceback on `--headless --seed 1` | verified by hand |

Sprint 2's tests cover C12 (walls), C16 (`--seed`), C8 (frame dimensions on
the generated dungeon), and the floor/world plumbing, but not all of Sprint
1's specific item-level test steps verbatim.

## What I added in this sprint

1. **`Game.from_seed(seed, num_floors=3, width=80, height=40)` factory**
   — `whisperdeep/game.py`. Sprint 1 C7 says "Construct the Game (directly
   or via a factory) with seed=1." The CLI already had `make_game(seed=...)`
   but it lived in `cli.py`, not on Game. Adding the classmethod gives
   tests and downstream callers a single obvious entry point.

2. **`tests/test_sprint01.py`** — a new test module with one test per
   contract criterion, named `test_cNN_…` so failures map straight back
   to the contract item. 23 new tests:

   - C1: package importable.
   - C2: `python -m whisperdeep --help` exits 0 (subprocess).
   - C3: each of the five module roles imports cleanly.
   - C4: wall glyph='#', wall.walkable=False; floor glyph='.', floor.walkable=True;
     TileKind enum exposes WALL/FLOOR/DOOR/UPSTAIRS/DOWNSTAIRS.
   - C5: 20×10 floor has width/height; in-bounds works at every cell;
     OOB queries are detectable and `get()` raises `IndexError`.
   - C6: Player(5,7).x/y/glyph; Player subclasses Entity.
   - C7: `Game.from_seed(seed=1)` and `Game(World(master_seed=1))` both
     construct cleanly with player in-bounds.
   - C8: `render_floor(Floor(10, 5))` is exactly 5 lines of 10 chars.
   - C9: rendered frame has '@' at exactly `(player.x, player.y)` and
     `frame.count('@') == 1`.
   - C10: characters in the frame are a subset of `{# . + < > @}`; '#'
     and '@' both present.
   - C11: from the center of an open 11×11 arena, all 8 cardinal+diagonal
     moves succeed and update position by exactly the requested delta.
   - C12: 3×3 arena with one walkable tile; bumping the wall returns False
     and leaves position unchanged.
   - C13: from (0,0) on a 5×5 fully-walkable floor, `try_move(-1, 0)` and
     `try_move(0, -1)` return False without raising.
   - C14: turn counter increments on a valid move and on a wall bump.
   - C15: headless run prints '@' and '#' and returns 0.
   - C16: two `--seed 1 --headless` runs are byte-identical.
   - C18: explicit wall-vs-floor walkability assertion.
   - C20: a heuristic check walking every `whisperdeep` submodule and
     asserting nothing imports a known third-party UI/HTTP library.
   - C21: `python -m whisperdeep --headless --seed 1` subprocess exits 0
     and produces no `Traceback` on stderr.

   The C11/C12/C13 tests construct floors directly and inject them into
   a `World` (bypassing the generator) so we can exercise tiny maps where
   the generator's room-placement constraints would otherwise fail. The
   helper uses `World.__new__` + manual `_floors` priming — slightly hacky
   but contained to the test file and clearly commented.

3. **`whisperdeep/__init__.py` docstring** — refreshed to explicitly
   describe what Sprint 1 delivers, since the audit revealed the previous
   docstring read like Sprint 1 was barely scaffolded.

## Verification

- `pytest -q` reports **44 passed in 0.36s** (21 from Sprint 2 + 23 new
  Sprint 1 tests). Far above the C17 ">=8 collected, all pass" threshold.
- `python -m whisperdeep --help` exits 0.
- `python -m whisperdeep --headless --seed 1` exits 0 with empty stderr;
  same-seed runs are byte-identical.
- The frame contains '@' exactly once at the player's position, and only
  uses glyphs from the documented legend.

## Out of scope (per contract)

- No procedural generation work this sprint (Sprint 2 already shipped
  rooms-and-corridors).
- No FOV, combat, items, monsters, save/load, Whisperer, or polish work.

## Files touched

- `whisperdeep/__init__.py` — docstring refresh, no behavior change.
- `whisperdeep/game.py` — added `Game.from_seed(...)` classmethod.
- `tests/test_sprint01.py` — new, 23 contract-mapped tests.

## Commits

- `harness(sprint-01): explicit sprint-01 contract tests + Game.from_seed factory [C1…C21]`
