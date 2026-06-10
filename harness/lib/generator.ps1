#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Generator phase: invoke the generator agent to implement a sprint
# (PowerShell port of generator.sh)

. (Join-Path $PSScriptRoot 'utils.ps1')
. (Join-Path $PSScriptRoot 'invoke.ps1')

function Invoke-Generator {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][int]$SprintNumber,
        [int]$Attempt = 1
    )

    $dir = Get-SprintDirectory -SprintNumber $SprintNumber
    $padded = Format-SprintNumber -SprintNumber $SprintNumber

    Write-LogInfo "Generator implementing sprint $padded (attempt $Attempt)..."

    $prompt = "Implement sprint $SprintNumber. Read the contract at harness-state/sprints/sprint-$padded/contract.json. Read harness-state/handoff.json for current project state and harness-state/progress.md for history."

    if ($Attempt -gt 1) {
        $evalReport = Join-Path $dir 'eval-report.json'
        if (Test-FileNonEmpty -Path $evalReport) {
            $prompt = "$prompt This is retry attempt $Attempt. Read the evaluator's failure report at harness-state/sprints/sprint-$padded/eval-report.json and fix every blocking failure."
        }
    }

    # Inject design spec reference for web-frontend projects
    $designSpec = Join-Path $script:HarnessState 'design-spec.md'
    if (Test-FileNonEmpty -Path $designSpec) {
        $prompt = "$prompt IMPORTANT: Read harness-state/design-spec.md and follow the design system exactly -- colors, typography, spacing, component patterns. Do not use library defaults."
    }

    $prompt = "$prompt When done, write your work log to harness-state/sprints/sprint-$padded/generator-log.md and set harness-state/sprints/sprint-$padded/status.json to {`"status`": `"ready-for-eval`", `"attempt`": $Attempt}."

    $code = Invoke-ClaudeAgent -Agent 'generator' -MaxTurns 200 -Prompt $prompt
    if ($code -ne 0) {
        Write-LogError 'Generator invocation failed'
        throw 'Generator invocation failed'
    }

    # Verify outputs
    $statusPath = Join-Path $dir 'status.json'
    if (-not (Test-FileNonEmpty -Path $statusPath)) {
        Write-LogError 'Generator did not produce status.json'
        throw 'Generator did not produce status.json'
    }

    $status = Read-JsonField -File $statusPath -Field '.status'

    if ($status -eq 'blocked') {
        Write-LogError "Generator is blocked. See $dir/generator-log.md"
        # Mirror .sh `return 2`
        $err = [System.Management.Automation.ErrorRecord]::new(
            [System.Exception]::new('Generator is blocked'),
            'GeneratorBlocked',
            [System.Management.Automation.ErrorCategory]::OperationStopped,
            $null
        )
        $global:LASTEXITCODE = 2
        throw $err
    }

    if ($status -ne 'ready-for-eval') {
        Write-LogWarn "Generator status is '$status', expected 'ready-for-eval'"
    }

    Write-LogSuccess "Generator completed sprint $padded (attempt $Attempt)"
}
