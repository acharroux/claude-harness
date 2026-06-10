# Sprint-04 Generator Log

## Source files studied

- `tests/run-all.sh` — top-level test runner that dispatches layer1/layer2/layer3/all and gates layer2/3 behind env-var guards.
- `tests/layer2/smoke-test.sh` — end-to-end smoke test that runs the harness against a hello-world prompt in an isolated temp dir, then asserts artifacts.
- `tests/layer3/meta-test.sh` — meta test that copies the project to a temp dir and drives the harness to build its own test suite, then verifies eval output.
- `harness/lib/utils.ps1` — confirmed available helpers (`Write-Utf8NoBom`, logging, sprint helpers) for dot-sourcing.

## Function-name / mechanism mapping

| .sh construct                                | .ps1 equivalent                                                                |
| -------------------------------------------- | ------------------------------------------------------------------------------ |
| `set -euo pipefail`                          | `Set-StrictMode -Version 3.0` + `$ErrorActionPreference = 'Stop'`              |
| `command -v bats`                            | `Get-Command bats -ErrorAction SilentlyContinue`                               |
| `bash "$SCRIPT_DIR/layer2/smoke-test.sh"`    | `& powershell -NoProfile -File $smokePs1`                                      |
| `bash -c "jq ..."`                           | inline `& jq ... ; $LASTEXITCODE -eq 0`                                        |
| `find harness-state/sprints -name '*.json'`  | `Get-ChildItem -Recurse -Filter '*.json'`                                      |
| `mktemp -d`                                  | `Join-Path ([System.IO.Path]::GetTempPath()) ("harness-..." + Guid)`           |
| `trap "..." EXIT`                            | PowerShell `trap { ... ; break }` + try/catch                                  |
| `wc -c < file`                               | `(Get-Item ...).Length`                                                        |
| `grep -q 'PASS' file`                        | `Select-String -SimpleMatch -Quiet`                                            |
| `git tag | grep -q 'harness/'`               | `git tag` piped through `Where-Object { $_ -match 'harness/' }`                |
| `cp -r src dst`                              | `Copy-Item -LiteralPath src -Destination dst -Recurse -Force`                  |
| `chmod +x ...`                               | omitted (no-op on Windows)                                                     |
| `date +%s` arithmetic                        | `Get-Date` with `[TimeSpan]` subtraction                                       |
| `tee smoke-output.log`                       | `Tee-Object -FilePath $smokeLog`                                               |

## Behavioural nuances handled

- **CLI parity.** The three `.sh` files have no `--help` flag. Per the sprint instructions, all three `.ps1` ports add a `--help`/`-h`/`/?` flag that prints a usage block and exits 0.
- **Default layer.** `run-all.sh` defaults to `layer1` via `${1:-layer1}`. The `.ps1` mirrors this with an explicit default and parses any non-flag positional as the layer name.
- **Cross-script invocation.** `run-all.sh` shells out to `bash tests/layer2/smoke-test.sh` and `bash tests/layer3/meta-test.sh`. The `.ps1` invokes `powershell -NoProfile -File` against the corresponding `.ps1` files instead — never `bash`, `sh`, or `wsl`.
- **`bats` is preserved.** Layer 1 still calls `bats` directly with the list of `.bats` files (allowed external tool).
- **`find` replaced by `Get-ChildItem`.** Both smoke and meta tests scan for generated test files; the `.ps1` versions use `Get-ChildItem -Recurse` plus a `Where-Object` name-pattern filter.
- **Temp dir.** Replaced `mktemp -d` with `[System.IO.Path]::GetTempPath()` plus a GUID suffix, mirroring the "not cleaned for inspection" exit-time message via a `trap` block and `try/catch` so the path is reported on both success and failure.
- **Exit-code propagation.** Both layer dispatch paths and `Tee-Object` runs preserve `$LASTEXITCODE`; `all` short-circuits on the first non-zero rc, matching `set -e` semantics. The smoke test exits 1 if any assertion fails.
- **`HARNESS_*` env guards.** `--help` is parsed and handled before the `HARNESS_SMOKE_TEST`/`HARNESS_META_TEST` env-var check, so help works without the guard set.
- **`.mcp.json` optional copy.** The `.sh` used `cp ... 2>/dev/null || true`; the `.ps1` checks `Test-Path` first.
- **Meta test prompt.** Adapted from `harness/lib/utils.sh` function names to `harness/lib/utils.ps1` function names so the prompt matches what the harness can verify; entry point switched from `meta-tests/run.sh` to `meta-tests/run.ps1`.
- **`bash -c` not used.** All compound shell expressions have been re-expressed as PowerShell pipelines or inline native calls plus `$LASTEXITCODE` checks.
- **No forbidden tokens.** AST scan over `bash, sh, wsl, sed, awk, grep, find, realpath, mktemp, dirname, basename, tr, cut, xargs` returns clean.

## Verification output

### 1) Parse check
```
OK   tests/run-all.ps1
OK   tests/layer2/smoke-test.ps1
OK   tests/layer3/meta-test.ps1
```

### 2) Forbidden-token AST scan
```
AST scan clean
```

### 3) `--help` smoke
```
--- run-all.ps1 ---
Usage: powershell -NoProfile -File tests/run-all.ps1 [layer1|layer2|layer3|all|--help]

  layer1   Run Layer 1 (unit/integration tests via bats; default)
  layer2   Run Layer 2 smoke test (requires HARNESS_SMOKE_TEST=1)
  layer3   Run Layer 3 meta test  (requires HARNESS_META_TEST=1)
  all      Run all three layers in sequence
  --help   Show this message and exit 0
EXIT=0

--- smoke-test.ps1 ---
Usage: powershell -NoProfile -File tests/layer2/smoke-test.ps1 [--help]

Layer 2 smoke test: drives the harness end-to-end with a real Claude run.
Set HARNESS_SMOKE_TEST=1 to actually execute (costs Claude usage).
EXIT=0

--- meta-test.ps1 ---
Usage: powershell -NoProfile -File tests/layer3/meta-test.ps1 [--help]

Layer 3 meta test: drives the harness to produce its own bats test suite.
Set HARNESS_META_TEST=1 to actually execute (costs significant Claude usage).
EXIT=0
```

All three checks green. Per instructions, no commits made and no end-to-end `bats`/`claude` runs attempted.
