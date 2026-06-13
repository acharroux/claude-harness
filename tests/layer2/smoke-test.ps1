#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Layer 2: Smoke test with real Claude (PowerShell port of tests/layer2/smoke-test.sh)
# Builds a trivial project to verify end-to-end harness functionality.
#
# Guard: Set HARNESS_SMOKE_TEST=1 to run (costs Claude usage ~$10-20)
# Timeout: 30 minutes
#
# Usage:
#   powershell -NoProfile -File tests/layer2/smoke-test.ps1
#   powershell -NoProfile -File tests/layer2/smoke-test.ps1 --help

# Argument parsing -- the .sh accepts no flags; we add --help for parity.
$ShowHelp = $false
foreach ($a in $args) {
    switch -Regex ([string]$a) {
        '^(--help|-h|/\?)$' { $ShowHelp = $true }
        default              { }
    }
}

function Show-Usage {
    Write-Host "Usage: powershell -NoProfile -File tests/layer2/smoke-test.ps1 [--help]"
    Write-Host ""
    Write-Host "Layer 2 smoke test: drives the harness end-to-end with a real Claude run."
    Write-Host "Set HARNESS_SMOKE_TEST=1 to actually execute (costs Claude usage)."
}

if ($ShowHelp) {
    Show-Usage
    exit 0
}

if ($env:HARNESS_SMOKE_TEST -ne '1') {
    Write-Host "Set HARNESS_SMOKE_TEST=1 to run the smoke test."
    exit 0
}

# Anchor to script location.
$ScriptDir  = Split-Path -Parent $PSCommandPath
$TestsDir   = Split-Path -Parent $ScriptDir
$ProjectDir = Split-Path -Parent $TestsDir

# Dot-source utils.ps1 for Write-Utf8NoBom and other helpers.
$UtilsPath = Join-Path $ProjectDir 'harness/lib/utils.ps1'
if (-not (Test-Path -LiteralPath $UtilsPath)) {
    Write-Host "utils.ps1 not found at $UtilsPath"
    exit 1
}
. $UtilsPath

# Create an isolated working directory (PowerShell-native equivalent of `mktemp -d`).
$SmokeDir = Join-Path ([System.IO.Path]::GetTempPath()) ("harness-smoke-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $SmokeDir -Force | Out-Null

# Trap-equivalent: print the directory location on exit (success or failure).
trap {
    Write-Host "Smoke test dir: $SmokeDir (not cleaned for inspection)"
    break
}

try {
    Write-Host "=== Smoke Test: Build a Hello World CLI ==="
    Write-Host "Working directory: $SmokeDir"
    Write-Host ""

    # Set up isolated project.
    Set-Location -LiteralPath $SmokeDir
    & git init -q
    if ($LASTEXITCODE -ne 0) { throw "git init failed" }
    & git config user.email 'test@test.com'
    if ($LASTEXITCODE -ne 0) { throw "git config user.email failed" }
    & git config user.name 'Smoke Test'
    if ($LASTEXITCODE -ne 0) { throw "git config user.name failed" }

    $readmePath = Join-Path $SmokeDir 'README.md'
    Write-Utf8NoBom -Path $readmePath -Value "# Smoke Test`n"

    & git add README.md
    if ($LASTEXITCODE -ne 0) { throw "git add failed" }
    & git commit -q -m 'initial'
    if ($LASTEXITCODE -ne 0) { throw "git commit failed" }

    # Copy harness assets into the isolated project.
    $srcHarness = Join-Path $ProjectDir 'harness'
    $dstHarness = Join-Path $SmokeDir 'harness'
    Copy-Item -LiteralPath $srcHarness -Destination $dstHarness -Recurse -Force

    $srcClaude = Join-Path $ProjectDir '.claude'
    if (Test-Path -LiteralPath $srcClaude) {
        $dstClaude = Join-Path $SmokeDir '.claude'
        Copy-Item -LiteralPath $srcClaude -Destination $dstClaude -Recurse -Force
    }

    $srcMcp = Join-Path $ProjectDir '.mcp.json'
    if (Test-Path -LiteralPath $srcMcp) {
        Copy-Item -LiteralPath $srcMcp -Destination (Join-Path $SmokeDir '.mcp.json') -Force
    }

    $srcClaudeMd = Join-Path $ProjectDir 'CLAUDE.md'
    if (Test-Path -LiteralPath $srcClaudeMd) {
        Copy-Item -LiteralPath $srcClaudeMd -Destination (Join-Path $SmokeDir 'CLAUDE.md') -Force
    }

    # `chmod +x` is a no-op on Windows; PowerShell scripts run via -File.

    # Run the harness.
    Write-Host "Starting harness (this may take 10-30 minutes)..."
    $startTime = Get-Date

    $orchestratePs1 = Join-Path $SmokeDir 'harness/orchestrate.ps1'
    $smokeLog = Join-Path $SmokeDir 'smoke-output.log'
    $promptText = "Build a hello world CLI tool in PowerShell that prints 'Hello, NAME' when given a name argument and 'Hello, World' with no arguments"

    # The .sh used `gtimeout`/`timeout`; on Windows we run without an external timer,
    # capturing combined stdout/stderr to the log via Tee-Object.
    & powershell -NoProfile -File $orchestratePs1 `
        $promptText `
        --project-type cli-tool `
        --max-cost 50 2>&1 | Tee-Object -FilePath $smokeLog

    $endTime = Get-Date
    $elapsed = [int]([TimeSpan]($endTime - $startTime)).TotalSeconds
    Write-Host ""
    Write-Host ("Elapsed: {0}m {1}s" -f [math]::Floor($elapsed / 60), ($elapsed % 60))

    # ---------- Assertions ----------
    Write-Host ""
    Write-Host "=== Assertions ==="
    $script:Pass = 0
    $script:Fail = 0

    function Assert-That {
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

    Assert-That "product-spec.md exists and is >100 bytes" {
        $p = 'harness-state/product-spec.md'
        (Test-Path -LiteralPath $p -PathType Leaf) -and ((Get-Item -LiteralPath $p).Length -gt 100)
    }

    Assert-That "sprint-plan.json is valid JSON with sprints" {
        & jq -e '.sprints | length > 0' 'harness-state/sprint-plan.json' | Out-Null
        $LASTEXITCODE -eq 0
    }

    Assert-That "At least one eval report exists" {
        $reports = @(Get-ChildItem -Path 'harness-state/sprints' -Filter 'eval-report.json' -Recurse -File -ErrorAction SilentlyContinue)
        $reports.Count -gt 0
    }

    Assert-That "At least one sprint PASS in eval reports" {
        $reports = @(Get-ChildItem -Path 'harness-state/sprints' -Filter 'eval-report.json' -Recurse -File -ErrorAction SilentlyContinue)
        $found = $false
        foreach ($r in $reports) {
            $val = & jq -r '.overallResult // .result' $r.FullName 2>$null
            if ($LASTEXITCODE -eq 0 -and ($val -match 'PASS')) { $found = $true; break }
        }
        $found
    }

    Assert-That "Harness git tag exists" {
        $tags = & git tag
        ($tags | Where-Object { $_ -match 'harness/' } | Measure-Object).Count -gt 0
    }

    Assert-That "Harness branch exists" {
        $branches = & git branch
        ($branches | Where-Object { $_ -match 'harness/' } | Measure-Object).Count -gt 0
    }

    Assert-That "handoff.json has completedSprints" {
        & jq -e '.completedSprints | length > 0' 'harness-state/handoff.json' | Out-Null
        $LASTEXITCODE -eq 0
    }

    Assert-That "cost-log.json exists" {
        Test-Path -LiteralPath 'harness-state/cost-log.json' -PathType Leaf
    }

    Assert-That "progress.md contains PASS" {
        $p = 'harness-state/progress.md'
        (Test-Path -LiteralPath $p -PathType Leaf) -and (Select-String -LiteralPath $p -Pattern 'PASS' -SimpleMatch -Quiet)
    }

    Write-Host ""
    Write-Host ("=== Results: {0} passed, {1} failed ===" -f $script:Pass, $script:Fail)

    if ($script:Fail -gt 0) {
        Write-Host "Smoke test output saved to: $smokeLog"
        Write-Host "Smoke test dir: $SmokeDir (not cleaned for inspection)"
        exit 1
    }

    Write-Host "Smoke test dir: $SmokeDir (not cleaned for inspection)"
    exit 0
} catch {
    Write-Host "Smoke test dir: $SmokeDir (not cleaned for inspection)"
    throw
}
