# Claude Harness Python Port — Product Specification

## 1. Product Overview

The Claude Harness is a multi-agent orchestrator (Planner / Generator / Evaluator) that drives Claude Code through structured sprint cycles to build working software. The current reference implementation is a set of bash scripts (`harness/orchestrate.sh`, `harness/lib/*.sh`) plus a `bats`-based test suite. This port produces a **functionally equivalent Python implementation** that runs natively on **Linux, macOS, and Windows** without bash, `jq`, or `bats`.

The Python harness is not a clever rewrite. It is a careful translation: byte-for-byte equivalent state files, identical git branch and tag names, the same exit-code contract from each phase, the same file-protocol semantics. A user who has run `bash harness/orchestrate.sh "..."` should be able to run `python harness/orchestrate.py "..."` and get the same artifacts in the same places. The bash scripts remain untouched and continue to work; the Python tree lives next to them as a true peer, not a wrapper.

This port matters because Windows users currently have to install Git Bash, `jq`, and `bats-core` before they can use the harness, and the bash scripts use POSIX-isms (process substitution, `mktemp -d`, ANSI escape codes through `echo -e`) that misbehave on PowerShell-native shells. By collapsing the dependency surface to **Python 3.8+ standard library** (plus optional `git` and `gh` CLIs, which the harness already requires in spirit), we make the harness installable in seconds on any modern developer machine, and we make it trivially embeddable in CI runners that already have Python.

## 2. Target Users

### Persona A — Windows-first developer using Claude Code
- **Goal:** Run `python harness/orchestrate.py "Build a kanban board"` and watch it work.
- **Pain points today:** Must install WSL, Git Bash, or MSYS2; `jq` is awkward to install on Windows; ANSI color codes get mangled in plain `cmd.exe`.
- **Wins:** Single `python -m pip`-free install (stdlib only), proper colored output via `colorama`-equivalent or smart TTY detection, paths handled with `pathlib`.

### Persona B — Harness contributor / maintainer
- **Goal:** Add a feature or fix a bug, run the test suite locally and in CI in seconds, with confidence the Python port mirrors bash behavior.
- **Pain points today:** `bats` failure output is cryptic; mocking `claude` requires shell tricks; debugging is print-style.
- **Wins:** Standard Python `unittest` (or `pytest`) runner, `unittest.mock`-based claude stand-in, proper tracebacks, runs identically on every OS in CI.

### Persona C — CI/automation engineer embedding the harness
- **Goal:** Drop the harness into a GitHub Action or container image with minimal layer bloat.
- **Pain points today:** `apt-get install -y bats-core jq git` on every CI run.
- **Wins:** `python:3.11-slim` with `git` and `gh` is enough — no extra apt packages.

## 3. Feature Specification

Features are organized by priority. Each maps cleanly to the bash module it replaces.

### P0 — Core Equivalence (must ship)

#### F1. Pure utilities (`harness/lib/utils.py`)
- **What:** `slugify`, `sprint_pad`, `sprint_dir`, `json_read`, `file_exists`, `init_harness_state`, `update_handoff`, `update_regression_registry`, `update_progress`, `log_cost`, `check_cost_cap`, plus colored logging helpers (`log_info`, `log_success`, `log_warn`, `log_error`, `log_phase`).
- **Why it matters:** Every other module depends on these. Behavior must match bash bit-for-bit (slug truncation at 50 chars, two-digit sprint padding, JSON read returning empty string on missing field/file).
- **Interactions:** Pure stdlib (`json`, `re`, `pathlib`, `datetime`, `sys`). Color output disabled when stdout/stderr is not a TTY or when `NO_COLOR` env is set; on Windows, enable ANSI via `os.system('')` or `colorama` if available, otherwise gracefully degrade.
- **Dependencies:** None.

#### F2. Claude invocation wrapper (`harness/lib/invoke.py`)
- **What:** `invoke_claude(agent, prompt, max_turns, mcp_config=None)` that builds the `claude -p ...` argv, streams NDJSON, and prints progress lines (`▸ tool_name: preview`, `Cost: $X`) to stderr in real time.
- **Why it matters:** The shell wrapper writes the entire output to a temp file and re-parses it; the Python version can stream line-by-line from `subprocess.Popen.stdout` and parse each NDJSON record as it arrives, giving more responsive UX. Must handle non-JSON lines gracefully.
- **Interactions:** Uses `subprocess.Popen` with `text=True`, no `shell=True`. Loads `--settings` from `HARNESS_ROOT/.claude/settings.json` if present. Returns exit code; raises only on truly unexpected errors. On Windows, locates `claude.exe` via `shutil.which`.
- **Dependencies:** F1.

#### F3. Git operations (`harness/lib/git.py`)
- **What:** `create_harness_branch`, `create_sprint_branch`, `merge_sprint`, `fail_sprint_attempt`, `commit_harness_state`, `create_pr`, `create_fix_pr`, `create_issue`, `generate_pr_body`. Each shells out to `git` (and `gh` where used) via `subprocess.run`.
- **Why it matters:** Branch and tag names are the stable contract with the rest of the system and with users inspecting `git log`. Must produce **exactly** the same names: `harness/<slug>`, `harness/<slug>-sprint-NN`, tags `harness/sprint-NN/pass`, `harness/sprint-NN/attempt-K`.
- **Interactions:** Uses `subprocess.run([...], check=False, capture_output=True, text=True)`. Detects missing `gh` and remotes the same way bash does, with the same warning messages.
- **Dependencies:** F1.

#### F4. Phase modules (`planner.py`, `contract.py`, `generator.py`, `evaluator.py`)
- **What:** `invoke_planner(mode)`, `negotiate_contract(sprint_num)`, `invoke_generator(sprint_num, attempt)`, `invoke_evaluator(sprint_num, attempt)`, `invoke_regression()`. Each builds the agent prompt, calls `invoke_claude`, validates the produced files, and returns a status int.
- **Why it matters:** This is the actual work. The output-validation logic (e.g., evaluator tolerating `.overallResult / .result / .verdict`, contract review tolerating `accepted/accept/approved/approve`) must be ported verbatim — this tolerance is load-bearing because real Claude varies.
- **Interactions:** Read JSON via `json_read`; build prompts as f-strings; same `MAX_CONTRACT_ROUNDS` accept-on-max-rounds fallback as bash.
- **Dependencies:** F1, F2.

#### F5. Main orchestrator (`harness/orchestrate.py`)
- **What:** Argparse-based CLI with the same flags as `orchestrate.sh`: positional prompt, `--extend`, `--fix`, `--refactor`, `--regression`, `--resume`, `--project-type`, `--context-strategy`, `--model`, `--max-cost`, `--from-sprint`, `--dry-run`. Implements all six modes (`new`, `extend`, `fix`, `refactor`, `resume`, `regression`).
- **Why it matters:** This is the user-facing entry point. It must accept the same flags in the same forms (long-form only, since bash doesn't use short flags here).
- **Interactions:** Stages `.claude/agents` and `.claude/skills` from `HARNESS_ROOT` to cwd just like bash. Adds harness entries to `.gitignore` if missing. Auto-init git repo if cwd isn't one (mode=new only). Runs the sprint loop with the same retry semantics (`MAX_SPRINT_ATTEMPTS`).
- **Dependencies:** F1, F2, F3, F4.

#### F6. Python test infrastructure (`tests/run-all.py`, `tests/helpers/`, `tests/layer1/test_*.py`)
- **What:** A `unittest`-based test runner with three layers mirroring the bats suite. Layer 1 covers utils, git, planner, contract, generator, evaluator, hooks (with mocked claude). Layer 2 calls the smoke-test shell script. Layer 3 calls the meta-test shell script. The runner accepts `layer1|layer2|layer3|all` like `run-all.sh`.
- **Why it matters:** Without an equivalent test layer, the port can't be trusted. Every bats scenario must have a Python equivalent assertion.
- **Key components:**
  - `tests/helpers/mock_claude.py` — a Python script with a shebang that emulates the existing bash `tests/helpers/claude` mock (same fixtures, same env vars: `MOCK_CLAUDE_FIXTURE_DIR`, `MOCK_CLAUDE_SCENARIO`, `MOCK_CLAUDE_LOG`, `MOCK_CLAUDE_STATE_DIR`).
  - `tests/helpers/test_helper.py` — a `HarnessTestCase` base class with `setUp`/`tearDown` that creates an isolated temp dir, sets env vars, prepends `tests/helpers/` to `PATH`, and exposes `init_test_repo()`, `install_fixture()`, `mock_call_count()`.
  - On Windows, the mock claude is invoked as `python tests/helpers/mock_claude.py` (PATH-shimmed via a `claude.cmd` or `claude.bat` launcher). The bats mock continues to work for bash users.
- **Dependencies:** F1–F5.

### P1 — Polish (ship in Sprint 5)

#### F7. Hooks compatibility
- **What:** The existing `harness/hooks/*.sh` scripts continue to work unchanged (they are invoked by Claude Code's settings.json, not by orchestrator code). Document that hooks remain bash-only for now; cross-platform hooks are out of scope.
- **Why:** Hooks fire from Claude Code itself. Re-implementing them in Python is a larger change in `.claude/settings.json` and is explicitly out of scope per project constraints (no .ps1/.sh modifications).

#### F8. Skill update for `harness-test`
- **What:** Minimally update `.claude/skills/harness-test/SKILL.md` to mention that Python tests can be run with `python tests/run-all.py [layer]` in addition to `bash tests/run-all.sh [layer]`. The bash command stays as the default; Python is offered as an alternative.
- **Why:** This is the only skill that directly invokes the test infrastructure. Other skills (`harness-run`, `harness-sprint`, etc.) call the bash orchestrator; they remain untouched per constraints. Users who want the Python orchestrator invoke it directly.

#### F9. Clear cross-platform UX
- **What:** Friendly errors when `git` or `claude` is not on PATH. When `gh` is missing, fall back gracefully (same as bash). Detect Windows and adjust paths/quoting where needed.
- **Why:** First-run errors set the tone for the whole tool.

### Out of Scope (explicitly)

- Replacing or modifying any `.sh` or `.ps1` script.
- Reimplementing hooks in Python.
- Replacing the agent definitions or skills (other than the minimal `harness-test` SKILL.md update).
- Adding new orchestrator features not present in the bash version.
- Migrating away from `git` or `gh` CLIs to a pure Python git library.

## 4. Visual Design Language

This is a CLI tool, so the "visual design" is terminal output. Principles:

- **Same vocabulary as bash version.** The bracketed `[harness]` prefix, the box-drawn phase headers (`━━━━━━━━`), the `▸` tool-call markers — all preserved. Users switching between bash and Python should not feel they're using a different tool.
- **Color discipline.** Blue for info, green for success, yellow for warn, red for error, cyan for phase headers, dim gray for tool-call previews. Disable colors when output is piped or `NO_COLOR` is set.
- **Honest progress.** Stream tool-call previews as they happen; never buffer the whole agent output silently and then dump it. The bash version is good at this; the Python version should be at least as responsive.
- **No emoji.** The bash logs use plain ASCII glyphs; keep it that way for terminal compatibility on Windows.
- **Quiet success, loud failure.** Successful sprints log one line; failures log the eval-report summary with the first 300 chars inline.

## 5. Technical Architecture (High-Level)

### Stack
- **Language:** Python 3.8+ (target the lowest version still on supported LTS distros).
- **Standard library only:** `argparse`, `json`, `subprocess`, `pathlib`, `re`, `os`, `sys`, `shutil`, `datetime`, `tempfile`, `unittest`.
- **External binaries (runtime):** `git` (required), `gh` (optional, for PRs/issues), `claude` (required for real runs; mocked in tests).
- **No third-party Python packages.** No `pip install` required.

### Data model
The harness operates on the existing `harness-state/` filesystem layout — this is the contract:

```
harness-state/
  config.json                  ← project settings
  product-spec.md              ← planner output
  sprint-plan.json             ← sprint decomposition
  handoff.json                 ← state passed across context resets
  progress.md                  ← narrative log
  cost-log.json                ← invocation log
  regression/registry.json     ← blocking criteria registry
  sprints/sprint-NN/
    contract-proposal.json
    contract-review.json
    contract.json
    status.json
    generator-log.md
    eval-report.json
```

The Python code reads/writes these files using `json.load/dump` (with `indent=2` to match bash's `jq` output style where possible). Path handling uses `pathlib.Path` exclusively; no string concatenation.

### Module relationships
```
orchestrate.py
  ├── lib/utils.py        (no deps)
  ├── lib/invoke.py       (utils)
  ├── lib/git.py          (utils)
  ├── lib/planner.py      (utils, invoke)
  ├── lib/contract.py     (utils, invoke)
  ├── lib/generator.py    (utils, invoke)
  └── lib/evaluator.py    (utils, invoke)
```

`lib/__init__.py` is empty. `harness/__init__.py` is empty. Modules are imported via `from harness.lib import utils` style; `orchestrate.py` is invoked as `python harness/orchestrate.py` or `python -m harness.orchestrate`.

### Testing architecture
```
tests/
  run-all.py                ← CLI: layer1 | layer2 | layer3 | all
  helpers/
    test_helper.py          ← HarnessTestCase base + helpers
    mock_claude.py          ← Python port of tests/helpers/claude
    claude.cmd / claude     ← thin shim that execs mock_claude.py
    fixtures/               ← reuse existing fixture files unchanged
  layer1/
    test_utils.py
    test_git.py
    test_invoke.py
    test_planner.py
    test_contract.py
    test_generator.py
    test_evaluator.py
    test_hooks.py           ← validates the existing bash hooks (skipped on no-bash)
  layer2/  (delegates to existing smoke-test.sh)
  layer3/  (delegates to existing meta-test.sh)
```

## 6. Sprint Decomposition

Five sprints, each independently testable. Order strictly enforces dependency: utilities first, then the wrapper that depends on utilities, then phases, then orchestration.

### Sprint 1 — Core Utilities + Test Infrastructure
- Build `harness/lib/utils.py` with all 11 utility functions matching bash semantics exactly.
- Build `tests/helpers/test_helper.py` (HarnessTestCase) and `tests/run-all.py` runner skeleton.
- Build `tests/layer1/test_utils.py` covering every bats test in `test-utils.bats`.
- Verify by running `python tests/run-all.py layer1` and seeing only `test_utils` tests collected and passing.

### Sprint 2 — Claude Invocation Wrapper
- Build `harness/lib/invoke.py` with streaming NDJSON parser and progress display.
- Build `tests/helpers/mock_claude.py` (Python port of bash mock) and the PATH shim (`tests/helpers/claude.cmd` on Windows, executable script on POSIX).
- Build `tests/layer1/test_invoke.py` covering the wrapper: it resolves `claude`, builds the right argv, parses the NDJSON stream, and propagates exit codes.
- Verify mock claude is interchangeable with the bash mock by running both and diffing fixture output.

### Sprint 3 — Git Operations
- Build `harness/lib/git.py` with all branch/merge/tag/PR functions.
- Build `tests/layer1/test_git.py` covering every scenario in `test-git.bats` (branch creation, sprint branch cleanup, merge produces tag, fail-attempt deletes branch, PR body generation).
- All tests run in isolated temp git repos created in `setUp`.

### Sprint 4 — Phase Modules (Planner, Contract, Generator, Evaluator)
- Build `harness/lib/planner.py`, `contract.py`, `generator.py`, `evaluator.py`.
- Port the tolerance logic for varied Claude output exactly (field name aliases, decision-string variants, accept-on-max-rounds fallback).
- Build `tests/layer1/test_planner.py`, `test_contract.py`, `test_generator.py`, `test_evaluator.py` covering every bats scenario.
- Cross-check: every numbered test in the bats files has a corresponding `test_*` method.

### Sprint 5 — Orchestrator + Integration + Skill Update
- Build `harness/orchestrate.py` with argparse, all six modes, the `.claude/` staging logic, and the sprint loop.
- Build `tests/layer1/test_hooks.py` (validates the existing bash hooks via subprocess; skip cleanly on Windows-without-bash with a clear message).
- Build a Python integration test that runs the full pipeline against the mock claude end-to-end (equivalent to a layer-1.5 smoke test that doesn't cost API usage).
- Wire `tests/run-all.py` to delegate `layer2` and `layer3` to the existing shell scripts unchanged.
- Minimally update `.claude/skills/harness-test/SKILL.md` to document `python tests/run-all.py` as an alternative to `bash tests/run-all.sh`.
- Verify cross-platform: test runs cleanly on Windows (cmd.exe and PowerShell), macOS, and Linux.

Each sprint is one focused session, complexity medium except Sprint 4 (high — four modules with subtle tolerance logic) and Sprint 1 (low–medium; foundational but mostly mechanical).
