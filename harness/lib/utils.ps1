#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Shared utilities for the harness orchestrator (PowerShell port of utils.sh)

# ANSI color codes for terminal output
$script:Red    = "$([char]27)[0;31m"
$script:Green  = "$([char]27)[0;32m"
$script:Yellow = "$([char]27)[1;33m"
$script:Blue   = "$([char]27)[0;34m"
$script:Cyan   = "$([char]27)[0;36m"
$script:Nc     = "$([char]27)[0m"

if (-not (Get-Variable -Name HarnessState -Scope Script -ErrorAction SilentlyContinue)) {
    $script:HarnessState = 'harness-state'
}

# ----------------------------------------------------------------------------
# Logging helpers (all write to stderr, mirroring .sh `>&2` behavior)
# ----------------------------------------------------------------------------

function Write-LogInfo {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Message)
    [Console]::Error.WriteLine("$($script:Blue)[harness]$($script:Nc) $($Message -join ' ')")
}

function Write-LogSuccess {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Message)
    [Console]::Error.WriteLine("$($script:Green)[harness]$($script:Nc) $($Message -join ' ')")
}

function Write-LogWarn {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Message)
    [Console]::Error.WriteLine("$($script:Yellow)[harness]$($script:Nc) $($Message -join ' ')")
}

function Write-LogError {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Message)
    [Console]::Error.WriteLine("$($script:Red)[harness]$($script:Nc) $($Message -join ' ')")
}

function Write-LogPhase {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Message)
    $bar = '-' * 51
    [Console]::Error.WriteLine('')
    [Console]::Error.WriteLine("$($script:Cyan)$bar$($script:Nc)")
    [Console]::Error.WriteLine("$($script:Cyan)  $($Message -join ' ')$($script:Nc)")
    [Console]::Error.WriteLine("$($script:Cyan)$bar$($script:Nc)")
    [Console]::Error.WriteLine('')
}

# ----------------------------------------------------------------------------
# External command wrapper -- mirrors `set -e` semantics for native commands.
# ----------------------------------------------------------------------------

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    # PS 5.1 converts native-command stderr into a terminating NativeCommandError
    # under $ErrorActionPreference = 'Stop', even when the command exits 0 (e.g.
    # `git checkout -b` printing "Switched to a new branch" on stderr).
    # Use try/catch and rely solely on $LASTEXITCODE for real failure detection.
    try {
        & $FilePath @Arguments
    } catch {
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
        }
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

function Stop-WithError {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Message)
    Write-LogError @Message
    throw ($Message -join ' ')
}

# ----------------------------------------------------------------------------
# Sprint helpers
# ----------------------------------------------------------------------------

# Pad sprint number to 2 digits (mirrors sprint_pad)
function Format-SprintNumber {
    param([Parameter(Mandatory)][int]$SprintNumber)
    return ('{0:D2}' -f $SprintNumber)
}

# Sprint directory path (mirrors sprint_dir)
function Get-SprintDirectory {
    param([Parameter(Mandatory)][int]$SprintNumber)
    $padded = Format-SprintNumber -SprintNumber $SprintNumber
    return (Join-Path $script:HarnessState (Join-Path 'sprints' "sprint-$padded"))
}

# Slugify a string for use in branch names (mirrors slugify)
function ConvertTo-Slug {
    param([Parameter(Mandatory)][string]$Value)
    $s = $Value.ToLower()
    $s = $s -replace '[^a-z0-9]', '-'
    $s = $s -replace '-+', '-'
    $s = $s -replace '^-', ''
    $s = $s -replace '-$', ''
    if ($s.Length -gt 50) { $s = $s.Substring(0, 50) }
    return $s
}

# ----------------------------------------------------------------------------
# JSON / file helpers (use jq for parity with .sh)
# ----------------------------------------------------------------------------

# Read a JSON field from a file (mirrors json_read)
function Read-JsonField {
    param(
        [Parameter(Mandatory)][string]$File,
        [Parameter(Mandatory)][string]$Field
    )
    try {
        $value = & jq -r $Field $File 2>$null
        if ($LASTEXITCODE -ne 0) { return '' }
        if ($null -eq $value) { return '' }
        # jq -r on a string with embedded newlines returns an array in PS; flatten to one string
        if ($value -is [array]) { return ($value -join ' ').Trim() }
        return [string]$value
    } catch {
        return ''
    }
}

# Check if a file exists and is non-empty (mirrors file_exists)
function Test-FileNonEmpty {
    param([Parameter(Mandatory)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $info = Get-Item -LiteralPath $Path
    return ($info.Length -gt 0)
}

# Write text content as UTF-8 without BOM
function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory, Position = 0)][string]$Path,
        [Parameter(Mandatory, Position = 1, ValueFromPipeline = $true)][AllowEmptyString()][string]$Value,
        [switch]$Append
    )
    $resolved = if ([System.IO.Path]::IsPathRooted($Path)) { $Path } else { Join-Path (Get-Location) $Path }
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    if ($Append) {
        [System.IO.File]::AppendAllText($resolved, $Value, $utf8NoBom)
    } else {
        [System.IO.File]::WriteAllText($resolved, $Value, $utf8NoBom)
    }
}

# ----------------------------------------------------------------------------
# Initialization / state
# ----------------------------------------------------------------------------

# Initialize harness-state directory with config (mirrors init_harness_state)
function Initialize-HarnessState {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [string]$ProjectType = 'general'
    )

    $regressionDir = Join-Path $script:HarnessState 'regression'
    $sprintsDir    = Join-Path $script:HarnessState 'sprints'
    New-Item -ItemType Directory -Path $regressionDir -Force | Out-Null
    New-Item -ItemType Directory -Path $sprintsDir    -Force | Out-Null

    # Read configuration overrides from environment (matching .sh defaults)
    $contextStrategy   = if ($env:CONTEXT_STRATEGY)    { $env:CONTEXT_STRATEGY }    else { 'reset' }
    $model             = if ($env:MODEL)               { $env:MODEL }               else { 'opus' }
    $maxSprintAttempts = if ($env:MAX_SPRINT_ATTEMPTS) { [int]$env:MAX_SPRINT_ATTEMPTS } else { 3 }
    $maxContractRounds = if ($env:MAX_CONTRACT_ROUNDS) { [int]$env:MAX_CONTRACT_ROUNDS } else { 3 }
    $costCapPerSprint  = if ($env:COST_CAP_PER_SPRINT) { [double]$env:COST_CAP_PER_SPRINT } else { 25.00 }
    $totalCostCap      = if ($env:TOTAL_COST_CAP)      { [double]$env:TOTAL_COST_CAP }      else { 200.00 }

    # JSON-encode the user prompt via jq (matches `echo "$prompt" | jq -Rs .`)
    $encodedPrompt = $Prompt | & jq -Rs .
    if ($LASTEXITCODE -ne 0) {
        throw "jq failed to encode prompt"
    }
    # jq emits a trailing newline; trim it
    $encodedPrompt = $encodedPrompt.TrimEnd("`r", "`n")

    $configJson = @"
{
  "userPrompt": $encodedPrompt,
  "projectType": "$ProjectType",
  "contextStrategy": "$contextStrategy",
  "model": "$model",
  "maxSprintAttempts": $maxSprintAttempts,
  "maxContractRounds": $maxContractRounds,
  "costCapPerSprint": $costCapPerSprint,
  "totalCostCap": $totalCostCap
}
"@
    $configPath = Join-Path $script:HarnessState 'config.json'
    Write-Utf8NoBom -Path $configPath -Value $configJson

    # Initialize cost log
    $costLogPath = Join-Path $script:HarnessState 'cost-log.json'
    Write-Utf8NoBom -Path $costLogPath -Value '{"invocations": [], "totalCost": 0}'

    # Initialize regression registry
    $registryPath = Join-Path $regressionDir 'registry.json'
    Write-Utf8NoBom -Path $registryPath -Value '{"sprints": {}, "lastFullRun": null}'

    # Initialize progress log
    $now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $progress = @"
# Harness Progress Log

**Project**: $Prompt
**Started**: $now
**Model**: $model
**Context strategy**: $contextStrategy

---

"@
    $progressPath = Join-Path $script:HarnessState 'progress.md'
    Write-Utf8NoBom -Path $progressPath -Value $progress
}

# ----------------------------------------------------------------------------
# Cost tracking
# ----------------------------------------------------------------------------

# Log cost for an invocation (mirrors log_cost / cost_append)
function Add-CostEntry {
    param(
        [Parameter(Mandatory)][string]$Role,
        [Parameter(Mandatory)][int]$Sprint,
        [Parameter(Mandatory)][string]$OutputJson
    )

    # Extract usage from claude output if available, default to 0 on failure
    $inputTokens = 0
    $outputTokens = 0
    try {
        $val = $OutputJson | & jq -r '.usage.input_tokens // 0' 2>$null
        if ($LASTEXITCODE -eq 0 -and $val) { $inputTokens = [int]$val }
    } catch { $inputTokens = 0 }
    try {
        $val = $OutputJson | & jq -r '.usage.output_tokens // 0' 2>$null
        if ($LASTEXITCODE -eq 0 -and $val) { $outputTokens = [int]$val }
    } catch { $outputTokens = 0 }

    $costFile = Join-Path $script:HarnessState 'cost-log.json'
    $now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")

    $entry = @"
{
  "role": "$Role",
  "sprint": $Sprint,
  "timestamp": "$now",
  "inputTokens": $inputTokens,
  "outputTokens": $outputTokens
}
"@

    # Append to cost log via jq, write atomically through a temp file
    $tmp = New-TemporaryFile
    try {
        $jqOut = & jq ".invocations += [$entry]" $costFile
        if ($LASTEXITCODE -ne 0) { throw "jq failed to append cost entry" }
        Write-Utf8NoBom -Path $tmp.FullName -Value (($jqOut -join "`n"))
        Move-Item -LiteralPath $tmp.FullName -Destination $costFile -Force
    } finally {
        if (Test-Path -LiteralPath $tmp.FullName) {
            Remove-Item -LiteralPath $tmp.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}

# Check if total cost exceeds cap (mirrors check_cost_cap)
function Test-CostCap {
    $configPath = Join-Path $script:HarnessState 'config.json'
    $totalCostCap = Read-JsonField -File $configPath -Field '.totalCostCap'
    $costLogPath = Join-Path $script:HarnessState 'cost-log.json'
    Write-LogInfo "Cost tracking: see $costLogPath for invocation details"
}

# ----------------------------------------------------------------------------
# Progress / handoff / regression registry updates
# ----------------------------------------------------------------------------

# Update progress.md with a sprint entry (mirrors update_progress)
function Update-Progress {
    param(
        [Parameter(Mandatory)][int]$SprintNumber,
        [Parameter(Mandatory)][string]$Status,
        [int]$Attempt = 1,
        [string]$MergeSha = ''
    )

    $padded = Format-SprintNumber -SprintNumber $SprintNumber
    $planPath = Join-Path $script:HarnessState 'sprint-plan.json'
    $idx = $SprintNumber - 1
    $sprintName = Read-JsonField -File $planPath -Field ".sprints[$idx] | .name // .title // `"Sprint $SprintNumber`""
    if ([string]::IsNullOrEmpty($sprintName)) { $sprintName = "Sprint $SprintNumber" }

    $now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $mergeLine = if ([string]::IsNullOrEmpty($MergeSha)) { '' } else { "- **Merge commit**: $MergeSha" }

    $entry = @"

## Sprint $padded`: $sprintName

- **Status**: $Status
- **Attempt**: $Attempt
- **Time**: $now
$mergeLine

"@

    $progressPath = Join-Path $script:HarnessState 'progress.md'
    Write-Utf8NoBom -Path $progressPath -Value $entry -Append
}

# Update handoff.json after a sprint completes (mirrors update_handoff)
function Update-Handoff {
    param(
        [Parameter(Mandatory)][int]$SprintNumber,
        [string]$MergeSha = '',
        [string]$Tag = '',
        [string]$HarnessBranch = ''
    )

    $handoffFile = Join-Path $script:HarnessState 'handoff.json'

    if (-not (Test-FileNonEmpty -Path $handoffFile)) {
        $init = @'
{
  "projectName": "",
  "completedSprints": [],
  "currentSprint": 1,
  "totalSprints": 0,
  "completedFeatures": [],
  "keyFiles": {},
  "techStack": {},
  "outstandingIssues": [],
  "devServerCommand": "",
  "devServerPort": 0,
  "git": {
    "harnessBranch": "",
    "latestTag": "",
    "latestMergeSha": "",
    "prNumbers": []
  }
}
'@
        Write-Utf8NoBom -Path $handoffFile -Value $init
    }

    # Build jq filter mirroring the .sh logic
    $filter = @'
.completedSprints += [$sprint] |
.completedSprints |= unique |
.currentSprint = ($sprint + 1) |
.git.latestTag = $tag |
.git.latestMergeSha = $sha |
(if $branch != "" then .git.harnessBranch = $branch else . end)
'@

    $tmp = New-TemporaryFile
    try {
        $jqOut = & jq `
            --argjson sprint $SprintNumber `
            --arg tag $Tag `
            --arg sha $MergeSha `
            --arg branch $HarnessBranch `
            $filter `
            $handoffFile
        if ($LASTEXITCODE -ne 0) { throw "jq failed to update handoff.json" }
        Write-Utf8NoBom -Path $tmp.FullName -Value (($jqOut -join "`n"))
        Move-Item -LiteralPath $tmp.FullName -Destination $handoffFile -Force
    } finally {
        if (Test-Path -LiteralPath $tmp.FullName) {
            Remove-Item -LiteralPath $tmp.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}

# Update regression registry with blocking criteria from a sprint
# (mirrors update_regression_registry)
function Update-RegressionRegistry {
    param([Parameter(Mandatory)][int]$SprintNumber)

    $contractPath = Join-Path (Get-SprintDirectory -SprintNumber $SprintNumber) 'contract.json'
    $registry = Join-Path $script:HarnessState 'regression/registry.json'

    if (-not (Test-FileNonEmpty -Path $contractPath)) {
        return
    }

    # Extract blocking criteria IDs as a compact JSON array (single line).
    # Write to a temp file and feed via --slurpfile to dodge two PS-on-Windows traps:
    #   (a) capturing pretty-printed jq output yields a string[] that splats into
    #       multiple argv slots when later passed as `--argjson <var>`;
    #   (b) even when collapsed to one line, PS 5.1 strips embedded "" from argv,
    #       so `--argjson criteria '["C1-01",...]'` loses its quoting and jq rejects it.
    $criteriaIdsCompact = (& jq -c '[.criteria[].id]' $contractPath) -join ''
    if ($LASTEXITCODE -ne 0) { throw "jq failed to extract criteria IDs" }

    $padded = Format-SprintNumber -SprintNumber $SprintNumber
    $relPath = "sprints/sprint-$padded/contract.json"

    $criteriaTmp = New-TemporaryFile
    $tmp = New-TemporaryFile
    try {
        Write-Utf8NoBom -Path $criteriaTmp.FullName -Value $criteriaIdsCompact

        $jqOut = & jq `
            --arg sprint "$SprintNumber" `
            --arg path $relPath `
            --slurpfile criteriaArr $criteriaTmp.FullName `
            '.sprints[$sprint] = {"criteria": $criteriaArr[0], "contractPath": $path}' `
            $registry
        if ($LASTEXITCODE -ne 0) { throw "jq failed to update registry.json" }
        Write-Utf8NoBom -Path $tmp.FullName -Value (($jqOut -join "`n"))
        Move-Item -LiteralPath $tmp.FullName -Destination $registry -Force
    } finally {
        if (Test-Path -LiteralPath $tmp.FullName) {
            Remove-Item -LiteralPath $tmp.FullName -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $criteriaTmp.FullName) {
            Remove-Item -LiteralPath $criteriaTmp.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}
