#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Planner phase: invoke the planner agent to produce product spec and sprint plan
# (PowerShell port of planner.sh)

. (Join-Path $PSScriptRoot 'utils.ps1')
. (Join-Path $PSScriptRoot 'invoke.ps1')

function Invoke-Planner {
    [CmdletBinding()]
    param(
        [string]$Mode = 'new'  # "new" or "extend"
    )

    Write-LogPhase "PLANNER PHASE ($Mode)"

    if ($Mode -eq 'extend') {
        $prompt = 'You are extending an existing project. Read harness-state/product-spec.md, harness-state/handoff.json, and harness-state/sprint-plan.json to understand what exists. Then read harness-state/config.json for the new feature request. Design additive sprints that build on the existing architecture. APPEND to product-spec.md and ADD new sprints to sprint-plan.json.'
    } else {
        $prompt = 'Read harness-state/config.json for the user prompt and project type. Produce a comprehensive product spec in harness-state/product-spec.md and sprint decomposition in harness-state/sprint-plan.json.'
    }

    Write-LogInfo 'Invoking planner...'

    $code = Invoke-ClaudeAgent -Agent 'planner' -MaxTurns 50 -Prompt $prompt
    if ($code -ne 0) {
        Write-LogError 'Planner invocation failed'
        throw 'Planner invocation failed'
    }

    # Verify outputs
    $specPath = Join-Path $script:HarnessState 'product-spec.md'
    if (-not (Test-FileNonEmpty -Path $specPath)) {
        Write-LogError 'Planner did not produce product-spec.md'
        throw 'Planner did not produce product-spec.md'
    }

    $planPath = Join-Path $script:HarnessState 'sprint-plan.json'
    if (-not (Test-FileNonEmpty -Path $planPath)) {
        Write-LogError 'Planner did not produce sprint-plan.json'
        throw 'Planner did not produce sprint-plan.json'
    }

    # Validate sprint-plan.json is valid JSON with sprints
    $sprintCount = & jq '.sprints | length' $planPath 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-LogError 'sprint-plan.json is not valid JSON'
        throw 'sprint-plan.json is not valid JSON'
    }
    if ($sprintCount -is [array]) { $sprintCount = ($sprintCount -join '') }
    $sprintCount = "$sprintCount".Trim()

    # Check for design spec on web-frontend projects
    $configPath = Join-Path $script:HarnessState 'config.json'
    $projectType = Read-JsonField -File $configPath -Field '.projectType'
    if ($projectType -eq 'web-frontend') {
        $designSpec = Join-Path $script:HarnessState 'design-spec.md'
        if (Test-FileNonEmpty -Path $designSpec) {
            Write-LogSuccess 'Design spec produced for web-frontend project'
        } else {
            Write-LogWarn 'Planner did not produce design-spec.md for web-frontend project'
        }
    }

    Write-LogSuccess "Planner produced spec with $sprintCount sprints"
    # Mirror the .sh `echo "$sprint_count"` -- write to stdout so callers can capture it.
    Write-Output $sprintCount
}
