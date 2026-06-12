#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Run the harness test suite (PowerShell port of tests/run-all.sh)
#
# Usage:
#   powershell -NoProfile -File tests/run-all.ps1                # Layer 1 only (default)
#   powershell -NoProfile -File tests/run-all.ps1 layer1         # Layer 1 explicitly
#   powershell -NoProfile -File tests/run-all.ps1 layer2         # Layer 2 smoke test (real Claude)
#   powershell -NoProfile -File tests/run-all.ps1 layer3         # Layer 3 meta test (real Claude)
#   powershell -NoProfile -File tests/run-all.ps1 all            # All three layers
#   powershell -NoProfile -File tests/run-all.ps1 --help         # Show usage and exit 0

# Parse arguments. Mirrors the .sh's positional `$1` plus an explicit --help flag
# (the .sh did not have --help; we add it here for parity with the other ports).
$ShowHelp = $false
$Layer = 'layer1'
if ($args.Count -gt 0) {
    foreach ($a in $args) {
        switch -Regex ($a) {
            '^(--help|-h|/\?)$' { $ShowHelp = $true }
            default              { $Layer = [string]$a }
        }
    }
}

function Show-Usage {
    Write-Host "Usage: powershell -NoProfile -File tests/run-all.ps1 [layer1|layer2|layer3|all|--help]"
    Write-Host ""
    Write-Host "  layer1   Run Layer 1 (unit/integration tests via bats; default)"
    Write-Host "  layer2   Run Layer 2 smoke test (requires HARNESS_SMOKE_TEST=1)"
    Write-Host "  layer3   Run Layer 3 meta test  (requires HARNESS_META_TEST=1)"
    Write-Host "  all      Run all three layers in sequence"
    Write-Host "  --help   Show this message and exit 0"
}

if ($ShowHelp) {
    Show-Usage
    exit 0
}

# Anchor to script location.
$ScriptDir  = Split-Path -Parent $PSCommandPath
$ProjectDir = Split-Path -Parent $ScriptDir

# Dot-source utils.ps1 for shared helpers (when present in a merged tree).
$UtilsPath = Join-Path $ProjectDir 'harness/lib/utils.ps1'
if (Test-Path -LiteralPath $UtilsPath) {
    . $UtilsPath
}

# Check for bats
$batsCmd = Get-Command bats -ErrorAction SilentlyContinue
if (-not $batsCmd) {
    Write-Host "bats-core not found."
    Write-Host "Install with:"
    Write-Host "  brew install bats-core"
    Write-Host "  npm install -g bats"
    exit 1
}

# Check for jq
$jqCmd = Get-Command jq -ErrorAction SilentlyContinue
if (-not $jqCmd) {
    Write-Host "jq not found. Install with: brew install jq"
    exit 1
}

function Invoke-Layer1 {
    Write-Host "=== Layer 1: Unit & Integration Tests (mocked Claude) ==="
    Write-Host ""
    $layer1Dir = Join-Path $ScriptDir 'layer1'
    $batsFiles = @(Get-ChildItem -LiteralPath $layer1Dir -Filter '*.bats' -File -ErrorAction SilentlyContinue |
                    ForEach-Object { $_.FullName })
    if ($batsFiles.Count -eq 0) {
        Write-Host "No .bats files found in $layer1Dir"
        return 1
    }
    & bats @batsFiles
    return $LASTEXITCODE
}

function Invoke-Layer2 {
    Write-Host "=== Layer 2: Smoke Test (Real Claude) ==="
    Write-Host ""
    if ($env:HARNESS_SMOKE_TEST -ne '1') {
        Write-Host "Skipped. Set HARNESS_SMOKE_TEST=1 to run (costs Claude usage)."
        return 0
    }
    $smokePs1 = Join-Path $ScriptDir 'layer2/smoke-test.ps1'
    & powershell -NoProfile -File $smokePs1
    return $LASTEXITCODE
}

function Invoke-Layer3 {
    Write-Host "=== Layer 3: Meta Test (Self-Referential) ==="
    Write-Host ""
    if ($env:HARNESS_META_TEST -ne '1') {
        Write-Host "Skipped. Set HARNESS_META_TEST=1 to run (costs significant Claude usage)."
        return 0
    }
    $metaPs1 = Join-Path $ScriptDir 'layer3/meta-test.ps1'
    & powershell -NoProfile -File $metaPs1
    return $LASTEXITCODE
}

$rc = 0
switch ($Layer) {
    'layer1'         { $rc = Invoke-Layer1 }
    '--layer1-only'  { $rc = Invoke-Layer1 }
    'layer2'         { $rc = Invoke-Layer2 }
    'layer3'         { $rc = Invoke-Layer3 }
    'all' {
        $rc = Invoke-Layer1
        if ($rc -ne 0) { exit $rc }
        Write-Host ""
        $rc = Invoke-Layer2
        if ($rc -ne 0) { exit $rc }
        Write-Host ""
        $rc = Invoke-Layer3
    }
    default {
        Write-Host "Unknown layer: $Layer"
        Write-Host "Usage: powershell -NoProfile -File tests/run-all.ps1 [layer1|layer2|layer3|all|--help]"
        exit 1
    }
}

if ($rc -ne 0) { exit $rc }

Write-Host ""
Write-Host "=== COMPLETE ==="
exit 0
