# Sprint 01 — Generator Log

## What was built

Ported `harness/lib/utils.sh` to Python and built the layer-1 test infrastructure.

### Files created

| File | Purpose |
| --- | --- |
| `harness/__init__.py` | Empty package marker |
| `harness/lib/__init__.py` | Empty package marker |
| `harness/lib/utils.py` | Python 3.8+ stdlib port of utils.sh |
| `tests/__init__.py` | Empty package marker |
| `tests/helpers/__init__.py` | Empty package marker |
| `tests/helpers/test_helper.py` | `HarnessTestCase` base + helpers |
| `tests/layer1/__init__.py` | Empty package marker |
| `tests/layer1/test_utils.py` | 35 unit tests (all 22 bats scenarios + bonus coverage) |
| `tests/run-all.py` | CLI test runner (`layer1`/`layer2`/`layer3`/`all`) |

### `harness/lib/utils.py`

Stdlib-only (`json`, `re`, `os`, `sys`, `pathlib`, `datetime`, `typing`).
Mirrors every function in `utils.sh`:

- `log_info` / `log_success` / `log_warn` / `log_error` / `log_phase` — write `[harness]` prefix + message to stderr; ANSI color emitted only when stderr is a TTY and `NO_COLOR` is unset.
- `HARNESS_STATE = "harness-state"`
- `sprint_pad(n)` — `f"{int(n):02d}"`
- `sprint_dir(n)` — forward-slash path `harness-state/sprints/sprint-NN`
- `slugify(s)` — lowercase, non-alphanumeric → `-`, collapse `-+`, strip leading/trailing `-`, truncate to 50 chars
- `json_read(file, field)` — jq-style accessor (`.a.b`, `.a[0]`, `.a["key"]`); empty string on missing file/field/parse error
- `file_exists(path)` — true only for non-empty regular file
- `init_harness_state(prompt, project_type)` — writes `config.json`, `cost-log.json`, `regression/registry.json`, `progress.md`
- `log_cost(role, sprint, output_json)` — appends invocation entry; defaults tokens to 0 on missing/invalid input
- `check_cost_cap()` — info notice, returns `None`
- `update_progress(sprint_num, status, attempt, merge_sha)` — appends sprint section
- `update_handoff(sprint_num, merge_sha, tag, harness_branch)` — initializes handoff if missing, dedupes `completedSprints`, sets git fields
- `update_regression_registry(sprint_num)` — writes `criteria` + `contractPath`; no-op when contract is missing

### `tests/helpers/test_helper.py`

`HarnessTestCase(unittest.TestCase)` with:

- `setUp()` — creates a `tempfile.mkdtemp()`, chdir into it, sets `MOCK_CLAUDE_*` env vars, exposes `self.test_temp_dir`, `self.fixture_dir`, `self.mock_claude_log`, `self.mock_claude_state_dir`, pre-creates `harness-state/sprints` and `harness-state/regression`.
- `tearDown()` — restore original cwd, remove temp dir.
- `install_fixture(name, dest)` — copies from `tests/helpers/fixtures/`, creating parent dirs.
- `init_test_repo()` — `git init -b main`, configure user, write `README.md`, commit.

### `tests/layer1/test_utils.py`

35 test methods (all 22 bats scenarios mapped 1-to-1, plus bonus coverage for `log_cost`, `update_progress`, `check_cost_cap`, and the five logging helpers under `NO_COLOR=1`). Every test runs inside an isolated `HarnessTestCase` temp directory.

Counts: 5 slugify, 2 sprint_pad, 2 sprint_dir, 4 json_read, 3 file_exists, 4 init_harness_state, 3 update_handoff, 2 update_regression_registry, 2 log_cost, 2 update_progress, 1 check_cost_cap, 5 log helpers = 35.

### `tests/run-all.py`

Usage: `python tests/run-all.py [layer1|layer2|layer3|all]`.

- `layer1` — `unittest.TestLoader.discover` under `tests/layer1/`, exit 0 on success.
- `layer2` / `layer3` — delegate to `tests/run-all.sh` via `bash` if available; otherwise print an informative skip message and return 0 (Sprint 5 wires this fully).
- Missing arg or unknown layer prints usage to stderr, exits 2.

## Verification

- `python tests/run-all.py layer1` from the repo root: **35 tests, OK, exit 0**.
- `python tests/run-all.py` (no arg): **exit 2**.
- `python tests/run-all.py bogus`: **exit 2**.
- `git status --porcelain` is identical before and after running the suite (no repo pollution).
- No backslash path literals in `harness/lib/utils.py` (only ANSI escapes `\033` and `\n`).
- `git diff` against parent shows zero `.sh`, `.ps1`, or `tests/helpers/fixtures/*` modifications.

## Cross-platform notes

- All filesystem ops go through `pathlib.Path` or `os.path.join`.
- `sprint_dir()` returns forward-slashes (matching the bash output and the JSON registry's `contractPath` field).
- `subprocess.run` is invoked with argument lists, not shell strings.
- ANSI colors are suppressed when stderr is not a TTY or when `NO_COLOR` is set.

## Notes / decisions

- `json_read` returns `""` for both missing files and missing fields. Bash `jq -r` on a missing field prints `null`; the contract explicitly accepts `""` or `"null"`. Returning `""` is cleaner for callers and is the documented Python convention here.
- `log_cost` reads/rewrites the entire JSON file rather than appending raw text — equivalent to bash's `jq` pipeline through a `mktemp` swap.
- `init_harness_state` writes JSON via `json.dumps(..., indent=2)`; the bash version uses literal heredocs. Both are byte-equivalent for parsing purposes; the layer-1 contract verifies via `json.load` semantics, not byte equality.
