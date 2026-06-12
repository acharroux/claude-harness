# Sprint 10 Generator Log

## Summary

Implemented F9 (Run Chronicle & Death Legends) in its Sprint-10 scope:
end-of-run Markdown chronicle with title, metadata block, notable-events
list, and epitaph blockquote. Added the `epitaph` canonical event type
and prose pool, the `Game.end_run` lifecycle hook, and the `--name` /
`--chronicle` CLI flags. Cross-run "death legends" deferred per contract
out-of-scope.

## Phase A: Contract Negotiation

No prior contract existed. Drafted `contract-proposal.json` with 18
testable criteria covering chronicle format (C1, C2, C18), the new
event type and pool (C3), the lifecycle hook (C4), event ordering (C5),
file writing (C6), default-path slug (C7), CLI integration (C8),
determinism (C9), epitaph rendering (C10), edge cases (C11), end-to-end
consistency (C12), regression (C13, C14), tests + docs + layering (C15,
C16, C17). Promoted the proposal to `contract.json` and committed as
`harness(contract): sprint-10 agreed`.

## Phase B: Implementation

### Step 1 — `epitaph` event type + prose pool entries

* `whisperdeep/events.py`: appended `EPITAPH = "epitaph"` to `EventType`
  (additive; the original nine names retain their positions).
* `whisperdeep/prose_pool.json`: added an `epitaph` key with 10 distinct
  short prose entries.

### Step 2 — `Game.end_run` lifecycle hook + chronicle metadata

* Added bookkeeping to `Game.__init__`: `_run_ended`, `max_floor_reached`,
  `seed`. `Game.from_seed` now stashes the master seed and adapter name
  on the Game (both the whisperer-on and whisperer-off paths) so the
  chronicle can read them without poking at the adapter or the World.
* `Game.descend` updates `max_floor_reached`.
* `Game.end_run(cause, summary)` publishes `run_ended` then `epitaph`,
  with each event stamped on a turn beyond the player's current turn so
  it doesn't collide with the Sprint-7 per-turn cap. Returns `True` once
  per Game; returns `False` thereafter (idempotent). Safe no-op with
  `whisperer=False` (returns `False`, never raises).

### Step 3 — `whisperdeep/chronicle.py`

* `build_chronicle(game, *, name, fixed_timestamp) -> str`: produces
  the four-section Markdown.
* `write_chronicle(game, path, *, name, fixed_timestamp) -> str`:
  writes UTF-8 to `path`, creating the parent directory if absent.
* `default_chronicle_path(game, name, *, root)`: returns
  `<root>/chronicles/seed-<N>-<slug>-floor-<F>.md`.
* `slugify_name`: lowercase, hyphenated, FS-safe; empty -> "unnamed".
* Layering is strict: stdlib + `typing` + `TYPE_CHECKING`-only references
  to `Game` / `Whisper`. No imports from `llm`, `render`, or `panel`.

### Step 4 — CLI integration

* Added `--name NAME`, `--chronicle PATH`,
  `--chronicle-fixed-timestamp ISO`, `--no-chronicle` to
  `whisperdeep/cli.py`.
* `_write_chronicle_if_requested(game, args)` calls `Game.end_run` and
  then `write_chronicle` after the headless and interactive run loops.

### Step 5 — Tests

* `tests/test_sprint10.py`: 34 distinct `test_*` functions covering
  every contract criterion (module imports, event-type additivity, pool
  size, `end_run` semantics, chronicle structure / metadata,
  chronological events, file IO, default path, CLI flags, determinism,
  epitaph rendering + determinism, edge cases incl. unicode / no-whisperer
  / no-end-run / long names, end-to-end whisper-vs-chronicle
  consistency, Sprint-7 / Sprint-8 regression spot checks, layering
  invariants).

### Step 6 — Documentation

* `docs/whisperdeep.md`: added Sprint-10 status banner at the top and a
  full **Chronicles (Sprint 10)** section with subsections for: format,
  the `epitaph` event type, the lifecycle hook, CLI flags, default path,
  determinism, and the explicitly-deferred cross-run-legends note.

## Phase C: Verification

* `pytest tests/`: 120 passed, 0 failed.
* `python -m whisperdeep --seed 1 --headless --name Mara --chronicle …`
  exits 0 and writes a chronicle whose four sections, metadata bullets,
  and epitaph blockquote match the contract.
* No network calls in any Sprint-10 test (verified by inspection;
  `subprocess` is used only to spawn the local CLI with API keys
  cleared).
* Sprint-1, Sprint-2, Sprint-7, Sprint-8 tests all still pass.

## Files Touched

* `whisperdeep/events.py` — added `EPITAPH`.
* `whisperdeep/prose_pool.json` — added 10 `epitaph` entries.
* `whisperdeep/game.py` — `seed` / `_adapter_name` / `max_floor_reached`
  bookkeeping; `end_run`.
* `whisperdeep/cli.py` — Sprint-10 chronicle flags + helper.
* `whisperdeep/chronicle.py` — new module.
* `tests/test_sprint10.py` — 34 new tests.
* `docs/whisperdeep.md` — Sprint-10 banner + Chronicles section.
* `harness-state/handoff.json`, `harness-state/progress.md` — updated.
