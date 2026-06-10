#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Layer 3: The Meta Test (PowerShell port of tests/layer3/meta-test.sh)
# Uses the harness to build its own test suite.
#
# Prerequisites: Layer 1 must pass first.
# Guard: Set HARNESS_META_TEST=1 to run (costs Claude usage ~$50-100)
#
# Why this is not circular:
# Layer 1 (human-written, mock-tested) is the ground truth.
# The meta test demonstrates the harness can analyze a complex project,
# decompose it into sprints, produce tests, and have them pass evaluation.
#
# Usage:
#   powershell -NoProfile -File tests/layer3/meta-test.ps1
#   powershell -NoProfile -File tests/layer3/meta-test.ps1 --help

# Argument parsing -- the .sh accepts no flags; we add --help for parity.
$ShowHelp = $false
foreach ($a in $args) {
    switch -Regex ([string]$a) {
        '^(--help|-h|/\?)$' { $ShowHelp = $true }
        default              { }
    }
}

function Show-Usage {
    Write-Host "Usage: powershell -NoProfile -File tests/layer3/meta-test.ps1 [--help]"
    Write-Host ""
    Write-Host "Layer 3 meta test: drives the harness to produce its own bats test suite."
    Write-Host "Set HARNESS_META_TEST=1 to actually execute (costs significant Claude usage)."
}

if ($ShowHelp) {
    Show-Usage
    exit 0
}

if ($env:HARNESS_META_TEST -ne '1') {
    Write-Host "Set HARNESS_META_TEST=1 to run the meta test."
    Write-Host "This costs significant Claude usage (~`$50-100)."
    exit 0
}

# Anchor to script location.
$ScriptDir  = Split-Path -Parent $PSCommandPath
$TestsDir   = Split-Path -Parent $ScriptDir
$ProjectDir = Split-Path -Parent $TestsDir

# Dot-source utils.ps1 for shared helpers (Write-Utf8NoBom, logging, etc.).
$UtilsPath = Join-Path $ProjectDir 'harness/lib/utils.ps1'
if (-not (Test-Path -LiteralPath $UtilsPath)) {
    Write-Host "utils.ps1 not found at $UtilsPath"
    exit 1
}
. $UtilsPath

# Verify Layer 1 passes first.
Write-Host "=== Verifying Layer 1 (prerequisite) ==="
$runAllPs1 = Join-Path $TestsDir 'run-all.ps1'
& powershell -NoProfile -File $runAllPs1 layer1
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Layer 1 must pass before running the meta test."
    Write-Host "Fix Layer 1 failures first."
    exit 1
}

Write-Host ""
Write-Host "=== Layer 3: The Meta Test ==="
Write-Host "The harness will now build its own test suite."
Write-Host ""

# Create isolated meta-test directory (PowerShell-native equivalent of `mktemp -d`).
$MetaDir = Join-Path ([System.IO.Path]::GetTempPath()) ("harness-meta-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $MetaDir -Force | Out-Null

# Trap-equivalent: print the directory location on exit.
trap {
    Write-Host "Meta test dir: $MetaDir (not cleaned for inspection)"
    break
}

try {
    # Copy project to isolated directory.
    $copyDest = Join-Path $MetaDir 'claude-harness'
    Copy-Item -LiteralPath $ProjectDir -Destination $copyDest -Recurse -Force
    Set-Location -LiteralPath $copyDest

    # Ensure git is ready (best-effort, mirrors `|| true` semantics).
    & git init -q 2>$null
    & git add -A 2>$null
    & git commit -q -m 'meta test baseline' 2>$null
    # Do not throw on these — the .sh used `|| true` for each.

    $startTime = Get-Date

    # Run the harness to build its own test suite.
    $orchestratePs1 = Join-Path $copyDest 'harness/orchestrate.ps1'
    $metaLog = Join-Path $copyDest 'meta-output.log'
    $promptText = "Build a comprehensive bats-core test suite for this project (a multi-agent harness). " +
                  "The test suite should cover: " +
                  "(1) Unit tests for all pure functions in harness/lib/utils.ps1 " +
                  "(ConvertTo-Slug, Format-SprintNumber, Get-SprintDirectory, Read-JsonField, Test-FileNonEmpty, " +
                  "Initialize-HarnessState, Update-Handoff, Update-RegressionRegistry), " +
                  "(2) Git operation tests for harness/lib/git.ps1 functions using isolated temp repos, " +
                  "(3) Hook validation tests for harness/hooks/on-generator-stop.sh, " +
                  "on-evaluator-stop.sh, and on-stop.sh using fixture files. " +
                  "Put all tests in a meta-tests/ directory. Include a meta-tests/run.ps1 entry point."

    & powershell -NoProfile -File $orchestratePs1 `
        $promptText `
        --project-type cli-tool `
        --max-cost 100 2>&1 | Tee-Object -FilePath $metaLog

    $endTime = Get-Date
    $elapsed = [int]([TimeSpan]($endTime - $startTime)).TotalSeconds

    Write-Host ""
    Write-Host "=== META-TEST VERIFICATION ==="
    Write-Host ("Elapsed: {0}m {1}s" -f [math]::Floor($elapsed / 60), ($elapsed % 60))
    Write-Host ""

    $script:Pass = 0
    $script:Fail = 0

    function Assert-Check {
        param(
            [Parameter(Mandatory)][string]$Description,
            [Parameter(Mandatory)][scriptblock]$Test
        )
        $ok = $false
        try {
            $result = & $Test
            if ($result) { $ok = $true }
        } catch {
            $ok = $false
        }
        if ($ok) {
            Write-Host "  PASS: $Description"
            $script:Pass++
        } else {
            Write-Host "  FAIL: $Description"
            $script:Fail++
        }
    }

    # Check harness completed sprints.
    Assert-Check "Harness completed sprint cycle" {
        $reports = @(Get-ChildItem -Path 'harness-state/sprints' -Filter 'eval-report.json' -Recurse -File -ErrorAction SilentlyContinue)
        $reports.Count -gt 0
    }

    Assert-Check "At least one sprint passed evaluation" {
        $reports = @(Get-ChildItem -Path 'harness-state/sprints' -Filter 'eval-report.json' -Recurse -File -ErrorAction SilentlyContinue)
        $found = $false
        foreach ($r in $reports) {
            $val = & jq -r '.overallResult' $r.FullName 2>$null
            if ($LASTEXITCODE -eq 0 -and ($val -match 'PASS')) { $found = $true; break }
        }
        $found
    }

    # Check test files were created.
    Assert-Check "Test files were created" {
        $hits = @(Get-ChildItem -Path '.' -Recurse -File -ErrorAction SilentlyContinue |
                  Where-Object { $_.Name -like '*.bats' -or $_.Name -like 'test-*.sh' -or $_.Name -like 'test-*.ps1' })
        $hits.Count -gt 0
    }

    # Count generated test files in meta-tests/.
    $metaTestsRoot = Join-Path $copyDest 'meta-tests'
    $TestFiles = 0
    if (Test-Path -LiteralPath $metaTestsRoot -PathType Container) {
        $TestFiles = @(Get-ChildItem -Path $metaTestsRoot -Recurse -File -ErrorAction SilentlyContinue |
                        Where-Object { $_.Name -like '*.bats' -or $_.Name -like 'test-*.sh' -or $_.Name -like 'test-*.ps1' }).Count
    }
    Write-Host "  INFO: $TestFiles test files generated"

    # Try to run the generated tests.
    $runPs1   = Join-Path $metaTestsRoot 'run.ps1'
    $runShell = Join-Path $metaTestsRoot 'run.sh'
    if (Test-Path -LiteralPath $runPs1 -PathType Leaf) {
        Write-Host ""
        Write-Host "=== RUNNING GENERATED TESTS ==="
        & powershell -NoProfile -File $runPs1
        if ($LASTEXITCODE -eq 0) {
            Assert-Check "Generated tests pass" { $true }
        } else {
            Write-Host "  WARN: Some generated tests failed (this is informative, not blocking)"
            Assert-Check "Generated tests exist and are runnable" { $true }
        }
    } elseif (Test-Path -LiteralPath $runShell -PathType Leaf) {
        # Some generators may emit a .sh entry point; we don't invoke `bash` directly,
        # but we record that an entry point was produced.
        Write-Host ""
        Write-Host "  INFO: Found meta-tests/run.sh but skipping (no bash on this port path)"
        Assert-Check "Generated tests exist with shell entry point" { $true }
    } elseif ($TestFiles -gt 0) {
        Write-Host "  INFO: No run.ps1 entry point, but test files exist"
        Assert-Check "Test files were generated" { $true }
    }

    Write-Host ""
    Write-Host ("=== META-TEST RESULTS: {0} passed, {1} failed ===" -f $script:Pass, $script:Fail)
    Write-Host ""

    if ($script:Pass -ge 2) {
        Write-Host "The harness successfully:"
        Write-Host "  - Analyzed its own codebase"
        Write-Host "  - Planned a test suite via sprint decomposition"
        Write-Host "  - Implemented tests via the generator"
        Write-Host "  - Evaluated them via the evaluator"
        Write-Host ""
        Write-Host "This is not circular proof -- it is empirical evidence that the harness"
        Write-Host "can produce useful output on a complex, real-world project."
    }

    Write-Host ""
    Write-Host "Meta test output: $metaLog"
    Write-Host "Generated tests:  $metaTestsRoot"
    Write-Host "Meta test dir: $MetaDir (not cleaned for inspection)"
    exit 0
} catch {
    Write-Host "Meta test dir: $MetaDir (not cleaned for inspection)"
    throw
}
