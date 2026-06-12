# Sprint 11 — Themed Archetypes & Palettes (Generator Log)

**Attempt**: 1
**Date**: 2026-06-12
**Branch**: harness/game-sprint-02-sprint-11

## Summary

Implemented F11: themed dungeon archetypes with per-floor palettes,
glyph variants, prose tags, and a metadata-only monster pool. Five
archetypes ship: `crypt`, `flooded_sewer`, `mushroom_forest`,
`bone_library`, and the rare/secret `whisperhall`.

## Delivered

### New module: `whisperdeep/archetypes.py`

* `DungeonArchetype` (frozen dataclass) with `id`, `name`,
  `glyph_overrides`, `palette`, `prose_tag`, `monster_pool`, `rare`,
  `weight` and a `glyph_for(kind)` method that returns the rendered
  glyph after honoring overrides while preserving the reserved upstairs
  / downstairs / player glyphs.
* `ARCHETYPES` tuple of five built-in archetypes; `ARCHETYPE_BY_ID`
  dict for fast lookup; `REQUIRED_IDS`, `SECRET_ID`,
  `REQUIRED_PALETTE_KEYS`, `RESERVED_GLYPHS`, `DEFAULT_GLYPHS`
  constants.
* `get_archetype(id)` — KeyError on unknown id.
* `assign_archetype(master_seed, floor_index)` — deterministic
  weighted SHA-256-based draw. Same arguments always return the same
  instance; small sweeps yield diverse archetypes; the rare archetype
  is reachable across a small `(seed, floor)` cross-product.
* `palette_to_ansi(palette, key)` — returns `"\x1b[...m"` or `""`
  (defensive on missing keys / bad values, never raises).
* `palette_value_to_ansi(value)` — handles int 0..255 and `#rrggbb`.
* `archetype_summary_line(archetype)` — one-line CLI summary.
* `validate_archetype(archetype)` — runs at import time on each
  built-in to fail loudly on malformed data.

Layering: imports stdlib + typing + `whisperdeep.tiles` only.

### Modified: `whisperdeep/floor.py`

* Floor gains an `archetype: Optional[DungeonArchetype]` attribute
  (default None for defensively-constructed floors).
* New `Floor.snapshot_glyphs()` method returns a tuple-of-tuples of
  single-character glyph strings reflecting archetype overrides.
* `Floor.snapshot()` (kind-snapshot) is unchanged.

### Modified: `whisperdeep/world.py`

* `World.__init__` accepts `forced_archetype: Optional[str]` (resolved
  via `get_archetype` so a bad id raises immediately).
* `World.get_floor(i)` assigns `floor.archetype` BEFORE returning,
  using either the forced override or `assign_archetype(master_seed, i)`.
* Floor identity is preserved across calls; archetype is not
  reassigned on cache hits.

### Modified: `whisperdeep/render.py`

* `render_floor` and `render_frame` now use a small
  `_glyph_for_floor_cell` helper that consults the floor's archetype
  glyph overrides (defaults preserved when archetype is None or doesn't
  override that kind).
* New `colorize_frame(game)` helper emits ANSI 256/truecolor escape
  sequences using the floor's palette. Stripping the ANSI sequences
  yields the same plain text as `render_frame`.
* New `render_floor_glyphs(floor)` top-level helper aliases
  `Floor.snapshot_glyphs`.
* `render_frame` continues to emit zero ESC characters by default
  (Sprint 7/8/10 byte-determinism contracts preserved).

### Modified: `whisperdeep/game.py`

* `Game.from_seed` accepts `forced_archetype` and threads it through
  the `World` constructor.
* `_archetype_id_for_floor(i)` helper added.
* All event publishers (`run_started`, `room_entered`, `descended`,
  `first_sight`, `run_ended`, `epitaph`) augment payloads with an
  `archetype` field (None when the floor has no archetype).

### Modified: `whisperdeep/llm.py`

* `LLMAdapter.complete` signature gains `archetype: Optional[str] = None`.
* `OfflineAdapter.complete` prefers the `<event_type>.<archetype_id>`
  sub-pool when present; falls back to the generic event-type pool;
  finally to the flat union.
* `NullAdapter`, `AnthropicAdapter`, `OpenAIAdapter` updated with the
  new keyword (kept signature-compatible).

### Modified: `whisperdeep/whisperer.py`

* `Whisper` dataclass gains an `archetype: Optional[str]` field.
* `Whisperer._handle_event` reads `payload['archetype']` and threads
  it through `_produce` / `_call_fallback` to the adapter call.
* New `_adapter_complete` helper wraps `adapter.complete(...)` with a
  TypeError fallback so adapters that predate the Sprint-11 keyword
  keep working.

### Modified: `whisperdeep/prose_pool.json`

* Original ten generic keys (run_started, run_ended, entered_room,
  killed_monster, low_hp, found_item, descended, first_sight,
  room_entered, epitaph) preserved with the same >= 8 entries each.
* Added `room_entered.<archetype_id>` and `first_sight.<archetype_id>`
  sub-keys for each of the five archetypes, with 6 distinct entries
  per key (>= 4 required).

### Modified: `whisperdeep/cli.py`

* New `--archetype ID` flag forces a single archetype across all
  floors of the run.
* New `--list-archetypes` flag prints one summary line per registered
  archetype to stdout and exits 0.
* Unknown `--archetype` ids exit 2 with a clear error to stderr that
  references `--list-archetypes` and the valid ids.

### Modified: `docs/whisperdeep.md`

* Sprint 11 status banner added.
* New "Archetypes & Palettes (Sprint 11)" section: archetype list,
  glyph-variant table, palette descriptor format, prose-tag
  convention, monster-pool stub note, CLI flags, determinism
  guarantees, ANSI-opt-in note (full colour wiring in Sprint 12),
  layering invariants.

### Tests

* `tests/test_sprint11.py` with **41** distinct `test_*` functions
  covering C1..C17 (>= 14 required).
* Updated four pre-Sprint-11 tests that hard-coded the original
  Sprint-1/2 default glyphs — they now pin the archetype to `crypt`
  (which preserves `#`/`.`/`+`) so the documented-glyph assertions
  remain valid:
  - `tests/test_game.py::test_render_uses_documented_glyph_set`
  - `tests/test_game.py::test_initial_frame_shows_dungeon_and_player`
  - `tests/test_sprint01.py::test_c10_frame_uses_documented_glyph_set_only`
  - `tests/test_sprint08.py::test_render_frame_byte_identical_with_or_without_whisperer`
  - `tests/test_sprint10.py::test_c14_glyphs_present_for_seed_1`

## Test results

```
174 passed in 5.74s
```

All prior-sprint suites (sprint-01, sprint-07, sprint-08, sprint-10,
test_game, test_generator, test_fix001) still pass unchanged after the
small adjustments noted above.

## Decisions / notes

* **Archetype data lives in code**, not in a separate JSON resource.
  The contract allows either; keeping the data in `archetypes.py` keeps
  the layering crisp and the import deterministic, and the CLI/test
  surface didn't need a JSON-loading path.
* **`crypt` deliberately preserves Sprint-1/2 default glyphs**. This
  let me pin the four pre-existing legacy tests to `crypt` to keep
  them meaningful, while still making `crypt` a proper archetype with
  its own palette / prose tag / monster pool.
* **Whisper.archetype** is recorded at publish time from the event
  payload (which the Game populates from
  `world.get_floor(i).archetype.id`). This avoids the Whisperer
  importing world/floor/archetype types directly — the bus and
  adapters stay layer-clean.
* **The rare archetype** (`whisperhall`, weight 2 vs 20 for the
  others) is reachable across a small (seed, floor) cross-product.
  My test sweeps `seed in 1..200, floor in 0..7` and asserts at
  least one hit; a tighter sweep on a single dimension may not see
  it (verified: sweep `seed=42, floor 0..7` and sweep `seed 1..50,
  floor=0` both happen to miss it; the cross-product hits it 44
  times).
* **`forced_archetype` plumbing**: World is the canonical place for
  the override (so `--archetype` and `forced_archetype="crypt"` in
  Python both flow through the same code path). Game.from_seed
  forwards the kwarg; CLI validates the id up front.
* **Determinism preserved**: Sprint-2 / Sprint-7 / Sprint-10
  byte-comparison contracts still hold because (a) `render_frame`
  emits no ANSI by default, (b) glyph variants are deterministic per
  `(master_seed, floor_index)`, (c) archetype-tagged prose selection
  uses the existing OfflineAdapter RNG. The integration tests in
  `tests/test_sprint11.py::test_c6_*` exercise this across two
  subprocesses.

## Commits

* `harness(contract): sprint-11 agreed` (pre-existing)
* `harness(sprint-11): archetypes module, glyph variants, palettes, prose tags, CLI flags [C1 C2 C3 C4 C5 C7 C10 C11 C12 C17]`
