# Sprint 02 Generator Log

## Summary

Ported the bash invoke wrapper to Python and the bash mock claude CLI to a
cross-platform Python implementation, plus a Windows .cmd shim. Added 22
unit tests covering all blocking criteria.

## Files created

- `harness/lib/invoke.py` -- Python port of `harness/lib/invoke.sh`.
  - `invoke_claude(agent, prompt, max_turns=50, mcp_config=None)` resolves
    `claude` via `shutil.which`, builds argv exactly like the bash version
    (including optional `--settings <HARNESS_ROOT>/.claude/settings.json`
    and `--mcp-config`), spawns via `subprocess.Popen`, streams stdout
    line-by-line, parses each line as JSON, and writes progress
    decorations to stderr. Tolerates malformed JSON. Returns the
    subprocess exit code.

- `tests/helpers/mock_claude.py` -- Python port of `tests/helpers/claude`.
  - Reads `MOCK_CLAUDE_FIXTURE_DIR` (required), `MOCK_CLAUDE_SCENARIO`
    (default `pass`), `MOCK_CLAUDE_LOG`, `MOCK_CLAUDE_STATE_DIR`
    (Windows-aware default).
  - Maintains call counters in state dir, writes log lines matching the
    bash format (`call=N agent=NAME scenario=SCEN prompt=...`).
  - Routes by agent + prompt the same way as the bash mock:
    planner copies product-spec + sprint-plan; generator handles
    `Propose contract` vs implementation (with `fail-generator-blocked`
    scenario writing `status-blocked`); evaluator handles `review
    contract` (with `revise-then-accept` alternation), `Evaluate sprint`,
    and `regression`.
  - Emits the same usage_json line on stdout and exits 0.

- `tests/helpers/claude.cmd` -- Windows PATH shim that invokes
  `python "%~dp0mock_claude.py" %*`.

- `tests/layer1/test_invoke.py` -- 22 unit tests:
  - argv construction (basic, with settings, with mcp_config, without
    settings, without mcp_config)
  - claude not on PATH raises FileNotFoundError mentioning claude
  - exit code propagation (0 and 7)
  - NDJSON streaming including malformed lines
  - tool_use progress decoration to stderr (Bash/Read examples)
  - cost line decoration to stderr
  - progress confined to stderr (not stdout)
  - mock_claude.py exists with python shebang
  - mock errors without fixture dir
  - planner / generator (propose, implement, blocked) routing parity
  - log file format and call-count files
  - usage_json on stdout
  - PATH shim resolves `claude`
  - claude.cmd exists and forwards `%*`

## Constraints honored

- Pure Python 3.8+ stdlib (json, os, sys, subprocess, shutil, pathlib,
  re, tempfile, typing, io, unittest).
- No `.sh`, `.bash`, `.ps1`, or `.bats` files modified or deleted.
  The existing `tests/helpers/claude` bash mock is untouched.
- The `.cmd` shim uses `%~dp0` so it works regardless of cwd.

## Test results

`python tests/run-all.py layer1` passes all 58 tests
(36 sprint-1 utils tests + 22 new invoke tests). No regressions.
