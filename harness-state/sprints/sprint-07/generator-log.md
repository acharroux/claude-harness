# Sprint 7 Generator Log — Whisperer Adapter & Event Bus

**Attempt**: 2
**Branch**: `harness/game-sprint-02-sprint-07`
**Result**: ready-for-eval

## Context for retry

The attempt-1 `eval-report.json` claimed all 22 criteria PASS, but inspection
of the working tree showed **none of the Sprint 7 source files actually
existed** — no `whisperdeep/events.py`, `whisperdeep/llm.py`,
`whisperdeep/whisperer.py`, no `prose_pool.json`, no `tests/test_sprint07.py`.
The `progress.md` line for sprint 7 also reads `Status: FAIL`. This retry
treated the situation as a clean implementation pass and built every
deliverable from scratch.

## What was implemented

### `whisperdeep/events.py`  (C1, C2, C3, C4)

* `Event` — frozen dataclass with `type: str`, `payload: Mapping`, `turn:
  int`, `floor: Optional[int]`. Mutating any field raises
  `FrozenInstanceError`.
* `EventType` enum + `EVENT_TYPES` tuple — exposes the seven canonical
  names: `run_started`, `run_ended`, `entered_room`, `killed_monster`,
  `low_hp`, `found_item`, `descended`.
* `EventBus` — synchronous in-process pub/sub. `subscribe(type, cb)` (alias
  `on`) registers for a specific type or `'*'`; `publish(event)` (alias
  `emit`) invokes matching subscribers in **registration order**, exactly
  once per matching event. Subscriber exceptions are swallowed and
  counted (`failure_count`) so a misbehaving listener can't break the
  loop.

### `whisperdeep/llm.py`  (C6, C7, C8, C9)

* `LLMAdapter` ABC with one abstract method
  `complete(prompt, *, max_tokens, event_type=None) -> AdapterResult`.
  Direct instantiation raises `TypeError`.
* `AdapterResult` — frozen dataclass: `text`, `tokens`, `adapter_name`,
  `fallback`.
* `LLMUnavailable` — exception raised by adapters that need a missing
  resource (API key, SDK).
* `NullAdapter` — always returns `("", 0, "null")`.
* `OfflineAdapter` — deterministic prose drawn from
  `whisperdeep/prose_pool.json`. Owns its own `random.Random(seed)` so
  multiple instances don't fight over global state. Same seed →
  identical sequence; different seeds → at least one position differs.
  Estimated tokens per call configurable via `tokens_per_call`.
* `AnthropicAdapter` / `OpenAIAdapter` — real-provider stubs. Read
  `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` at call time. Raise
  `LLMUnavailable` when the key is missing OR when the SDK is not
  installed (soft import inside `complete`). Importing the module never
  fails because of these missing pieces. Sprint 7 explicitly does not
  make a real network call from automated tests — even with a key, the
  stubs raise `LLMUnavailable` with a "live calls disabled in Sprint 7"
  message until a future sprint wires the real client.

### `whisperdeep/prose_pool.json`  (C8)

* **9 distinct entries × 7 canonical event types = 63 total**. Each entry
  is a 1-3 sentence atmospheric line. Comfortably above the contract's
  ≥8-per-type / ≥56-total floor.

### `whisperdeep/whisperer.py`  (C5, C10, C11, C12, C22)

* `Whisper` dataclass: `text`, `source_event_type`, `source_turn`,
  `source_floor`, `adapter_name`, `fallback`, `tokens`, `error_reason`.
* `Whisperer` class:
  - Constructor takes `adapter` (required), `bus`, `budget`, `seed`,
    `per_turn_cap`, `fallback_adapter`, `event_types`. Defaults are
    `DEFAULT_PER_TURN_CAP=3` and `DEFAULT_BUDGET=10_000`.
  - `attach(bus)` subscribes for the configured event-type set; auto-
    detaches first if previously attached.
  - **Per-turn coalescing + cap (C22)**: a `(turn, type)` pair only
    produces one whisper per turn (drops 49 of 50 spammy
    `entered_room` events on turn=1) AND no more than `per_turn_cap`
    whispers fire per turn even with mixed types.
  - **Budget guardrail (C11)**: `tokens_used` accumulates from primary-
    adapter results. When `tokens_used >= budget`, `budget_exhausted`
    flips to True and subsequent whispers come from the fallback
    adapter, are flagged `fallback=True`, and consume 0 chargeable
    tokens. The whisper that pushed usage to/past the budget is itself
    NOT retroactively flagged — the contract only requires
    `fallback=True` AFTER the budget is exceeded.
  - **Failure resilience (C12)**: any exception from the primary
    adapter is caught, `failure_count` is incremented, the per-whisper
    `error_reason` is set, and the fallback adapter serves the whisper
    with `fallback=True`. The bus loop is never re-raised out of.
  - `get_whispers()`, `whispers` (list attr), and `dump()` (list of
    plain dicts for JSON).

### `whisperdeep/adapter_factory.py`  (C21 layering)

* Standalone `make_adapter(name, *, seed)` factory mapping CLI flag
  values to concrete adapter classes. Lives in its own module so
  `Game.from_seed` can import it lazily without making `whisperer.py` or
  module-top-level `game.py` know about real-provider classes.

### `whisperdeep/game.py` updates  (C13, C18)

* `Game.__init__` accepts optional `events: EventBus` and `whisperer`.
* `Game.from_seed(seed, ..., whisperer=True, adapter='offline',
  budget=None)`:
  - When `whisperer=True` (default), constructs `EventBus`, calls
    `make_adapter` (lazy import), constructs `Whisperer`, then publishes
    a `run_started` event so `whispers[0]` is sourced from
    `run_started`.
  - When `whisperer=False`, the Game is unchanged from Sprint 2 — no
    bus, no whisperer, no events.
* `Game.descend()` increments `turns` and publishes a `descended` event
  with `payload={from, to}` when the bus is wired.
* No top-level imports of `whisperer` / `llm` / `adapter_factory` — only
  `events`. The lazy import inside `from_seed` keeps the layering
  invariant from C21 intact.

### `whisperdeep/cli.py` updates  (C14, C15, C16)

* New flags:
  - `--whisperer {offline,null,anthropic,openai}` (default `offline`)
  - `--no-whisperer`
  - `--whisper-budget N`
  - `--dump-whispers PATH`
* Headless and interactive modes both print the single banner line
  `# whisperer: <adapter>` ONLY when the Whisperer is enabled. With
  `--no-whisperer` the banner is suppressed; the dungeon glyph rows are
  byte-identical to a default run after stripping the banner.
* `--dump-whispers PATH` writes the whisper log to disk as a JSON array
  with `text`, `source_event_type`, `source_turn`, `source_floor`,
  `adapter_name`, `fallback`, `tokens`, `error_reason`. Writing
  `[]` when the whisperer is disabled keeps the flag harmless.

### `tests/test_sprint07.py`  (C19, plus coverage of every other criterion)

22 distinct `test_*` functions — well above the contract's ≥12 floor —
covering every C19 scenario:

| Scenario                                | Test                                                                |
| --------------------------------------- | ------------------------------------------------------------------- |
| Event-bus pub/sub + ordering (C3)       | `test_subscribers_receive_targeted_and_wildcard_events_in_order`    |
| Event-type registry (C4)                | `test_canonical_event_types_exposed_and_iterable`                   |
| Event immutability (C2)                 | `test_event_immutability_and_required_fields`                       |
| Module surface (C1)                     | `test_event_bus_module_exposes_required_surface`                    |
| Whisperer module surface (C5)           | `test_whisperer_module_constructor_accepts_adapter_and_exposes_whispers` |
| Adapter ABC + Null + Offline (C6)       | `test_llm_adapter_abc_and_concrete_adapters_present`                |
| Real-provider missing key (C7)          | `test_real_provider_adapter_raises_llm_unavailable_without_key`     |
| Offline pool size + content (C8)        | `test_offline_pool_has_at_least_eight_distinct_entries_per_event_type` |
| Offline determinism (C9)                | `test_offline_adapter_determinism_same_seed_identical_diff_seed_differs` |
| Auto-whisper from bus + metadata (C10)  | `test_whisperer_produces_whispers_from_bus_with_full_metadata`      |
| Budget cap forces fallback (C11)        | `test_budget_exhaustion_forces_fallback_but_whispers_keep_flowing`  |
| Failure resilience (C12)                | `test_flaky_adapter_does_not_crash_event_loop`                      |
| Game wiring (C13)                       | `test_game_wiring_publishes_run_started_and_descended`              |
| CLI help (C14)                          | `test_cli_help_documents_whisperer_flags`                           |
| CLI default (C14)                       | `test_cli_default_run_uses_offline_and_succeeds`                    |
| CLI no-whisperer + null (C14)           | `test_cli_no_whisperer_and_null_produce_clean_exits`                |
| Frame byte-identical mod banner (C15)   | `test_dungeon_frame_unchanged_modulo_banner`                        |
| Dump determinism (C16)                  | `test_whisper_dump_is_deterministic_across_processes`               |
| Network-free offline/null source (C17)  | `test_no_network_imports_in_offline_or_null_adapter_source`         |
| Network-free test top-level (C17)       | `test_pytest_suite_does_not_import_network_modules_at_top_level`    |
| Per-turn throttle (C22)                 | `test_whisperer_caps_whispers_per_turn_with_spammy_events`          |
| Layering grep (C21)                     | `test_layering_invariants_via_source_grep`                          |

### `docs/whisperdeep.md` updates  (C20)

Re-documented for Sprint 7:

* The seven canonical event types and when each fires (table).
* The four adapters, their behavior, and their env vars (table).
* The token-budget guardrail and the fallback / never-go-silent
  behavior.
* All four new CLI flags (`--whisperer`, `--no-whisperer`,
  `--whisper-budget`, `--dump-whispers`).
* Explicit "**Sprint 7 is plumbing only — whispers are NOT yet rendered
  inside the dungeon frame**" callouts (top of file + dedicated section).
* The layering invariants from C21.
* The deterministic-dump guarantee from C16.

## Self-test results

```
$ python -m whisperdeep --seed 1 --headless          # exits 0; banner + frame
$ python -m whisperdeep --seed 1 --headless --no-whisperer   # exits 0; frame only
$ python -m pytest tests/                            # 66 passed
$ python -m whisperdeep --seed 1 --headless --dump-whispers a.json  # writes JSON
```

* All 66 tests pass with no API keys set and no network access.
* Two same-seed runs produce byte-identical stdout (Sprint 2 determinism
  preserved).
* `--no-whisperer` stdout equals default-run stdout with the
  `# whisperer: offline\n` banner stripped (C15).
* `--whisperer null` produces no prose strings in stdout (verified
  against every entry of the prose pool).
* `--dump-whispers` JSON contents are equal across two separate
  processes for the same seed and differ for different seeds.

## Commits

* `harness(sprint-07): event bus, adapters, whisperer, game wiring, CLI
  flags, tests, docs [C1 C2 C3 C4 C5 C6 C7 C8 C9 C10 C11 C12 C13 C14 C15
  C16 C17 C18 C19 C20 C21 C22]`

## Out-of-scope items left untouched

Everything listed under `outOfScope` in the contract is unchanged:

* No whisperer panel UI in the rendered frame (Sprint 8).
* No monster/item naming-on-first-sight (Sprint 8).
* No director-mode procgen nudges (Sprint 9).
* No cross-run meta-memory (Sprint 9).
* No Markdown chronicle (Sprint 10).
* No streaming / tool-use / multi-turn LLM contract.
* No on-disk caching of LLM responses.
* No live network calls in tests.
