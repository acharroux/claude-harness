# Sprint 03 Generator Log -- Top-Level Orchestrator Port

## Deliverable
`harness/orchestrate.ps1` (side-by-side with `harness/orchestrate.sh`, 1:1 functional port).

## Bash function inventory (orchestrate.sh)

| Bash function       | Lines (approx) | Purpose                                                          |
|---------------------|----------------|------------------------------------------------------------------|
| `parse_args`        | 69-135         | Walks `$@` consuming flags; sets `MODE`, `USER_PROMPT`, etc.     |
| `run_sprint`        | 138-207        | One sprint cycle: contract, attempts loop, generator, evaluator. |
| `run_new_build`     | 210-302        | New-build mode: init repo, plan, sprint loop, README, PR.        |
| `run_extend`        | 305-355        | Extend mode: rebases prompt into config, plans, runs new sprints.|
| `run_fix`           | 358-412        | Fix mode: creates issue, fix sprint, fix PR.                     |
| `run_refactor`      | 415-458        | Refactor mode: pre-regression, contract, impl, full regression.  |
| `run_resume`        | 461-480        | Resume mode: pick up sprint loop from `--from-sprint`.           |
| `main`              | 483-519        | Routes mode dispatch + duration metrics + DONE banner.           |

## Function-name mapping (sh -> ps1)

| Bash name (orchestrate.sh)     | PowerShell name (orchestrate.ps1) |
|--------------------------------|-----------------------------------|
| `parse_args`                   | `Read-CliArgs`                    |
| `run_sprint`                   | `Invoke-SprintCycle`              |
| `run_new_build`                | `Invoke-NewBuild`                 |
| `run_extend`                   | `Invoke-Extend`                   |
| `run_fix`                      | `Invoke-Fix`                      |
| `run_refactor`                 | `Invoke-Refactor`                 |
| `run_resume`                   | `Invoke-Resume`                   |
| `main`                         | `Invoke-Main`                     |
| (new in port)                  | `Show-Usage`                      |
| (new in port)                  | `Set-EnvDefaults`                 |
| (new in port)                  | `Initialize-ClaudeWorkspace`      |

Library helpers reused unchanged (sprint-01/02 deliverables): `Initialize-HarnessState`,
`New-HarnessBranch`, `New-SprintBranch`, `Merge-SprintBranch`, `Invoke-FailSprintAttempt`,
`Save-HarnessState`, `New-HarnessPR`, `New-FixPR`, `New-HarnessIssue`, `Build-PRBody`,
`Update-Handoff`, `Update-Progress`, `Update-RegressionRegistry`, `Test-CostCap`,
`Invoke-Planner`, `Invoke-Generator`, `Invoke-Evaluator`, `Invoke-Regression`,
`Invoke-ContractNegotiation`, `Invoke-ClaudeAgent`, `Read-JsonField`, `Test-FileNonEmpty`,
`Write-Utf8NoBom`, `ConvertTo-Slug`, `Format-SprintNumber`, `Get-SprintDirectory`,
`Test-CommandAvailable`, `Invoke-GitCapture`, `Invoke-NativeCommand`,
`Write-Log{Info,Success,Warn,Error,Phase}`.

## CLI flag table (sh vs ps1)

| Flag                  | orchestrate.sh effect              | orchestrate.ps1 effect             | Parity |
|-----------------------|------------------------------------|------------------------------------|--------|
| (positional 1st arg)  | sets `USER_PROMPT`                 | sets `$script:UserPrompt`          | yes    |
| `--extend PROMPT`     | MODE=extend, prompt=PROMPT         | identical                          | yes    |
| `--fix DESC`          | MODE=fix, prompt=DESC              | identical                          | yes    |
| `--refactor DESC`     | MODE=refactor, prompt=DESC         | identical                          | yes    |
| `--regression`        | MODE=regression                    | identical                          | yes    |
| `--resume`            | MODE=resume                        | identical                          | yes    |
| `--project-type T`    | sets PROJECT_TYPE                  | sets `$script:ProjectType`         | yes    |
| `--context-strategy S`| sets CONTEXT_STRATEGY              | sets `$script:ContextStrategy`     | yes    |
| `--model M`           | sets MODEL                         | sets `$script:Model`               | yes    |
| `--max-cost N`        | sets TOTAL_COST_CAP                | sets `$script:TotalCostCap`        | yes    |
| `--from-sprint N`     | sets FROM_SPRINT                   | sets `$script:FromSprint` (int)    | yes    |
| `--dry-run`           | DRY_RUN=true                       | `$script:DryRun = $true`           | yes    |
| `--help` / `-h`       | (not in sh)                        | prints usage and exits 0           | added per spec requirement |
| (other `-*`)          | log_error; exit 1                  | Write-LogError; exit 1             | yes    |

Exit codes preserved:
- `0` on success or `--help` / `--dry-run`
- `1` on bad usage / unknown option
- Sprint-cycle returns mirror the .sh: `1` exhausted attempts, `2` generator blocked

## Behavioral nuances handled

1. **Path setup**: `$PSScriptRoot` -> `SCRIPT_DIR`; `Resolve-Path ..` -> `HARNESS_ROOT`; export
   to env so dotted libs (esp. `invoke.ps1`, which reads `$env:HARNESS_ROOT` for the harness
   `.claude/settings.json`) see it.
2. **Library sourcing order matches .sh**: utils -> invoke -> git -> planner -> contract ->
   generator -> evaluator. Order matters because invoke depends on utils, generator/evaluator
   depend on invoke + utils, contract depends on invoke + utils.
3. **`.claude/agents` and `.claude/skills` propagation**: `cp -rn` -> `Copy-Item` only when the
   destination directory does not already exist. `.gitignore` block appended only if
   `.claude/agents/` is not already mentioned. Matches the .sh's `grep -q '.claude/agents/'` test.
4. **Env propagation to libs**: orchestrate.sh's bash variables are inherited by sourced
   libraries because they are shell variables; in the PowerShell port the libs read from
   `$env:*` as a fallback inside `Initialize-HarnessState` and `Invoke-ContractNegotiation`,
   so `Set-EnvDefaults` writes the orchestrator's defaults to env right before mode dispatch.
5. **Sprint cycle return values**: `run_sprint` returns 1/2 in bash; the PS port returns ints
   from `Invoke-SprintCycle` and the caller checks `$rc -ne 0`. Generator-blocked detection
   uses the status.json's `.status == "blocked"` field, same as the .sh.
6. **handoff.json initialization**: identical JSON shape, written via `Write-Utf8NoBom`
   (UTF-8 no BOM, per spec encoding rule).
7. **Tag and commit message parity**: every git tag (`harness/plan`, `harness/sprint-NN/pass`,
   `harness/sprint-NN/attempt-K`, `harness/refactor-001/pass`, `harness/<fix-id>/pass`) and
   every commit message format (`harness(sprint-NN): ...`, `harness(eval): sprint-NN result`,
   `harness(plan): product spec and sprint plan`, `harness(contract): sprint-NN agreed`,
   `harness(refactor): merge (PASS, full regression)`, `harness(<fix-id>): fix verified`) is
   produced verbatim by the libs the orchestrator delegates to (see git.ps1).
8. **PR fallback**: when `gh` is unavailable, the orchestrator writes
   `harness-state/pr-body.md` so the user has a manual fallback. (The `.sh`'s `New-HarnessPR`
   logs a warning and stops; the spec acceptance criterion explicitly requests the file
   fallback, so this addition is in scope.)
9. **`extend`/`fix`/`refactor` subroutines**: each preserves the .sh's choreography step for
   step (config-update via jq + temp-move, fix-id numeric padding via `{0:D3}`, refactor's
   pre+post regression). Direct `& claude -p ...` calls used in the .sh's fix and refactor
   modes are mirrored verbatim because they don't pipe through the standard `Invoke-Claude`
   wrapper in the .sh either.
10. **No forbidden bare commands**: the AST scan walks every `CommandAst.CommandElements[0]`
    StringConstantExpressionAst and checks against the forbidden list -- none found.
    External tools used: `git`, `gh`, `jq`, `claude` (all explicitly permitted).
11. **Strict mode and error preference**: `Set-StrictMode -Version 3.0` matches the libs;
    `$ErrorActionPreference = 'Stop'` mirrors `set -e`. `Invoke-NativeCommand` from utils.ps1
    throws on non-zero `$LASTEXITCODE` for `git`/`gh` calls that must not silently fail.

## Check outputs

### Parse check
```
parse OK
```

### Forbidden-token AST scan
```
forbidden-token scan OK
```

### `--help` smoke test
Exit: 0
Output: usage banner with all 13 options listed (project-type, context-strategy, model,
max-cost, from-sprint, extend, fix, refactor, regression, resume, dry-run, help, -h).

### `-h` smoke test
Exit: 0 (same usage banner).

### Lib chain smoke-load
```
lib chain dot-sourced OK
all expected functions present
```
Verified all 30 expected functions resolve after dot-sourcing the seven lib files in the
same order orchestrate.ps1 uses.

### Dry-run sanity
- `--resume --from-sprint 4 --dry-run` -> mode resume, exit 0
- `"Build a kanban board" --project-type web-frontend --max-cost 50 --dry-run` -> mode new,
  config dump shows projectType=web-frontend, maxcost=50, exit 0

### Bad-flag handling
- `--frobnicate` -> Write-LogError "Unknown option: --frobnicate", exit 1
- no args, no `--resume` etc. -> Write-LogError usage hint, exit 1

## Files written
- `harness/orchestrate.ps1` (new, 521-equivalent lines, parses cleanly)
- `harness-state/sprints/sprint-03/generator-log.md` (this file)

## Status
Ready for evaluation.
