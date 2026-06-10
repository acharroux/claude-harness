# Product Spec: Native PowerShell Port of Harness Shell Scripts

## Goal

Produce native PowerShell 7+ (`.ps1`) equivalents of every user-invokable `.sh` script in this repository so the Planner-Generator-Evaluator harness becomes fully usable on native Windows without WSL or any POSIX shell. Each `.ps1` lives **side-by-side** with its `.sh` counterpart, shares the same base name, and provides functionally equivalent observable behavior.

## Scope clarification (2026-06-10)

The user clarified: **hooks under `harness/hooks/` are NOT in scope**. Hooks are executed by Claude Code in its own runtime environment, where bash already works regardless of host OS. Only scripts a Windows *user* would invoke from a PowerShell prompt need ports. The four hook `.sh` files (`on-stop`, `on-generator-stop`, `on-evaluator-stop`, `validate-schema`) stay as-is and get no `.ps1` sibling.

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

Hooks (`harness/hooks/*.sh`, 4 files, ~348 lines) are out of scope per user clarification.

## Cross-cutting requirements every `.ps1` must satisfy

### Runtime
- **Primary target: PowerShell 7+ (`pwsh`)**. Each script begins with `#Requires -Version 7.0` and uses `Set-StrictMode -Version Latest` plus `$ErrorActionPreference = 'Stop'`.
- Windows PowerShell 5.1 is not a target.
- Each `.ps1` runnable as `pwsh -NoProfile -File <path> [args...]`. No `Set-ExecutionPolicy` change required by the user.

### Zero POSIX-tool dependency at runtime
- No `bash`, no WSL, no `jq`, `grep`, `sed`, `awk`, `cut`, `find`, `cat`, `tee`, `mktemp`, `realpath`, `dirname`, `basename`, `tr`, `sort`, `uniq`, `xargs`.
- Replacements:
  - `jq '.foo'` → `(Get-Content $f -Raw | ConvertFrom-Json).foo`
  - `jq '. + {x:1}' f.json > tmp && mv tmp f.json` → load → mutate → `ConvertTo-Json -Depth 32 | Set-Content -Encoding utf8NoBOM`
  - `grep -E pattern` → `Select-String -Pattern pattern`
  - `find . -name '*.sh'` → `Get-ChildItem -Recurse -Filter *.sh`
  - `mktemp` → `New-TemporaryFile`
  - `dirname / basename / realpath` → `Split-Path`, `Resolve-Path`
  - `tee` → `Tee-Object`
- Calling `git`, `gh`, `claude` is allowed and required (they are native Windows binaries on PATH).

### Argument and I/O contract parity
- **Same CLI flags, positional args, env-var inputs.** A user who reads README's `bash harness/orchestrate.sh "..."` example must be able to type `pwsh -NoProfile -File harness/orchestrate.ps1 "..."` and get the same effect.
- **Same exit codes.** 0 = success; non-zero codes used by `.sh` are preserved.
- **Same stdout/stderr split.** Diagnostics → stderr (`[Console]::Error.WriteLine`), data → stdout.
- **Same file outputs at the same paths under `harness-state/`** with the same JSON shapes and field names. Commit messages and git-tag names must match exactly (`harness(sprint-NN): description [C-ID]`, `harness/sprint-NN/pass`, etc.).

### Path & encoding hygiene
- All path joins via `Join-Path` or `[IO.Path]::Combine`. Never literal `/`.
- Anchor relative paths to `$PSScriptRoot` so scripts work from any cwd.
- Write text files as **UTF-8 without BOM** (`Set-Content -Encoding utf8NoBOM` on PS7) to match `.sh` output.
- Respect repo `.gitattributes` — text files must end up LF-only when committed.

### Sourcing pattern
The `.sh` files use `source harness/lib/utils.sh`. The PowerShell equivalent uses **dot-sourcing**:

```powershell
. (Join-Path $PSScriptRoot 'utils.ps1')
```

We do not convert libraries into `.psm1` modules — that would break the side-by-side parity rule and complicate `$PSScriptRoot` chains.

### Error handling & strictness
- `Set-StrictMode -Version Latest` and `$ErrorActionPreference = 'Stop'` at the top of every script.
- Wrap external commands (`git`, `gh`, `claude`) so a non-zero exit code throws a terminating error mirroring the `.sh` `set -e` behavior.
- Provide an `Invoke-OrFail` helper in `utils.ps1` that runs an external command and throws on non-zero `$LASTEXITCODE`.

## Out of scope / non-goals

- Hooks (`harness/hooks/*.sh`) — Claude runs them in its own env.
- Porting `.bats` Layer 1 unit tests to PowerShell (only the `.sh` test runners themselves are in scope).
- Modifying or deleting any `.sh` original.
- Changing harness behavior, file protocol, schemas, or skills under `.claude/skills/`.
- Cross-platform support beyond Windows (running on macOS/Linux pwsh is a free side benefit, not a target).

## Acceptance criteria (evaluator-checkable)

Per-script:
1. **Existence**: `Test-Path` returns true for every expected `.ps1` next to its `.sh`.
2. **Parses**: `[System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$null, [ref]$errs)` returns zero parse errors.
3. **No POSIX-tool dependence**: a token-aware scan of the parsed AST for `jq|grep|sed|awk|bash|wsl` as bare commands finds nothing (matches inside string literals or comments are allowed).
4. **Help/no-arg behavior parity**: where the `.sh` prints usage on `--help` or `-h`, the `.ps1` does too with the same flag.

Whole-port:
5. **Coverage**: every in-scope `.sh` (the 11 enumerated above) has a sibling `.ps1` with the same basename. No `.ps1` exists for any hook `.sh`.
6. **Smoke**: `pwsh -NoProfile -File harness/orchestrate.ps1 --help` exits 0 (or shows usage), as does `tests/run-all.ps1 --help`.
7. **Invariant**: no `.sh` file modified, no hook `.sh` shadowed by a `.ps1` (git diff against the branch base shows zero changes to `*.sh` and zero new files under `harness/hooks/`).

---
Authored 2026-06-10 for sprint plan `harness-state/sprint-plan.json`.
