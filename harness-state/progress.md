# Harness Progress Log

**Project**: game (Whisperdeep)
**Started**: 2026-06-12T12:18:29Z
**Model**: opus
**Context strategy**: reset

---

## Sprint 2 — Dungeon Generation v1 (2026-06-12)

Bootstrapped the Whisperdeep package and shipped the seedable
rooms-and-corridors generator described in F2. Sprint 1 had not produced
any code in a previous run, so Sprint 2 also created the foundational
entity/tile/grid model, ASCII renderer, and basic player movement that
Sprint 1 was supposed to provide.

**Delivered**:
- `whisperdeep/` package: `tiles`, `floor`, `generator`, `world`, `entity`,
  `game`, `render`, `cli`, `__main__`.
- Deterministic dungeon generator (rooms + L-shaped corridors + doors +
  stairs).
- `World` abstraction supporting >=3 floors with per-floor seeds derived
  from a master seed; floors persist across descent/ascent.
- `python -m whisperdeep --seed N [--headless]` CLI.
- ASCII render with the documented glyph set (`#`, `.`, `+`, `<`, `>`, `@`).
- `tests/test_generator.py` and `tests/test_game.py` — 21 pytest tests, all
  passing, covering determinism, connectivity, stair invariants, door
  adjacency, floor persistence, wall bumps, doors-walkable, and the
  `--seed` CLI flag.
- `docs/whisperdeep.md` — generator parameters, glyph legend, controls,
  CLI flags.

Commits:
- `harness(sprint-02): scaffold + dungeon generator core [C1 C2 C3 C4 C5 C6 C7]`
- `harness(sprint-02): game/movement tests, world docs, glyph legend [C8…C22]`

## Sprint 05: Sprint 5

- **Status**: FAILED (all attempts exhausted)
- **Attempt**: 3
- **Time**: 2026-06-12T16:30:33Z


## Sprint 06: Sprint 6

- **Status**: FAILED (all attempts exhausted)
- **Attempt**: 3
- **Time**: 2026-06-12T17:38:13Z


## Sprint 07: Sprint 7

- **Status**: FAIL
- **Attempt**: 1
- **Time**: 2026-06-12T18:45:19Z


## Sprint 10 — Chronicle Generator (2026-06-12)

Implemented F9: end-of-run Markdown chronicle.

**Delivered**:
- `whisperdeep/chronicle.py`: `build_chronicle(game, *, name, fixed_timestamp)`,
  `write_chronicle(game, path, ...)`, `default_chronicle_path(game, name)`,
  `slugify_name(name)`. Module imports stdlib + typing only (layering preserved).
- New canonical `epitaph` event type added additively to `EventType` /
  `EVENT_TYPES`. Original ten event names preserved.
- `prose_pool.json` gains 10 distinct `epitaph` entries.
- `Game.end_run(cause='quit')` publishes `run_ended` + `epitaph`,
  idempotent, safe no-op with `whisperer=False`. Tracks `seed`,
  `_adapter_name`, `max_floor_reached` for the chronicle's metadata block.
- CLI flags `--name`, `--chronicle PATH`, `--chronicle-fixed-timestamp ISO`,
  `--no-chronicle`. All listed in `--help`.
- 34 new tests in `tests/test_sprint10.py`; 120/120 pytest green.
- `docs/whisperdeep.md` gains a Sprint-10 status banner and a full
  Chronicles section (format, epitaph event, lifecycle hook, CLI flags,
  default path, determinism, deferred cross-run legends).

Commits:
- `harness(contract): sprint-10 agreed`
- `harness(sprint-10): epitaph event, prose pool, end_run, chronicle module, CLI flags [C1 C3 C4 C8]`
- `harness(sprint-10): tests + docs for chronicle, epitaph, end_run hook [C2 C5 C6 C7 C9 C10 C11 C12 C13 C14 C15 C16 C17 C18]`
