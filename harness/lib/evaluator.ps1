#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Evaluator phase: invoke the evaluator agent to test a sprint
# (PowerShell port of evaluator.sh)

. (Join-Path $PSScriptRoot 'utils.ps1')
. (Join-Path $PSScriptRoot 'invoke.ps1')

function Invoke-Evaluator {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][int]$SprintNumber,
        [int]$Attempt = 1
    )

    $dir = Get-SprintDirectory -SprintNumber $SprintNumber
    $padded = Format-SprintNumber -SprintNumber $SprintNumber

    Write-LogInfo "Evaluator testing sprint $padded (attempt $Attempt)..."

    $configPath = Join-Path $script:HarnessState 'config.json'
    $projectType = Read-JsonField -File $configPath -Field '.projectType'

    $prompt = "Evaluate sprint $SprintNumber. Read the contract at harness-state/sprints/sprint-$padded/contract.json. Read harness-state/handoff.json for git branch info and dev server details. Use git diff to understand what changed. Start the dev server, test every criterion, run regression tests if the contract specifies regressionSprints, score the holistic dimensions for project type '$projectType'. Write your report to harness-state/sprints/sprint-$padded/eval-report.json and update status.json."

    # Inject design spec verification for web-frontend
    $designSpec = Join-Path $script:HarnessState 'design-spec.md'
    if ($projectType -eq 'web-frontend' -and (Test-FileNonEmpty -Path $designSpec)) {
        $prompt = "$prompt IMPORTANT: Read harness-state/design-spec.md and verify the implementation matches the design system. Design Quality and Originality scores are BLOCKING -- FAIL the sprint if Design Quality < 6 or Originality < 5."
    }

    # Build optional --mcp-config arg for web-frontend projects
    $extraArgs = @()
    if ($projectType -eq 'web-frontend' -and (Test-Path -LiteralPath '.mcp.json' -PathType Leaf)) {
        $extraArgs = @('--mcp-config', '.mcp.json')
    }

    if ($extraArgs.Count -gt 0) {
        $code = Invoke-ClaudeAgent -Agent 'evaluator' -MaxTurns 100 -Prompt $prompt @extraArgs
    } else {
        $code = Invoke-ClaudeAgent -Agent 'evaluator' -MaxTurns 100 -Prompt $prompt
    }

    if ($code -ne 0) {
        Write-LogError 'Evaluator invocation failed'
        throw 'Evaluator invocation failed'
    }

    # Verify outputs
    $reportPath = Join-Path $dir 'eval-report.json'
    if (-not (Test-FileNonEmpty -Path $reportPath)) {
        Write-LogError 'Evaluator did not produce eval-report.json'
        throw 'Evaluator did not produce eval-report.json'
    }

    # Tolerate many field name variations and case differences from real Claude
    $result = Invoke-JqCapture -Filter '(.overallResult // .result // .verdict // $unk) | ascii_downcase' -InputFile $reportPath -ExtraArgs @('--arg', 'unk', 'UNKNOWN')
    $result = "$result".Trim()

    $passCount = & jq -r '.passCount // .pass_count // .score.passedCriteria // .score.passed // 0' $reportPath 2>$null
    if ($passCount -is [array]) { $passCount = ($passCount -join '') }
    $passCount = "$passCount".Trim()

    $failCount = & jq -r '.failCount // .fail_count // .score.failedCriteria // .score.failed // 0' $reportPath 2>$null
    if ($failCount -is [array]) { $failCount = ($failCount -join '') }
    $failCount = "$failCount".Trim()

    $blocking = & jq -r '.blockingFailures // .blocking_failures // .score.blocking // 0' $reportPath 2>$null
    if ($blocking -is [array]) { $blocking = ($blocking -join '') }
    $blocking = "$blocking".Trim()

    if ($result -eq 'pass' -or $result -eq 'passed') {
        Write-LogSuccess "Sprint $padded PASSED ($passCount pass, $failCount fail, $blocking blocking)"
        return 0
    } else {
        Write-LogWarn "Sprint $padded FAILED ($passCount pass, $failCount fail, $blocking blocking)"
        $summary = Read-JsonField -File $reportPath -Field '.summary'
        if ($null -ne $summary) {
            $summaryStr = "$summary"
            if ($summaryStr.Length -gt 300) { $summaryStr = $summaryStr.Substring(0, 300) }
            Write-LogWarn "Summary: $summaryStr"
        }
        throw "Sprint $padded evaluation failed"
    }
}

# Run regression tests against all prior sprints (mirrors invoke_regression).
function Invoke-Regression {
    [CmdletBinding()]
    param()

    Write-LogPhase 'REGRESSION TEST'

    $configPath = Join-Path $script:HarnessState 'config.json'
    $projectType = Read-JsonField -File $configPath -Field '.projectType'

    $prompt = 'Run regression tests. Read harness-state/regression/registry.json for all prior sprint criteria. For each sprint in the registry, load its contract and test the listed blocking criteria. Start the dev server and test the running application. Write results to harness-state/regression/last-run.json.'

    $extraArgs = @()
    if ($projectType -eq 'web-frontend' -and (Test-Path -LiteralPath '.mcp.json' -PathType Leaf)) {
        $extraArgs = @('--mcp-config', '.mcp.json')
    }

    if ($extraArgs.Count -gt 0) {
        $code = Invoke-ClaudeAgent -Agent 'evaluator' -MaxTurns 100 -Prompt $prompt @extraArgs
    } else {
        $code = Invoke-ClaudeAgent -Agent 'evaluator' -MaxTurns 100 -Prompt $prompt
    }

    if ($code -ne 0) {
        Write-LogError 'Regression test invocation failed'
        throw 'Regression test invocation failed'
    }

    $lastRun = Join-Path $script:HarnessState 'regression/last-run.json'
    if (Test-FileNonEmpty -Path $lastRun) {
        $totalPass = Read-JsonField -File $lastRun -Field '.pass'
        if ([string]::IsNullOrEmpty($totalPass)) { $totalPass = '0' }
        $totalFail = Read-JsonField -File $lastRun -Field '.fail'
        if ([string]::IsNullOrEmpty($totalFail)) { $totalFail = '0' }

        $failNum = 0
        [int]::TryParse($totalFail, [ref]$failNum) | Out-Null

        if ($failNum -gt 0) {
            Write-LogError "Regression FAILED: $totalPass pass, $totalFail fail"
            throw "Regression FAILED: $totalPass pass, $totalFail fail"
        } else {
            Write-LogSuccess "Regression PASSED: $totalPass pass, $totalFail fail"
        }
    }
}
