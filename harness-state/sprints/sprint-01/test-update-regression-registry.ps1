$ErrorActionPreference = 'Stop'

# Self-contained regression test for Update-RegressionRegistry (the sprint-01 blocker).
. ./harness/lib/utils.ps1

$workdir = Join-Path $env:TEMP "harness-eval-fix-$([Guid]::NewGuid().ToString('N').Substring(0,8))"
New-Item -ItemType Directory -Force -Path $workdir | Out-Null
Push-Location $workdir
try {
    New-Item -ItemType Directory -Force -Path harness-state/regression | Out-Null
    New-Item -ItemType Directory -Force -Path harness-state/sprints/sprint-01 | Out-Null

    Write-Utf8NoBom -Path harness-state/regression/registry.json `
                    -Value '{"sprints":{},"lastFullRun":null}'
    Write-Utf8NoBom -Path harness-state/sprints/sprint-01/contract.json `
                    -Value '{"sprintId":"sprint-01","criteria":[{"id":"C1-01"},{"id":"C1-02"},{"id":"C1-03"}]}'

    $script:HarnessState = 'harness-state'
    Update-RegressionRegistry -SprintNumber 1

    $reg = Get-Content -Raw harness-state/regression/registry.json | ConvertFrom-Json
    $sprint1 = $reg.sprints.'1'
    if (-not $sprint1) { throw "FAIL: sprint key '1' missing" }
    $ids = @($sprint1.criteria)
    if ($ids -join ',' -ne 'C1-01,C1-02,C1-03') {
        throw "FAIL: criteria ids = '$($ids -join ',')' (expected 'C1-01,C1-02,C1-03')"
    }
    if ($sprint1.contractPath -ne 'sprints/sprint-01/contract.json') {
        throw "FAIL: contractPath = '$($sprint1.contractPath)'"
    }
    Write-Host "PASS: criteria=[$($ids -join ',')] contractPath=$($sprint1.contractPath)"
} finally {
    Pop-Location
    Remove-Item -Recurse -Force $workdir -ErrorAction SilentlyContinue
}
