# Sprint 12 Generator Log

**Sprint name**: Polish: Keybinds, Help, Sound, Leaderboard
**Features**: F12 (Keybinds & Help), F13 (Sound), F14 (Daily seed +
leaderboard + badges)
**Branch**: `harness/game-sprint-02-sprint-12`
**Result**: ready-for-eval (attempt 1)
**Tests**: 251/251 passing locally (174 prior + 77 new)

## What I built

Four new modules, all importing only stdlib + typing (with optional
`TYPE_CHECKING`-gated game/archetypes types where useful). None of
them import `whisperdeep.llm`, `whisperdeep.render`,
`whisperdeep.panel`, or `whisperdeep.whisperer`.

### `whisperdeep/keybinds.py` (C1, C2, C3, C4, C19)

* `COMMANDS` tuple of 16 canonical command names (the 13 mandated by
  the contract plus `redraw`, `summary`, `bindings`).
* `KeyBindings` dataclass with `mapping` dict, `bind`/`unbind`/
  `command_for`/`keys_for` methods, a `DEFAULTS_KB()` factory, and a
  `DEFAULTS` view.
* Defaults bind `h`/`j`/`k`/`l`/`y`/`u`/`b`/`n` to the eight movement
  directions, `<Up>`/`<Down>`/`<Left>`/`<Right>` ANSI escape sequences
  to the same, `.` to wait, `>`/`<` to descend/ascend, `q` to quit,
  `?` to help, `<Ctrl-L>` to redraw.
* `load_keybindings(path)` / `save_keybindings(kb, path)` round-trip a
  JSON object with a top-level `bindings` key. Missing path → defaults
  (no error). Malformed JSON → `ValueError`. Unknown command → clear
  `ValueError` naming the offending entry.
* `format_help_overlay(kb)` returns a plain-ASCII multi-line block
  with a `# Whisperdeep keybindings` header.

### `whisperdeep/audio.py` (C5, C6, C19)

* `AudioAdapter` runtime-checkable Protocol with `play(cue)` and
  `stop()`.
* `NullAudioAdapter` (silent default) and `LogAudioAdapter` (records
  cues to `self.cues`).
* `CUES` = the 9 mandated names; `EVENT_TO_CUE` mapping for at least
  `descended`, `run_started`, `run_ended`, `epitaph`, `first_sight`,
  `low_hp`, `killed_monster`, `found_item`.
* `make_adapter("null"|"log")` factory used by the CLI.
* No real backend (no `winsound`/`playsound`/`pyaudio`/`pygame`/
  `numpy`/`requests`/`urllib`).
* The module docstring explicitly documents that audio is OPT-IN and
  OFF by default.

### `whisperdeep/leaderboard.py` (C7, C8, C9, C10, C19)

* `score_for(game)` = `floors_reached * 100 + turns`.
* `read_leaderboard(path)` returns `[]` when the file is missing,
  malformed, or not a list — graceful degradation.
* `append_entry(path, entry)` reads, appends, sorts (score DESC then
  timestamp ASC), caps at `MAX_ENTRIES = 50`, writes back atomically
  (via `_atomic_write_json`), returns the new list.
* `build_entry(game, *, name, timestamp)` returns the dict with all
  required keys.
* `stable_seed_from_string(s)` is the SHA-256-based, process-stable,
  31-bit unsigned int hash. Empty strings raise `ValueError`. A
  subprocess test verifies cross-process stability (Python's salted
  `hash()` is NOT used).
* `daily_seed_for_date(date)` returns `int(YYYYMMDD)`.
* `format_top_n(entries, n=10)` is the pretty-printer for
  `--print-leaderboard`.

### `whisperdeep/summary.py` (C11, C12, C19)

* `build_badge(game, *, name=None)` returns the canonical line
  `WHISPERDEEP seed=<S> floors=<F> turns=<T> archetype=<A> v1 <CHK>`
  with `<CHK>` = first 6 hex chars of `sha256(prefix)` where `prefix`
  is everything up to and including `v1`. Reversible by any future
  verifier. Two runs with identical `(seed, floors, turns,
  archetype)` produce identical badges.
* `build_run_summary(game, *, name, fixed_timestamp=None,
  chronicle_path=None, leaderboard_rank=None)` returns a multi-line
  block starting with `BADGE_HEADER == "== Run Summary =="`. Includes
  name, seed, floors, turns, score, archetype, timestamp, optional
  chronicle path, optional rank, and the embedded badge line.
  Determinism preserved when `fixed_timestamp` is pinned.

### `whisperdeep/game.py` (C6)

Added an opt-in `audio: AudioAdapter | None` constructor parameter
(default `None`). When both `audio` and an event bus are wired,
`_wire_audio` subscribes a wildcard handler that resolves the cue via
`audio.EVENT_TO_CUE` and forwards it to `audio.play(cue)`. Audio
exceptions are swallowed defensively. `attach_audio()` is exposed for
post-construction wiring.

`Game.from_seed` accepts the new `audio=` kwarg and forwards it to the
constructor.

### `whisperdeep/cli.py` (C3, C4, C6, C9, C10, C11, C12, C13, C20)

A near-complete rewrite that adds the new flags listed in the
contract while preserving every Sprint-7/8/10/11 flag and behavior:

* `--keys PATH`, `--list-bindings`, `--print-help-overlay`
* `--audio CHOICE` (`null` (default) | `log`), `--dump-audio PATH`
* `--leaderboard PATH`, `--no-leaderboard`, `--print-leaderboard`,
  `--leaderboard-fixed-timestamp ISO`
* `--daily`, `--daily-date YYYY-MM-DD`, `--seed-string TEXT`
  (mutually exclusive with `--seed` and each other)
* `--print-badge`, `--no-badge`
* `--summary`, `--no-summary`

The interactive loop now consults a `KeyBindings` registry instead of
a hard-coded `moves` dict. A new public `dispatch_command(game, kb,
line) -> str` helper is the testable seam for `:`-prefixed commands
(`:quit`, `:help`, `:bindings`, `:descend`, `:ascend`, `:summary`,
`:bind <command> <key>`, `:unbind <key>`). Unknown commands print a
clear error and do NOT advance the turn.

End-of-run wiring (in this order):

1. `_dump_whispers_if_requested`
2. `_write_chronicle_if_requested` (calls `Game.end_run` first)
3. `_write_badge_if_requested`
4. `_append_leaderboard_if_requested` (returns the rank)
5. `_dump_audio_if_requested`
6. `_print_summary_if_requested`

### Tests — `tests/test_sprint12.py` (C17)

77 distinct `test_*` functions covering each criterion. Tests use
subprocess invocations of `python -m whisperdeep` to verify CLI
behavior, AST inspection to verify layering, deterministic
fixed-timestamp injections to verify byte-stability, and direct unit
calls to verify module APIs. No test imports `requests`, `httpx`,
`urllib.request`, `anthropic`, `openai`, `winsound`, `playsound`,
`pyaudio`, `pygame`, or `numpy`.

### Documentation (C18)

* `docs/whisperdeep.md` — prepended a Sprint-12 status banner that
  covers keybinds (with the default mapping table), audio (OPT-IN
  layer), leaderboard (file format, sorting, cap), daily/seed-string
  (algorithm + epoch), badge (canonical format), and run-summary
  (sections + determinism). The Sprint-10 deferral note about
  cross-run "death legends" is preserved. Sprints 3/4/5/6/9 are
  explicitly noted as deferred.
* `README.md` — appended a full **Whisperdeep** quickstart section
  with install / quickstart / controls / config (incl. `--keys` +
  `WHISPERDEEP_KEYS`) / daily / leaderboard / badge / project-status
  sub-sections.

## Verification highlights

* `python -m pytest tests/` → `251 passed`.
* `python -m whisperdeep --help` lists every Sprint-12 flag.
* `python -m whisperdeep --list-bindings` and
  `--print-help-overlay` work standalone.
* `python -m whisperdeep --seed 1 --headless --audio log
  --dump-audio /tmp/cues.json` records `["run_started"]`.
* Full end-to-end smoke test
  (`test_end_to_end_smoke_full_sprint12_surface`) produces every
  artifact: chronicle, badge sibling, leaderboard, cue dump,
  run-summary stdout block; re-running with a different seed
  accumulates the leaderboard.
* `EVENT_TYPES` and `TileKind` are byte-unchanged from Sprint 11.

## Known limitations / non-blocking notes

* Real audio backends are explicitly out of scope (per contract). The
  `AudioAdapter` Protocol is in place; future sprints can drop in a
  `winsound` / `playsound` / `terminal-bell` adapter without changing
  the public interface.
* Cross-run "death legends" (the Whisperer reading prior chronicles
  in a future run) remain deferred from Sprint 10.
* Sprints 3, 4, 5, 6, 9 remain not-in-tree; Sprint 12 deliberately
  avoids any dependency on them.

## Files changed

* New: `whisperdeep/keybinds.py`, `whisperdeep/audio.py`,
  `whisperdeep/leaderboard.py`, `whisperdeep/summary.py`,
  `tests/test_sprint12.py`.
* Modified: `whisperdeep/cli.py`, `whisperdeep/game.py`,
  `docs/whisperdeep.md`, `README.md`.

## Commits

* `harness(sprint-12): keybinds, audio, leaderboard, badge, summary
  modules + CLI [C1..C15, C19, C20]`
* (this log + status.json commit follows)
