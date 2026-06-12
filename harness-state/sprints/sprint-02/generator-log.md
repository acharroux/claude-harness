# Sprint 02 Generator Log

## Source files studied (read end-to-end)

- `harness/lib/planner.sh`   (60 lines)
- `harness/lib/generator.sh` (55 lines)
- `harness/lib/evaluator.sh` (93 lines)
- `harness/lib/contract.sh`  (83 lines)
- `harness/lib/utils.ps1`    (Sprint 01 -- consumed for helpers)
- `harness/lib/invoke.ps1`   (Sprint 01 -- consumed for `Invoke-ClaudeAgent`)
- `harness/lib/git.ps1`      (Sprint 01 -- not directly called by the four files, but loaded for the smoke-load test)

## Function-name mapping per source file

### planner.sh -> planner.ps1

| Bash function   | PowerShell function | Notes                                                         |
|-----------------|---------------------|---------------------------------------------------------------|
| `invoke_planner`| `Invoke-Planner`    | Same `mode` argument ("new"/"extend"); same prompts; emits sprint count to stdout via `Write-Output` to mirror the .sh `echo "$sprint_count"`. |

### generator.sh -> generator.ps1

| Bash function     | PowerShell function | Notes                                                              |
|-------------------|---------------------|--------------------------------------------------------------------|
| `invoke_generator`| `Invoke-Generator`  | Same args (`SprintNumber`, `Attempt`); same prompts; same retry/design-spec injection logic; "blocked" status sets `$LASTEXITCODE = 2` then throws (mirrors `return 2`). |

### evaluator.sh -> evaluator.ps1

| Bash function       | PowerShell function | Notes                                                                                                  |
|---------------------|---------------------|--------------------------------------------------------------------------------------------------------|
| `invoke_evaluator`  | `Invoke-Evaluator`  | Same `--mcp-config .mcp.json` injection for web-frontend projects; same field-name fallbacks via jq.   |
| `invoke_regression` | `Invoke-Regression` | Same prompt, same web-frontend MCP injection, same `regression/last-run.json` consumption.             |

### contract.sh -> contract.ps1

| Bash function        | PowerShell function           | Notes                                                                                                                                          |
|----------------------|-------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------|
| `negotiate_contract` | `Invoke-ContractNegotiation`  | Same propose <-> review loop; max rounds resolved from `$env:MAX_CONTRACT_ROUNDS`, then `harness-state/config.json .maxContractRounds`, then 3.|

## Behavioral nuances handled

1. **Argument-order parity preserved.** `Invoke-Generator -SprintNumber N -Attempt M` matches `invoke_generator "$sprint_num" "$attempt"`. Same for evaluator.
2. **stderr vs stdout split.** All log helpers (`Write-LogInfo` etc.) write to stderr (already done in Sprint 01 utils.ps1). Only planner.ps1 emits the sprint count on stdout via `Write-Output`, mirroring the .sh `echo "$sprint_count"`.
3. **Exit-code semantics.** A non-zero `Invoke-ClaudeAgent` triggers a `throw` (mirrors `set -e` plus `return 1` in the .sh). Generator's "blocked" path sets `$LASTEXITCODE = 2` and throws, mirroring the .sh `return 2`.
4. **Prompts loaded unchanged from `harness/prompts/*`.** None of the four .sh files actually read prompt files from disk -- the prompts are hard-coded inline strings. The .ps1 ports preserve those strings byte-for-byte (modulo necessary escaping of `"` for PowerShell).
5. **JSON shape parity for outputs.**
   - `planner.ps1` does not write product-spec.md / sprint-plan.json itself; the planner agent does. The .ps1 only asserts existence + JSON validity, identically to the .sh.
   - `generator.ps1` emits the same status.json directive in its prompt (`{"status": "ready-for-eval", "attempt": N}`).
   - `evaluator.ps1` does not write eval-report.json; the evaluator agent does. The .ps1 reads it back with the same set of field-name fallbacks (`.overallResult // .result // .verdict`, `.passCount // .pass_count // .score.passedCriteria // .score.passed`, etc.).
   - `contract.ps1` copies `contract-proposal.json` -> `contract.json` on acceptance via `Copy-Item -Force`, mirroring the .sh `cp`.
6. **Web-frontend MCP injection.** `evaluator.ps1` builds an `$extraArgs = @('--mcp-config', '.mcp.json')` array when `.mcp.json` exists, then splats it via `@extraArgs` into `Invoke-ClaudeAgent` -- avoids the empty-string-becomes-positional-arg trap that bit early Sprint 01 ports.
7. **Forbidden-tool avoidance.** No `bash`, `sh`, `wsl`, `sed`, `awk`, `grep`, `find`, `realpath`, `mktemp`, `dirname`, `basename`, `tr`, `cut`, `xargs` as bare commands. `head -c 200` / `head -c 300` from the .sh is replaced with `.Substring(0, N)` after a length check. Temp files (where needed) come via `New-TemporaryFile`. Directory creation via `New-Item -ItemType Directory -Force`.
8. **jq output capture.** Where jq output is read back, results are normalized with `($x -is [array]) -> $x -join ''` then `.Trim()`, matching the proven Sprint 01 pattern.
9. **Encoding.** No file writes happen in these four .ps1 files. (planner/contract write is performed by the agents through Claude tools, evaluator only reads, contract only copies.) Where `Copy-Item` is used, content is preserved bit-exact.
10. **Dot-sourcing.** Every file dot-sources `utils.ps1` (and `invoke.ps1` where `Invoke-ClaudeAgent` is called) using `Join-Path $PSScriptRoot ...`, identical to the .sh `source "${SCRIPT_DIR}/utils.sh"` pattern.
11. **maxContractRounds resolution.** The .sh uses only `${MAX_CONTRACT_ROUNDS:-3}` (env var). The .ps1 first checks `$env:MAX_CONTRACT_ROUNDS`, then falls back to `Read-JsonField` on `config.json`, then 3. This is a strict superset of the .sh behavior -- existing callers that set the env var get identical behavior.

## Verification output

### 1. Parse check (PS 5.1)

```
OK   harness/lib/planner.ps1
OK   harness/lib/generator.ps1
OK   harness/lib/evaluator.ps1
OK   harness/lib/contract.ps1
```

### 2. Forbidden-token AST scan

```
clean harness/lib/planner.ps1
clean harness/lib/generator.ps1
clean harness/lib/evaluator.ps1
clean harness/lib/contract.ps1
all-clean
```

### 3. Smoke-load (utils + invoke + git + all four new files)

```
all-loaded
```

## Files written

- `harness/lib/planner.ps1`
- `harness/lib/generator.ps1`
- `harness/lib/evaluator.ps1`
- `harness/lib/contract.ps1`

No `.sh` files modified. No hooks shadowed. No commit performed (per instructions).
