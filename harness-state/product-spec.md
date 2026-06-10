# Product Spec: Native PowerShell Port of Harness Shell Scripts

## Goal

Produce native PowerShell 7+ (`.ps1`) equivalents of every user-invokable `.sh` script in this repository so the Planner-Generator-Evaluator harness becomes fully usable on native Windows PowerShell without WSL or any POSIX shell. Each `.ps1` lives **side-by-side** with its `.sh` counterpart, shares the same base name, and provides functionally equivalent observable behavior.

## Scope clarifications (2026-06-10)

- **Hooks are out of scope**. Files under `harness/hooks/*.sh` are executed by Claude Code in its own runtime; bash works there regardless of host OS. They get no `.ps1` sibling.
- **External tools assumed installed on Windows**: `jq`, `git`, `gh`, `claude`, `node`, `npm`, `bats` (bats install may be flaky — handle it the same way the .sh does, with the same error message; do not work around bats issues in the port). Calling these from PowerShell is **allowed and encouraged**. `jq` is the workhorse of the .sh scripts and porting its pipelines verbatim into PowerShell `& jq ...` calls is fine — it preserves correctness for free.
- **Forbidden in the .ps1 ports**: `bash`, `sh`, `wsl`, and POSIX-only tools the user did not say are installed (`sed`, `awk`, `grep` as a bare command, `find`, `realpath`, `mktemp`, `dirname`, `basename`, `tr`, `cut`, `xargs`, `tee` as a bare command). Replace these with PowerShell-native equivalents (`Select-String`, `Get-ChildItem`, `Resolve-Path`, `Split-Path`, `Tee-Object`, `New-TemporaryFile`).

## Source inventory in scope (11 files, ~1640 lines)

| Path | Lines | Role |
|---|---|---|
| `harness/orchestrate.sh` | 521 | Top-level driver: orchestrates planner → contract loop → generator → evaluator per sprint |
| `harness/lib/utils.sh` | 243 | JSON helpers, logging, path resolution, cost tracking, status writes |
| `harness/lib/git.sh` | 286 | Branch/tag/commit/PR helpers around `git` and `gh` |
| `harness/lib/invoke.sh` | 84 | Wraps `claude` CLI invocations with structured I/O and cost capture |
| `harness/lib/planner.sh` | 60 | Calls planner agent; writes product-spec + sprint-plan |
| `harness/lib/generator.sh` | 55 | Calls generator agent; writes implementation log |
| `harness/lib/evaluator.sh` | 93 | Calls evaluator agent; writes eval-report.json |
| `harness/lib/contract.sh` | 83 | Negotiation loop generator↔evaluator, writes sprint-contract.json |
| `tests/run-all.sh` | 84 | Top test runner — fans out across layer1/2/3 |
| `tests/layer2/smoke-test.sh` | 107 | Real-Claude smoke test |
| `tests/layer3/meta-test.sh` | 138 | Meta self-test (harness builds its own test suite) |

Hooks (`harness/hooks/*.sh`, 4 files, ~348 lines) are out of scope.

## Cross-cutting requirements every `.ps1` must satisfy

### Runtime
- **Primary target: PowerShell 7+ (`pwsh`)**. Each script begins with `#Requires -Version 7.0`, then `Set-StrictMode -Version Latest`, then `$ErrorActionPreference = 'Stop'`.
- Each `.ps1` runnable as `pwsh -NoProfile -File <path> [args...]`. No `Set-ExecutionPolicy` change required from the user.

### External-tool policy
- **Allowed and expected**: `jq`, `git`, `gh`, `claude`, `node`, `npm`, `bats`. Use `& jq ...`, `& git ...`, etc. directly. If a `.sh` script pipes JSON through several `jq` filters in a row, the `.ps1` may either keep the pipeline (`(& jq -r '.foo' $f) | & jq ...`) or read once with `ConvertFrom-Json` and project — pick whichever stays closest to the source. **Default: keep the jq pipeline.** It minimizes translation risk.
- **Forbidden**: `bash`, `sh`, `wsl`, `sed`, `awk`, `grep`, `find`, `realpath`, `mktemp`, `dirname`, `basename`, `tr`, `cut`, `xargs`, plus `cat`/`tee` as bare commands. Replace with PowerShell built-ins.

### Argument and I/O contract parity
- **Same CLI flags, positional args, env-var inputs.** A user who reads README's `bash harness/orchestrate.sh "..."` example must be able to type `pwsh -NoProfile -File harness/orchestrate.ps1 "..."` and get the same effect.
- **Same exit codes.** 0 = success; non-zero codes used by `.sh` are preserved.
- **Same stdout/stderr split.** Diagnostics → stderr (`[Console]::Error.WriteLine`), data → stdout.
- **Same file outputs at the same paths under `harness-state/`** with the same JSON shapes and field names. Commit messages and git-tag names must match exactly: `harness(sprint-NN): description [C-ID]`, `harness/sprint-NN/pass`, `harness/plan`, etc.

### Path & encoding hygiene
- All path joins via `Join-Path` or `[IO.Path]::Combine`. Never literal `/` in joins (literals inside command-line args to `git`/`jq` are fine — those tools accept either separator).
- Anchor relative paths to `$PSScriptRoot` so scripts work from any cwd.
- Write text files as **UTF-8 without BOM**: `Set-Content -Encoding utf8NoBOM` (PS7).
- Respect repo `.gitattributes` — text files end up LF-only when committed.

### Sourcing pattern
The `.sh` files use `source harness/lib/utils.sh`. The PowerShell equivalent uses **dot-sourcing**:

```powershell
. (Join-Path $PSScriptRoot 'utils.ps1')
```

We do not convert libraries into `.psm1` modules — that would break the side-by-side parity rule and complicate `$PSScriptRoot` chains.

### Error handling & strictness
- `Set-StrictMode -Version Latest` and `$ErrorActionPreference = 'Stop'` at the top of every script.
- Wrap external commands so a non-zero exit code throws a terminating error mirroring `.sh` `set -e`. Provide an `Invoke-NativeCommand` (or `Invoke-OrFail`) helper in `utils.ps1` that runs an external command, streams its output, and throws on non-zero `$LASTEXITCODE`. Use it for `git`, `gh`, `claude`. For `jq`, the same wrapper is used when its exit code carries semantic meaning (e.g. filter match/no-match); a `Get-JsonField` convenience helper in utils.ps1 is encouraged.

## Out of scope / non-goals

- Hooks (`harness/hooks/*.sh`) — Claude runs them in its own env.
- Porting `.bats` Layer 1 unit tests to PowerShell. The `.sh` test runners themselves are in scope (they call `bats` as an external tool).
- Modifying or deleting any `.sh` original.
- Changing harness behavior, file protocol, schemas, or skills under `.claude/skills/`.
- Cross-platform support beyond Windows (the .ps1 happening to run on macOS/Linux pwsh is a side benefit, not a target).

## Acceptance criteria (evaluator-checkable)

Per-script:
1. **Existence**: `Test-Path` returns true for every expected `.ps1` next to its `.sh`.
2. **Parses**: `[System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$errs)` returns zero parse errors.
3. **No forbidden tool calls**: an AST-aware scan finds no bare command invocations of `bash`, `sh`, `wsl`, `sed`, `awk`, `grep`, `find`, `realpath`, `mktemp`, `dirname`, `basename`, `tr`, `cut`, `xargs`. Matches inside string literals or comments are allowed. `jq`, `git`, `gh`, `claude`, `node`, `npm`, `bats` are explicitly permitted.
4. **Help/no-arg behavior parity**: where the `.sh` prints usage on `--help` or `-h`, the `.ps1` does too with the same flag.

Whole-port:
5. **Coverage**: every in-scope `.sh` (the 11 enumerated above) has a sibling `.ps1` with the same basename. No `.ps1` exists for any hook `.sh`.
6. **Smoke**: `pwsh -NoProfile -File harness/orchestrate.ps1 --help` exits 0 with usage; `tests/run-all.ps1 --help` exits 0 with usage.
7. **Invariant**: no `.sh` file modified, no hook `.sh` shadowed by a `.ps1`.

---
Authored 2026-06-10, revised after user clarification re: jq/bats/npm availability on Windows.
