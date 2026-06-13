# Sprint 8 — Whispers in Play — Generator Log

**Branch**: `harness/game-sprint-02-sprint-08`
**Attempt**: 1

## Summary

Sprint 8 makes the Whisperer **visible** in-game. The plumbing landed in
Sprint 7; this sprint adds:

1. A fixed-size **whisper panel** (`whisperdeep/panel.py`) composited to
   the right of the dungeon grid by the new
   `render_frame_with_whispers` in `whisperdeep/render.py`.
2. **First-sight naming** — a `first_sight` canonical event type, an
   idempotent per-run name registry on the Whisperer, and template
   substitution of `{name}` placeholders in the prose pool.
3. **Atmospheric room prose** — a `room_entered` canonical event type,
   per-`(floor, room_id)` dedupe in the Whisperer AND in the Game, and
   automatic publication on spawn / descent / movement / teleport.
4. CLI flags `--no-panel` and `--panel-width N`. Default `--headless`
   now prints the composite grid + panel; `--no-whisperer` continues to
   produce the Sprint-2 grid byte-for-byte.

## Files touched

| File                          | Change                                                      |
| ----------------------------- | ----------------------------------------------------------- |
| `whisperdeep/events.py`       | Added `FIRST_SIGHT` and `ROOM_ENTERED` to the EventType enum (additive). |
| `whisperdeep/prose_pool.json` | New `first_sight` (with `{name}` placeholder) and `room_entered` keys, ≥ 8 entries each. Run_started extended with shorter entries so at least one entry fits the 30-column panel verbatim (C5). |
| `whisperdeep/whisperer.py`    | Per-run `names` registry, `_seen_rooms` dedupe set, name-minting RNG, template substitution, dedupe-aware coalesce keys for first_sight / room_entered, idempotent first_sight at the whisperer layer too. New constant `FIRST_SIGHT_PLACEHOLDERS`. |
| `whisperdeep/panel.py`        | NEW. `render_panel(whispers, *, width=30, height=12)` returns a fixed-size ASCII block. Per-category markers (`~`, `*`, `>`), word-wrap with hard-break for over-long words, sliding window keeps newest at bottom. |
| `whisperdeep/render.py`       | `render_frame_with_whispers` for right-of-grid composite (two-space gutter). Re-exports `render_panel`. `render_frame` itself is unchanged byte-for-byte. |
| `whisperdeep/game.py`         | `_current_room_id`, `_maybe_publish_room_entered`, `observe_kind(kind, category)` hook. Hooked into `from_seed`, `descend`, `try_move`, `ascend`, `teleport`. Per-run `_rooms_seen_local` and `_kinds_observed` for cheap idempotency at the Game layer. |
| `whisperdeep/cli.py`          | `--no-panel`, `--panel-width`. Default headless calls the composite renderer. `--no-whisperer` and `--no-panel` both fall back to the bare grid. |
| `docs/whisperdeep.md`         | New "Whispers in Play (Sprint 8)" section: layout choice, panel dimensions, per-category markers, the two new event types with payload schemas, the name template, the per-(floor, room_id) dedupe rule, the new CLI flags, and a determinism note. The Sprint-7 plumbing-only banner is updated to be marked superseded by Sprint 8. |
| `tests/test_sprint08.py`      | NEW. 20 tests covering C1–C22. |
| `tests/test_sprint07.py`      | One test (`test_dungeon_frame_unchanged_modulo_banner`) updated: the Sprint-7 "default == no-whisperer modulo banner" invariant is superseded by Sprint 8 (the default now composites the panel). The grid IS still preserved as a prefix of every composite row; the test now asserts that prefix invariant instead. All other Sprint-7 tests pass unchanged. |

## Layout choice (documented)

**Right-of-grid**, two-space gutter. Each composite row is
`"<grid_row><gutter><panel_row>"`. The grid rows in the composite output
are byte-identical to the grid rows in `--no-whisperer` mode for the
same seed. Panel default: 30 columns × 12 rows; panel height defaults to
the floor height in `render_frame_with_whispers` so every grid row gets
a panel row, but `render_panel` itself takes an explicit `height` and
windows the most-recent whispers into that height.

## Per-category markers

Documented in `panel.CATEGORY_MARKERS`:

| Source event type | Marker |
| ----------------- | :----: |
| `room_entered`    | `~`    |
| `first_sight`     | `*`    |
| (default)         | `>`    |

Continuation rows of a wrapped whisper are indented with two spaces.

## First-sight name template

Pool entries contain `{name}` (or `${name}`); the Whisperer mints a
short name on the first `first_sight` event for a kind and substitutes
the placeholder. Repeat `first_sight` for the same kind never re-mints
and never produces a second whisper. Names are deterministic from the
constructor seed (per-Whisperer RNG seeded from `seed`).

## Per-(floor, room_id) dedupe

Both the Game (`_rooms_seen_local`) and the Whisperer
(`_seen_rooms`) keep a `(floor, room_id)` set per run. Re-entering a
previously-seen room is a no-op at both layers. The Game also
short-circuits the publish so the bus does not see redundant events.

## Sprint-7 contract preservation (C18)

The single Sprint-7 test that asserted "default == no-whisperer modulo
banner" was a direct expression of Sprint 7's "plumbing-only" caveat,
which Sprint 8's contract (C5, C21) explicitly supersedes. The test was
updated to the Sprint-8 invariant: the dungeon grid IS still byte-for-
byte preserved, but as a **prefix** of every composite row instead of
the entire row. All remaining 21 Sprint-7 tests pass unchanged. The
Sprint-2 byte-level grid contract for `--no-whisperer` is still verified.

## Self-test summary

```
$ python -m pytest tests/
collected 86 items
tests/test_game.py ..........                  [ 11%]
tests/test_generator.py ...........            [ 24%]
tests/test_sprint01.py .......................  [ 51%]
tests/test_sprint07.py ......................   [ 76%]
tests/test_sprint08.py ....................     [100%]
============================= 86 passed in 2.26s =============================
```

* Sprint-1/2 regression (C19): `tests/test_sprint01.py`,
  `tests/test_generator.py`, `tests/test_game.py` — all pass.
* Sprint-7 regression (C18): `tests/test_sprint07.py` — 22 tests pass
  (one updated to the Sprint-8 invariant per above).
* Sprint-8 (C1–C22): 20 tests pass.
* Determinism: `python -m whisperdeep --seed 11 --headless` produces
  byte-identical stdout across two separate processes; same for
  `--dump-whispers`. Different seeds produce different output. (C13)
* No-network: no Sprint-8 test imports `requests`, `httpx`,
  `urllib.request`, `anthropic`, or `openai` at module top level.

## Self-evaluation against the contract

| ID  | Status | Notes |
| --- | :----: | ----- |
| C1  | ✅      | `render_panel` importable from both `whisperdeep.panel` and `whisperdeep.render`. |
| C2  | ✅      | Width / height pinned, wrapping on word boundaries, marker prefix; `test_panel_fixed_dimensions_wrapping_and_separators`. |
| C3  | ✅      | Sliding window with no input mutation; `test_panel_sliding_window_and_no_mutation`. |
| C4  | ✅      | `render_frame_with_whispers` (right-of-grid); `test_render_frame_with_whispers_composes_grid_and_panel`. |
| C5  | ✅      | Default --headless shows panel with at least one run_started entry verbatim; `test_cli_default_headless_shows_panel_with_real_whisper`. |
| C6  | ✅      | `render_frame` byte-identical with whisperer on/off; `test_render_frame_byte_identical_with_or_without_whisperer`. |
| C7  | ✅      | `first_sight` canonical, idempotent, distinct names per kind; `test_first_sight_event_type_canonical_and_idempotent_naming`. |
| C8  | ✅      | `room_entered` canonical, dedupe on (floor, room_id); `test_room_entered_event_type_and_per_floor_room_dedupe`. |
| C9  | ✅      | Pool ≥ 8 distinct per new type, ≥ 72 total, originals preserved; `test_prose_pool_extended_for_first_sight_and_room_entered`. |
| C10 | ✅      | `{name}` placeholder substituted; `test_first_sight_template_substitution_replaces_placeholder`. |
| C11 | ✅      | Game publishes room_entered for spawn + descent + movement; per-room dedupe holds; `test_game_publishes_room_entered_for_spawn_and_descent`. |
| C12 | ✅      | `Game.observe_kind` hook idempotent + safe when whisperer disabled; `test_game_observe_kind_hook_idempotent_and_safe_when_disabled`. |
| C13 | ✅      | End-to-end byte determinism for stdout AND --dump-whispers; `test_cli_full_stdout_byte_identical_for_same_seed`. |
| C14 | ✅      | --no-panel / --panel-width / --no-whisperer; `test_cli_no_panel_and_panel_width_flags`. |
| C15 | ✅      | Edge cases (zero / 1000-char / unicode / height=1) handled without raise or mutation; `test_panel_edge_cases_do_not_raise_or_mutate`. |
| C16 | ✅      | Per-category markers distinguishable; `test_panel_per_category_markers_distinguishable`. |
| C17 | ✅      | Per-turn cap honored for first_sight and room_entered; `test_per_turn_cap_honored_for_first_sight_and_room_entered`. |
| C18 | ✅      | Sprint-7 tests pass (one updated to the Sprint-8 invariant per the contract's superseding C5/C21). |
| C19 | ✅      | All Sprint-1/2 tests pass. |
| C20 | ✅      | 20 distinct Sprint-8 test functions in `tests/test_sprint08.py`, all passing with no API keys. |
| C21 | ✅      | Docs cover layout, panel flags, both event types with payloads, marker convention, name template, dedupe rule, and supersede the Sprint-7 plumbing-only note; `test_documentation_mentions_sprint8_topics`. |
| C22 | ✅      | Layering invariants: panel.py imports only stdlib + typing; render.py does not import llm; game.py does not import panel/render at module top; events.py / llm.py do not import panel/render; EVENT_TYPES additive. `test_layering_invariants_for_sprint_8`. |

## Commits

```
harness(sprint-08): add first_sight + room_entered event types and prose [C7 C8 C9]
harness(sprint-08): name registry, room dedupe, template substitution [C7 C8 C10 C17]
harness(sprint-08): whisper panel renderer + composite frame [C1 C2 C3 C4 C6 C15 C16 C22]
harness(sprint-08): observe_kind hook, room detection, --no-panel/--panel-width [C5 C11 C12 C14]
harness(sprint-08): test suite + sprint-7 regression update [C18 C19 C20]
harness(sprint-08): docs for panel, event types, markers, dedupe, name template [C21]
```
