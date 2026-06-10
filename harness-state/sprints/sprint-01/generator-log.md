# Sprint 01 Generator Log — Foundation libs (utils, git, invoke)

## Source files studied

- `harness/lib/utils.sh` (243 lines) — shared utilities: logging, JSON helpers, sprint helpers, state init, cost log, progress/handoff/registry updates.
- `harness/lib/git.sh` (286 lines) — git/gh wrappers: branch creation, sprint merge, fail-attempt forensics, harness-state commits, PR creation, issue creation, PR-body builder.
- `harness/lib/invoke.sh` (84 lines) — wraps `claude -p` with stream-json output, parses NDJSON for progress lines, propagates exit code.

## Function-name mapping

| Bash name (.sh)                   | PowerShell name (.ps1)        | File          |
|-----------------------------------|-------------------------------|---------------|
| `log_info`                        | `Write-LogInfo`               | utils.ps1     |
| `log_success`                     | `Write-LogSuccess`            | utils.ps1     |
| `log_warn`                        | `Write-LogWarn`               | utils.ps1     |
| `log_error`                       | `Write-LogError`              | utils.ps1     |
| `log_phase`                       | `Write-LogPhase`              | utils.ps1     |
| (new wrapper required by spec)    | `Invoke-NativeCommand`        | utils.ps1     |
| (die/fatal helper)                | `Stop-WithError`              | utils.ps1     |
| `sprint_pad`                      | `Format-SprintNumber`         | utils.ps1     |
| `sprint_dir`                      | `Get-SprintDirectory`         | utils.ps1     |
| `slugify`                         | `ConvertTo-Slug`              | utils.ps1     |
| `json_read`                       | `Read-JsonField`              | utils.ps1     |
| `file_exists`                     | `Test-FileNonEmpty`           | utils.ps1     |
| (utf8-no-bom write helper)        | `Write-Utf8NoBom`             | utils.ps1     |
| `init_harness_state`              | `Initialize-HarnessState`     | utils.ps1     |
| `log_cost`                        | `Add-CostEntry`               | utils.ps1     |
| `check_cost_cap`                  | `Test-CostCap`                | utils.ps1     |
| `update_progress`                 | `Update-Progress`             | utils.ps1     |
| `update_handoff`                  | `Update-Handoff`              | utils.ps1     |
| `update_regression_registry`      | `Update-RegressionRegistry`   | utils.ps1     |
| `git_create_harness_branch`       | `New-HarnessBranch`           | git.ps1       |
| `git_create_sprint_branch`        | `New-SprintBranch`            | git.ps1       |
| `git_merge_sprint`                | `Merge-SprintBranch`          | git.ps1       |
| `git_fail_sprint_attempt`         | `Invoke-FailSprintAttempt`    | git.ps1       |
| `git_commit_harness_state`        | `Save-HarnessState`           | git.ps1       |
| `git_create_pr`                   | `New-HarnessPR`               | git.ps1       |
| `git_create_fix_pr`               | `New-FixPR`                   | git.ps1       |
| `git_create_issue`                | `New-HarnessIssue`            | git.ps1       |
| `generate_pr_body`                | `Build-PRBody`                | git.ps1       |
| (internal: capture git output)    | `Invoke-GitCapture`           | git.ps1       |
| (internal: resolve base branch)   | `Get-BaseBranch`              | git.ps1       |
| (internal: ref-exists check)      | `Test-GitRefExists`           | git.ps1       |
| (internal: command available)     | `Test-CommandAvailable`       | git.ps1       |
| `invoke_claude`                   | `Invoke-ClaudeAgent`          | invoke.ps1    |

## Behavioral nuances handled

- **stderr routing.** All `log_*` helpers in the .sh write to stderr via `>&2`. The .ps1 versions use `[Console]::Error.WriteLine` so diagnostics don't pollute stdout (which carries data like the harness branch name returned by `New-HarnessBranch`).
- **Return-via-stdout pattern.** Bash functions like `git_create_harness_branch` `echo`'d their result. PowerShell functions instead `return` strings; only the result is written to the success-stream.
- **`set -euo pipefail` parity.** Each .ps1 starts with `Set-StrictMode -Version Latest` and `$ErrorActionPreference = 'Stop'`. The `Invoke-NativeCommand` helper throws on non-zero `$LASTEXITCODE`, mirroring how `set -e` aborts on a failed subcommand. For commands whose exit code is informational (e.g. `git rev-parse --verify`, `git diff --cached --quiet`), `Invoke-GitCapture` is used instead so callers can branch on the exit code without throwing.
- **JSON parity.** All JSON read/write paths go through `jq`, matching the .sh exactly. `init_harness_state` keeps the `jq -Rs .` prompt-encoding step and produces config.json with the same field names and values. `Update-Handoff` uses the identical jq filter from update_handoff. `Update-RegressionRegistry` uses the same `[.criteria[].id]` extraction.
- **Atomic writes.** Where the .sh used `mktemp` + `mv`, the .ps1 uses `New-TemporaryFile` + `Move-Item -Force` and cleans up the temp file in `finally`.
- **Encoding.** All text output is written as UTF-8 without BOM via `Set-Content -Encoding utf8NoBOM` / `Out-File -Encoding utf8NoBOM`, matching the spec and the `.gitattributes` LF policy.
- **Path joins.** Every constructed path uses `Join-Path` anchored to `$PSScriptRoot` (for sourcing) or `$script:HarnessState` (for state files). No literal `/` in path joins.
- **Tag/commit message format.** `Merge-SprintBranch` emits `harness(sprint-NN): merge (PASS, attempt K)` and tags `harness/sprint-NN/pass`. `Invoke-FailSprintAttempt` tags `harness/sprint-NN/attempt-K`. The evaluator-artifact commit uses `harness(sprint-NN): evaluator artifacts`. These match the .sh exactly.
- **`invoke_claude` argument loop.** The .sh accepts `--agent NAME --max-turns N [--mcp-config FILE] PROMPT` in any order; the .ps1 version mirrors that with named parameters plus a `ValueFromRemainingArguments` walk so callers can pass the same arg string they would to the .sh.
- **`--settings` discovery.** Mirrors the .sh: looks for `${HARNESS_ROOT:-.}/.claude/settings.json` and only adds the flag when the file exists.
- **Stream-json progress display.** The .ps1 keeps the same NDJSON parser, using `& jq -r` for each line to extract `.type`, the tool name (`assistant`), and the cost (`result`). The same dim-grey ANSI prefix (`> tool: preview`) is emitted to stderr.
- **Out-of-scope hooks untouched.** No `harness/hooks/*.sh` files were read or modified; no `.sh` originals were modified.

## Forbidden-token strategy

- No bare commands of `bash`, `sh`, `wsl`, `sed`, `awk`, `grep`, `find`, `realpath`, `mktemp`, `dirname`, `basename`, `tr`, `cut`, or `xargs`.
- Replacements:
  - `mktemp` → `New-TemporaryFile`
  - `dirname`/`basename` → no usage required (paths built via `Join-Path` and anchored to `$PSScriptRoot`).
  - `sed`/`tr`/`cut` (as used in `slugify` and `generate_pr_body`'s `head -c 80`) → `-replace` operators and `String.Substring`.
  - `grep -o '[0-9]*$'` (in `git_create_issue`) → `[regex]::Match($url, '(\d+)\s*$')`.
  - `command -v gh` (uses POSIX `command`) → `Get-Command -Name gh -ErrorAction SilentlyContinue` wrapped as `Test-CommandAvailable`.
  - `git ls-remote --heads ... | grep -q .` → check `[string]::IsNullOrWhiteSpace` on the captured output.
  - `seq` → `for ($i = 1; $i -le ...; $i++)`.
- Allowed external commands used: `jq`, `git`, `gh`, `claude`. `node`/`npm`/`bats` are not needed in these three foundation libs.

## Verification output

Both checks were run against the worktree copy of the three files using Windows PowerShell 5.1 (the AST `Parser` class lives in `System.Management.Automation` and is identical in 5.1 and 7+; the system's `pwsh` was not present on PATH in this environment, but the parse and AST scans are version-independent).

### Parse check
```
OK   harness/lib/utils.ps1
OK   harness/lib/git.ps1
OK   harness/lib/invoke.ps1
```

### Forbidden-token AST scan
```
forbidden-token scan: clean
```

(Note: at runtime, the `#Requires -Version 7.0` directive will refuse to load these scripts under Windows PowerShell 5.1 — that is the intended behavior per the product spec which targets pwsh 7+.)

---

## PS 5.1 compatibility patch

The user's machine has only Windows PowerShell 5.1 (pwsh 7 is not installed), so the three foundation libs were retrofitted to load and run under both 5.1 and 7+.

### What changed

1. **Header lines (all three files).**
   - `#Requires -Version 7.0` → `#Requires -Version 5.1`
   - `Set-StrictMode -Version Latest` → `Set-StrictMode -Version 3.0`
   - `$ErrorActionPreference = 'Stop'` retained.

2. **ANSI escape literal (`utils.ps1` color block, `invoke.ps1` two stream-progress lines).**
   The `` `e `` escape sequence is PS 7+ only — under 5.1 it produces a literal `e`, breaking color output. Replaced every occurrence with `$([char]27)`:
   - `utils.ps1` lines 8–13: `$script:Red = "$([char]27)[0;31m"` etc.
   - `invoke.ps1` two `[Console]::Error.WriteLine` calls in the assistant/result branches.

3. **utf8NoBOM encoding helper (`utils.ps1`).**
   `Set-Content -Encoding utf8NoBOM`, `Add-Content -Encoding utf8NoBOM`, and `Out-File -Encoding utf8NoBOM` do not exist in PS 5.1 (its `utf8` writes a BOM). The previously-thin `Write-Utf8NoBom` wrapper around `Set-Content` was replaced with a `[System.IO.File]::WriteAllText` / `AppendAllText` implementation using `New-Object System.Text.UTF8Encoding($false)`. Signature now: `Write-Utf8NoBom -Path P -Value V [-Append]`.

4. **Replaced every `utf8NoBOM` write site.**
   Scope: `utils.ps1` only (git.ps1 and invoke.ps1 had no such sites). Sites updated:
   - `Initialize-HarnessState`: config.json, cost-log.json, regression registry.json, progress.md (4 sites; all `Set-Content … -Encoding utf8NoBOM` → `Write-Utf8NoBom -Path … -Value …`).
   - `Add-CostEntry`: jq pipeline previously `& jq … | Out-File -LiteralPath $tmp -Encoding utf8NoBOM` → captured into `$jqOut`, exit-code-checked, then `Write-Utf8NoBom -Path $tmp -Value ($jqOut -join "`n")`.
   - `Update-Progress`: `Add-Content … -Encoding utf8NoBOM` → `Write-Utf8NoBom -Path … -Value … -Append`.
   - `Update-Handoff`: jq pipeline pattern same as `Add-CostEntry`. Also the initialization branch (`Set-Content $handoffFile $init -Encoding utf8NoBOM` → `Write-Utf8NoBom`).
   - `Update-RegressionRegistry`: jq pipeline pattern same as `Add-CostEntry`.
   - Total: 8 write sites + 1 helper rewrite.

5. **Out of scope (left untouched).** Function names, function bodies' core logic, file paths, JSON shapes, commit/tag formats. No `Set-Content` calls without an explicit `utf8NoBOM` encoding existed, so none were touched.

### Verification (Windows PowerShell 5.1)

#### Parse check
```
OK   harness/lib/utils.ps1
OK   harness/lib/git.ps1
OK   harness/lib/invoke.ps1
```

#### Forbidden-token AST scan
```
forbidden-token scan: clean
```

#### Smoke-load (dot-source) check
```
. ./harness/lib/utils.ps1   -> loaded
. ./harness/lib/git.ps1     -> loaded
. ./harness/lib/invoke.ps1  -> loaded
```

All three checks were run via `powershell -NoProfile` (Windows PowerShell 5.1) since `pwsh` is not on PATH. The scripts now load and parse cleanly under 5.1, and remain forward-compatible with 7+ (the `[char]27` literal, `System.Text.UTF8Encoding`, and `[System.IO.File]::WriteAllText` are all available in both versions).

### Fix for jq-splat blocker (post-eval-1)

**Site:** `Update-RegressionRegistry` in `harness/lib/utils.ps1`.

**Symptom:** Capturing `& jq '[.criteria[].id]' $contractPath` yielded a multi-line `string[]`. PS then splatted it into argv when later passed via `--argjson criteria $criteriaIds`, so jq saw `--argjson criteria [` and aborted (`invalid JSON text passed to --argjson`, exit 2).

**Root cause:** PS-on-Windows has two compounding traps for jq output reuse:
1. Pretty-printed jq output is captured as a string array → splat hazard.
2. Even joined to one line, PS 5.1 strips embedded `"` chars when passing argv to native exes — `--argjson criteria '["C1-01",...]'` reaches jq with the quoting destroyed.

**Fix:** Use `-c` for compact jq output, join to a single line, write to a temp file, then feed via `--slurpfile criteriaArr <tmp>` (referencing `$criteriaArr[0]` in the filter). Bypasses both traps. The temp file is cleaned up in `finally`.

**Verification:** `harness-state/sprints/sprint-01/test-update-regression-registry.ps1` writes a 3-criteria contract fixture, calls `Update-RegressionRegistry -SprintNumber 1`, and asserts the resulting registry.json has `criteria=["C1-01","C1-02","C1-03"]` and the right contractPath. Result: `PASS: criteria=[C1-01,C1-02,C1-03] contractPath=sprints/sprint-01/contract.json`.

**Audit:** Other `& jq` capture sites in `utils.ps1` (`Add-CostEntry`, `Update-Handoff`) write the captured output back to a temp file via `Write-Utf8NoBom -Value ($jqOut -join "`n")`. They never pass the captured value as argv to another jq call, so the splat hazard does not apply. `git.ps1` has no `& jq` calls. `invoke.ps1` uses `& jq -r ...` for scalar extraction (single-line strings) and never splats — safe.
