# Native PowerShell ports of the harness shell scripts

Adds side-by-side `.ps1` equivalents of every user-invokable `.sh` in the harness so it can be driven from native Windows PowerShell without WSL or any POSIX shell.

## What changed

11 new PowerShell scripts, side-by-side with their `.sh` counterparts (same basename, `.ps1` extension):

| `.sh` | `.ps1` |
|---|---|
| `harness/orchestrate.sh` | `harness/orchestrate.ps1` |
| `harness/lib/utils.sh` | `harness/lib/utils.ps1` |
| `harness/lib/git.sh` | `harness/lib/git.ps1` |
| `harness/lib/invoke.sh` | `harness/lib/invoke.ps1` |
| `harness/lib/planner.sh` | `harness/lib/planner.ps1` |
| `harness/lib/generator.sh` | `harness/lib/generator.ps1` |
| `harness/lib/evaluator.sh` | `harness/lib/evaluator.ps1` |
| `harness/lib/contract.sh` | `harness/lib/contract.ps1` |
| `tests/run-all.sh` | `tests/run-all.ps1` |
| `tests/layer2/smoke-test.sh` | `tests/layer2/smoke-test.ps1` |
| `tests/layer3/meta-test.sh` | `tests/layer3/meta-test.ps1` |

No `.sh` file was modified. Hooks under `harness/hooks/` are intentionally excluded — Claude Code executes hooks in its own runtime where bash already works regardless of host OS.

## Cross-cutting design

- **Runtime target:** Windows PowerShell 5.1 AND PowerShell 7+. PS 5.1 ships with every Windows 10/11, so no install is required to drive the harness on Windows.
- **External tools used directly:** `jq`, `git`, `gh`, `claude`, `node`, `npm`, `bats`. The `.sh` scripts' `jq` pipelines are preserved verbatim — keeps semantics identical and minimizes translation risk.
- **Forbidden in ports:** `bash`, `sh`, `wsl`, `sed`, `awk`, `grep`, `find`, `realpath`, `mktemp`, `dirname`, `basename`, `tr`, `cut`, `xargs`. AST-level scan confirms zero bare invocations across all 11 files.
- **Encoding:** all UTF-8 writes go through `Write-Utf8NoBom` (in `utils.ps1`, implemented via `[System.IO.File]::WriteAllText` + `UTF8Encoding($false)`). Avoids the PS 5.1 / PS 7 split where `Set-Content -Encoding utf8NoBOM` only exists on 7+.
- **Sourcing:** `.ps1` libs dot-source siblings via `. (Join-Path $PSScriptRoot 'utils.ps1')` — mirrors the `source harness/lib/utils.sh` pattern.
- **CLI parity:** every flag, positional arg, env var, exit code, and stdout/stderr split matches the `.sh` original. `--help` / `-h` added everywhere it was missing.
- **Git/file-protocol parity:** branch names (`harness/sprint-NN`), tag names (`harness/plan`, `harness/sprint-NN/pass`, `harness/sprint-NN/attempt-K`), commit messages (`harness(sprint-NN): ... [C-ID]` etc.), and `harness-state/` JSON shapes are bit-identical.

## Sprint summary

| Sprint | Title | Verdict | Files |
|---|---|---|---|
| 01 | Foundation libs | **PASS** (after one fix for jq-splat blocker in `Update-RegressionRegistry`; root cause: PS 5.1 strips embedded `"` from native-command argv. Fix: `--slurpfile` over `--argjson`. Regression test included.) | utils.ps1, git.ps1, invoke.ps1 |
| 02 | Agent libs | **PASS** | planner.ps1, generator.ps1, evaluator.ps1, contract.ps1 |
| 03 | Orchestrator | **PASS** (20/20 criteria) | orchestrate.ps1 |
| 04 | Test runners | **PASS** (13/13 criteria) | run-all.ps1, smoke-test.ps1, meta-test.ps1 |

Per-sprint contracts, generator logs, and evaluator reports live under `harness-state/sprints/sprint-NN/`.

## Verification done

For each `.ps1`:
1. `[System.Management.Automation.Language.Parser]::ParseFile` — zero parse errors.
2. AST-aware forbidden-token scan — zero hits across all 11 files.
3. Full lib chain dot-sources cleanly under PS 5.1 (`utils → invoke → git → planner → contract → generator → evaluator`).
4. `--help` exits 0 with usage on every script that accepts user invocation.
5. `Write-Utf8NoBom` verified to produce no BOM (read-back byte check).
6. `Invoke-NativeCommand` verified to throw on non-zero `$LASTEXITCODE`.
7. `Update-RegressionRegistry` verified end-to-end with a 3-criteria fixture.

End-to-end harness-runs against real `claude` were intentionally not executed in CI for this port — that's what `tests/layer2/smoke-test.ps1` and `tests/layer3/meta-test.ps1` exist for, gated behind `HARNESS_SMOKE_TEST=1` / `HARNESS_META_TEST=1` to avoid burning Claude usage on PRs.

## How to use on Windows

```powershell
# One-shot full pipeline:
powershell -NoProfile -File harness\orchestrate.ps1 "Build a ..."

# Individual modes mirror the .sh:
powershell -NoProfile -File harness\orchestrate.ps1 --extend "Add login screen"
powershell -NoProfile -File harness\orchestrate.ps1 --resume --from-sprint 3

# Tests:
powershell -NoProfile -File tests\run-all.ps1 layer1
$env:HARNESS_SMOKE_TEST = "1"
powershell -NoProfile -File tests\run-all.ps1 layer2
```

## Out of scope

- `harness/hooks/*.sh` — Claude runs hooks in its own bash-capable env; no Windows-side need to port.
- `tests/layer1/*.bats` — Layer 1 unit tests stay in `bats`; the runners (`run-all.ps1`) invoke `bats` directly.
- WSL / cross-shell shims, MSYS workarounds — none needed.

🤖 Generated by the harness Planner-Generator-Evaluator pipeline.
