#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Harness Orchestrator (PowerShell port of orchestrate.sh)
#
# Coordinates the Planner-Generator-Evaluator pipeline for building software
# through structured sprint cycles with context resets.
#
# Usage:
#   powershell -NoProfile -File harness/orchestrate.ps1 "Build a kanban board" [options]
#   powershell -NoProfile -File harness/orchestrate.ps1 --extend "Add collaboration features"
#   powershell -NoProfile -File harness/orchestrate.ps1 --fix "Cards vanish on rapid drag"
#   powershell -NoProfile -File harness/orchestrate.ps1 --refactor "Extract state into Zustand"
#   powershell -NoProfile -File harness/orchestrate.ps1 --resume --from-sprint 4
#   powershell -NoProfile -File harness/orchestrate.ps1 --regression
#
# Options:
#   --project-type TYPE   web-frontend|backend-api|cli-tool|general (default: general)
#   --context-strategy S  reset|compact (default: reset)
#   --model MODEL         opus|sonnet (default: opus)
#   --max-cost DOLLARS    Total cost cap (default: 200)
#   --from-sprint N       Start/resume from sprint N
#   --extend PROMPT       Add features to existing project
#   --fix DESCRIPTION     Fix a specific bug
#   --refactor DESC       Refactor without behavior change
#   --regression          Run all prior evaluations
#   --resume              Resume a partially completed run
#   --dry-run             Show what would happen without executing
#   --help, -h            Show this usage and exit

# ----------------------------------------------------------------------------
# Path setup -- mirrors `SCRIPT_DIR` and `HARNESS_ROOT` from orchestrate.sh
# ----------------------------------------------------------------------------

$script:ScriptDir   = $PSScriptRoot
$script:HarnessRoot = (Resolve-Path (Join-Path $script:ScriptDir '..')).Path
$env:HARNESS_ROOT   = $script:HarnessRoot

# ----------------------------------------------------------------------------
# Dot-source libraries (mirrors the .sh `source ...` lines, same order)
# ----------------------------------------------------------------------------

. (Join-Path $PSScriptRoot 'lib/utils.ps1')
. (Join-Path $PSScriptRoot 'lib/invoke.ps1')
. (Join-Path $PSScriptRoot 'lib/git.ps1')
. (Join-Path $PSScriptRoot 'lib/planner.ps1')
. (Join-Path $PSScriptRoot 'lib/contract.ps1')
. (Join-Path $PSScriptRoot 'lib/generator.ps1')
. (Join-Path $PSScriptRoot 'lib/evaluator.ps1')

# ----------------------------------------------------------------------------
# Defaults (mirroring orchestrate.sh)
# ----------------------------------------------------------------------------

$script:Mode               = 'new'
$script:UserPrompt         = ''
$script:ProjectType        = 'general'
$script:ContextStrategy    = 'reset'
$script:Model              = 'opus'
$script:TotalCostCap       = 200
$script:CostCapPerSprint   = 25
$script:MaxSprintAttempts  = 3
$script:MaxContractRounds  = 3
$script:FromSprint         = 1
$script:DryRun             = $false

# ----------------------------------------------------------------------------
# Help / argument parsing
# ----------------------------------------------------------------------------

function Show-Usage {
    $usage = @'
Harness Orchestrator -- Planner / Generator / Evaluator

Usage:
  powershell -NoProfile -File harness/orchestrate.ps1 "Project description" [options]
  powershell -NoProfile -File harness/orchestrate.ps1 --extend "New features"
  powershell -NoProfile -File harness/orchestrate.ps1 --fix "Bug description"
  powershell -NoProfile -File harness/orchestrate.ps1 --refactor "Refactor description"
  powershell -NoProfile -File harness/orchestrate.ps1 --resume --from-sprint N
  powershell -NoProfile -File harness/orchestrate.ps1 --regression

Options:
  --project-type TYPE     web-frontend | backend-api | cli-tool | general (default: general)
  --context-strategy S    reset | compact (default: reset)
  --model MODEL           opus | sonnet (default: opus)
  --max-cost DOLLARS      Total cost cap (default: 200)
  --from-sprint N         Start/resume from sprint N
  --extend PROMPT         Add features to existing project
  --fix DESCRIPTION       Fix a specific bug
  --refactor DESCRIPTION  Refactor without behavior change
  --regression            Run all prior evaluations
  --resume                Resume a partially completed run
  --dry-run               Show what would happen without executing
  --help, -h              Show this usage and exit
'@
    [Console]::Out.WriteLine($usage)
}

# Argument parsing -- mirrors orchestrate.sh's `parse_args` case statement.
# Returns nothing; mutates the script-scope variables above.
function Read-CliArgs {
    param([string[]]$ArgList)

    if ($null -eq $ArgList) { return }

    $i = 0
    while ($i -lt $ArgList.Count) {
        $tok = $ArgList[$i]
        switch -CaseSensitive ($tok) {
            '--help'             { Show-Usage; exit 0 }
            '-h'                 { Show-Usage; exit 0 }
            '--extend' {
                if ($i + 1 -ge $ArgList.Count) { Write-LogError 'Missing value for --extend'; exit 1 }
                $script:Mode = 'extend'
                $script:UserPrompt = $ArgList[$i + 1]
                $i += 2
                continue
            }
            '--fix' {
                if ($i + 1 -ge $ArgList.Count) { Write-LogError 'Missing value for --fix'; exit 1 }
                $script:Mode = 'fix'
                $script:UserPrompt = $ArgList[$i + 1]
                $i += 2
                continue
            }
            '--refactor' {
                if ($i + 1 -ge $ArgList.Count) { Write-LogError 'Missing value for --refactor'; exit 1 }
                $script:Mode = 'refactor'
                $script:UserPrompt = $ArgList[$i + 1]
                $i += 2
                continue
            }
            '--regression'        { $script:Mode = 'regression'; $i += 1; continue }
            '--resume'            { $script:Mode = 'resume';     $i += 1; continue }
            '--project-type' {
                if ($i + 1 -ge $ArgList.Count) { Write-LogError 'Missing value for --project-type'; exit 1 }
                $script:ProjectType = $ArgList[$i + 1]
                $i += 2
                continue
            }
            '--context-strategy' {
                if ($i + 1 -ge $ArgList.Count) { Write-LogError 'Missing value for --context-strategy'; exit 1 }
                $script:ContextStrategy = $ArgList[$i + 1]
                $i += 2
                continue
            }
            '--model' {
                if ($i + 1 -ge $ArgList.Count) { Write-LogError 'Missing value for --model'; exit 1 }
                $script:Model = $ArgList[$i + 1]
                $i += 2
                continue
            }
            '--max-cost' {
                if ($i + 1 -ge $ArgList.Count) { Write-LogError 'Missing value for --max-cost'; exit 1 }
                $script:TotalCostCap = $ArgList[$i + 1]
                $i += 2
                continue
            }
            '--from-sprint' {
                if ($i + 1 -ge $ArgList.Count) { Write-LogError 'Missing value for --from-sprint'; exit 1 }
                [int]$parsed = 1
                if (-not [int]::TryParse([string]$ArgList[$i + 1], [ref]$parsed)) {
                    Write-LogError "Invalid value for --from-sprint: $($ArgList[$i + 1])"
                    exit 1
                }
                $script:FromSprint = $parsed
                $i += 2
                continue
            }
            '--dry-run'           { $script:DryRun = $true; $i += 1; continue }
            default {
                if ($tok.StartsWith('-')) {
                    Write-LogError "Unknown option: $tok"
                    exit 1
                }
                $script:UserPrompt = $tok
                $i += 1
            }
        }
    }

    # Validate
    if ($script:Mode -eq 'new' -and [string]::IsNullOrEmpty($script:UserPrompt)) {
        Write-LogError 'Usage: powershell -NoProfile -File harness/orchestrate.ps1 "Your project description" [options]'
        exit 1
    }
}

# Propagate cap defaults to env so the libs that read env (Initialize-HarnessState,
# Invoke-ContractNegotiation) pick them up. Mirrors how the .sh inherits these via shell vars.
function Set-EnvDefaults {
    $env:CONTEXT_STRATEGY    = "$script:ContextStrategy"
    $env:MODEL               = "$script:Model"
    $env:MAX_SPRINT_ATTEMPTS = "$script:MaxSprintAttempts"
    $env:MAX_CONTRACT_ROUNDS = "$script:MaxContractRounds"
    $env:COST_CAP_PER_SPRINT = "$script:CostCapPerSprint"
    $env:TOTAL_COST_CAP      = "$script:TotalCostCap"
}

# Ensure .claude/agents/ and .claude/skills/ exist in cwd
# (mirrors the .sh block that uses cp -rn + grep on .gitignore).
function Initialize-ClaudeWorkspace {
    $rootClaude = Join-Path $script:HarnessRoot '.claude'
    if (-not (Test-Path -LiteralPath $rootClaude -PathType Container)) { return }

    $cwdClaude = Join-Path (Get-Location) '.claude'
    New-Item -ItemType Directory -Path $cwdClaude -Force | Out-Null

    foreach ($subdir in @('agents', 'skills')) {
        $src = Join-Path $rootClaude $subdir
        $dst = Join-Path $cwdClaude $subdir
        if (Test-Path -LiteralPath $src -PathType Container) {
            if (-not (Test-Path -LiteralPath $dst -PathType Container)) {
                # cp -rn equivalent: copy only when destination doesn't exist.
                Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }

    # Ensure harness infrastructure is gitignored in the target repo.
    $gitignore = Join-Path (Get-Location) '.gitignore'
    $needsAppend = $true
    if (Test-Path -LiteralPath $gitignore -PathType Leaf) {
        $existing = Get-Content -LiteralPath $gitignore -Raw -ErrorAction SilentlyContinue
        if ($existing -and $existing.Contains('.claude/agents/')) {
            $needsAppend = $false
        }
    }
    if ($needsAppend) {
        $block = "`n# Harness infrastructure (not project code)`n.claude/agents/`n.claude/skills/`n"
        Write-Utf8NoBom -Path $gitignore -Value $block -Append
    }
}

# ----------------------------------------------------------------------------
# Sprint cycle
# ----------------------------------------------------------------------------

# Run a single sprint cycle: contract -> implement -> evaluate
# Returns 0 on success, 1 on exhausted attempts, 2 on blocked generator.
function Invoke-SprintCycle {
    param(
        [Parameter(Mandatory)][int]$SprintNumber,
        [Parameter(Mandatory)][string]$HarnessBranch
    )

    $dir    = Get-SprintDirectory -SprintNumber $SprintNumber
    $padded = Format-SprintNumber  -SprintNumber $SprintNumber

    $planPath = Join-Path $script:HarnessState 'sprint-plan.json'
    $idx = $SprintNumber - 1
    $sprintName = Read-JsonField -File $planPath -Field ".sprints[$idx] | .name // .title // `"Sprint $SprintNumber`""
    if ([string]::IsNullOrEmpty($sprintName)) { $sprintName = "Sprint $SprintNumber" }

    Write-LogPhase "SPRINT ${padded}: ${sprintName}"

    New-Item -ItemType Directory -Path $dir -Force | Out-Null

    # Contract negotiation (if no contract exists)
    $contractFile = Join-Path $dir 'contract.json'
    if (-not (Test-FileNonEmpty -Path $contractFile)) {
        Invoke-ContractNegotiation -SprintNumber $SprintNumber
        Save-HarnessState -Message "harness(contract): sprint-$padded agreed"
    } else {
        Write-LogInfo 'Contract already exists, skipping negotiation'
    }

    # Implementation + evaluation loop
    $maxAttempts = $script:MaxSprintAttempts

    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        Write-LogInfo "Attempt $attempt/$maxAttempts"

        # Create sprint branch
        $sprintBranch = New-SprintBranch -HarnessBranch $HarnessBranch -SprintNumber $SprintNumber
        $null = $sprintBranch  # capture for clarity; not used below

        # Generator implements
        $genBlocked = $false
        $genFailed  = $false
        try {
            Invoke-Generator -SprintNumber $SprintNumber -Attempt $attempt
        } catch {
            $genFailed = $true
            $statusFile = Join-Path $dir 'status.json'
            $genStatus = ''
            if (Test-FileNonEmpty -Path $statusFile) {
                try {
                    $genStatus = Read-JsonField -File $statusFile -Field '.status'
                } catch {
                    $genStatus = 'failed'
                }
            } else {
                $genStatus = 'failed'
            }
            if ($genStatus -eq 'blocked') {
                $genBlocked = $true
            }
        }

        if ($genFailed) {
            if ($genBlocked) {
                Write-LogError 'Generator is blocked. Aborting sprint.'
                Invoke-FailSprintAttempt -HarnessBranch $HarnessBranch -SprintNumber $SprintNumber -Attempt $attempt
                return 2
            }
            Invoke-FailSprintAttempt -HarnessBranch $HarnessBranch -SprintNumber $SprintNumber -Attempt $attempt
            continue
        }

        # Evaluator tests
        $evalPassed = $false
        try {
            Invoke-Evaluator -SprintNumber $SprintNumber -Attempt $attempt | Out-Null
            $evalPassed = $true
        } catch {
            $evalPassed = $false
        }

        if ($evalPassed) {
            # PASS: merge, tag, handoff
            $mergeSha = Merge-SprintBranch -HarnessBranch $HarnessBranch -SprintNumber $SprintNumber -Attempt $attempt
            $tag = "harness/sprint-$padded/pass"

            Update-Handoff -SprintNumber $SprintNumber -MergeSha $mergeSha -Tag $tag -HarnessBranch $HarnessBranch
            Update-Progress -SprintNumber $SprintNumber -Status 'PASS' -Attempt $attempt -MergeSha $mergeSha
            Update-RegressionRegistry -SprintNumber $SprintNumber
            Save-HarnessState -Message "harness(eval): sprint-$padded PASS"

            Write-LogSuccess "Sprint $padded PASSED on attempt $attempt"
            return 0
        } else {
            # FAIL: tag, delete branch, retry
            Invoke-FailSprintAttempt -HarnessBranch $HarnessBranch -SprintNumber $SprintNumber -Attempt $attempt
            Update-Progress -SprintNumber $SprintNumber -Status 'FAIL' -Attempt $attempt
            Write-LogWarn "Sprint $padded failed on attempt $attempt"
        }
    }

    Write-LogError "Sprint $padded failed all $maxAttempts attempts"
    Update-Progress -SprintNumber $SprintNumber -Status 'FAILED (all attempts exhausted)' -Attempt $maxAttempts
    Save-HarnessState -Message "harness(eval): sprint-$padded FAILED"
    return 1
}

# ----------------------------------------------------------------------------
# Modes
# ----------------------------------------------------------------------------

# Mode: new build
function Invoke-NewBuild {
    $projectSlug = ConvertTo-Slug -Value $script:UserPrompt

    Write-LogPhase 'HARNESS: NEW BUILD'
    Write-LogInfo "Project: $($script:UserPrompt)"
    Write-LogInfo "Slug: $projectSlug"
    Write-LogInfo "Type: $($script:ProjectType)"
    Write-LogInfo "Model: $($script:Model)"
    Write-LogInfo "Context strategy: $($script:ContextStrategy)"

    # Ensure we're in a git repo (auto-init for new projects)
    & git rev-parse --git-dir 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-LogInfo 'No git repo found. Initializing...'
        Invoke-NativeCommand -FilePath 'git' -Arguments @('init', '-q', '-b', 'main')
        $gitEmail = if ($env:GIT_EMAIL) { $env:GIT_EMAIL } else { 'harness@claude-harness.dev' }
        $gitName  = if ($env:GIT_NAME)  { $env:GIT_NAME }  else { 'Claude Harness' }
        Invoke-NativeCommand -FilePath 'git' -Arguments @('config', 'user.email', $gitEmail)
        Invoke-NativeCommand -FilePath 'git' -Arguments @('config', 'user.name',  $gitName)
        Write-Utf8NoBom -Path 'README.md' -Value "# $projectSlug`n"
        Invoke-NativeCommand -FilePath 'git' -Arguments @('add', 'README.md')
        Invoke-NativeCommand -FilePath 'git' -Arguments @('commit', '-q', '-m', 'initial commit')
    }

    # Initialize state
    Initialize-HarnessState -Prompt $script:UserPrompt -ProjectType $script:ProjectType

    # Create harness branch
    $harnessBranch = New-HarnessBranch -ProjectSlug $projectSlug

    # Initialize handoff.json with harness branch
    $handoffJson = @"
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
    "harnessBranch": "$harnessBranch",
    "latestTag": "",
    "latestMergeSha": "",
    "prNumbers": []
  }
}
"@
    $handoffPath = Join-Path $script:HarnessState 'handoff.json'
    Write-Utf8NoBom -Path $handoffPath -Value $handoffJson

    Save-HarnessState -Message "harness: initialize state for $projectSlug"

    # Plan
    $sprintCountStr = Invoke-Planner -Mode 'new'
    if ($sprintCountStr -is [array]) { $sprintCountStr = ($sprintCountStr -join '') }
    $sprintCountStr = "$sprintCountStr".Trim()
    [int]$sprintCount = 0
    if (-not [int]::TryParse($sprintCountStr, [ref]$sprintCount)) {
        $sprintCount = 0
    }
    Save-HarnessState -Message 'harness(plan): product spec and sprint plan'
    Invoke-NativeCommand -FilePath 'git' -Arguments @('tag', 'harness/plan')

    Write-LogInfo "Sprint plan: $sprintCount sprints"

    # Sprint loop
    $failedSprints = 0
    for ($sprintNum = $script:FromSprint; $sprintNum -le $sprintCount; $sprintNum++) {
        $rc = Invoke-SprintCycle -SprintNumber $sprintNum -HarnessBranch $harnessBranch
        if ($rc -ne 0) {
            $failedSprints++
            Write-LogWarn "Sprint $sprintNum failed. Continuing to next sprint."
        }
        Test-CostCap | Out-Null
    }

    # Generate README
    if ($failedSprints -eq 0) {
        Write-LogInfo 'Generating README...'
        try {
            Invoke-ClaudeAgent -Agent 'generator' -MaxTurns 30 -Prompt 'Read harness-state/product-spec.md for the product vision and features. Read harness-state/handoff.json for the tech stack and dev server command. Read harness-state/progress.md for what was built across sprints. Write a comprehensive README.md for this project covering: what it is, features, how to install and run (dev + build), tech stack, and project structure. Do NOT mention the harness or sprint process -- write it as a normal project README.' | Out-Null
        } catch {
            Write-LogWarn 'README generation invocation failed (continuing)'
        }
        if (Test-Path -LiteralPath 'README.md' -PathType Leaf) {
            Invoke-GitCapture -Args @('add', 'README.md') | Out-Null
        }
        Save-HarnessState -Message 'harness: generate README.md'
    }

    # Completion
    Write-LogPhase 'HARNESS COMPLETE'

    $prBody = Build-PRBody
    New-HarnessPR -HarnessBranch $harnessBranch -ProjectSlug $projectSlug -PrBody $prBody

    # If gh is not available, fall back to writing pr-body.md (matches spec note).
    if (-not (Test-CommandAvailable -Name 'gh')) {
        Write-Utf8NoBom -Path (Join-Path $script:HarnessState 'pr-body.md') -Value $prBody
    }

    if ($failedSprints -gt 0) {
        Write-LogWarn "$failedSprints sprint(s) failed. Review harness-state/progress.md for details."
    } else {
        Write-LogSuccess 'All sprints passed!'
    }
}

# Mode: extend existing project
function Invoke-Extend {
    Write-LogPhase 'HARNESS: EXTEND'
    Write-LogInfo "New features: $($script:UserPrompt)"

    $configPath = Join-Path $script:HarnessState 'config.json'
    if (-not (Test-FileNonEmpty -Path $configPath)) {
        Write-LogError 'No existing harness state found. Run a new build first.'
        exit 1
    }

    $handoffPath = Join-Path $script:HarnessState 'handoff.json'
    $harnessBranch = Read-JsonField -File $handoffPath -Field '.git.harnessBranch'
    Invoke-NativeCommand -FilePath 'git' -Arguments @('checkout', $harnessBranch)

    # Update config with new prompt -- jq pipeline + atomic move via temp file.
    $tmp = New-TemporaryFile
    try {
        $jqOut = & jq --arg prompt $script:UserPrompt '.userPrompt = $prompt' $configPath
        if ($LASTEXITCODE -ne 0) { throw 'jq failed to update config.json' }
        Write-Utf8NoBom -Path $tmp.FullName -Value (($jqOut -join "`n"))
        Move-Item -LiteralPath $tmp.FullName -Destination $configPath -Force
    } finally {
        if (Test-Path -LiteralPath $tmp.FullName) {
            Remove-Item -LiteralPath $tmp.FullName -Force -ErrorAction SilentlyContinue
        }
    }

    # Count completed sprints (those with a passing eval report)
    $completedSprints = 0
    $sprintsRoot = Join-Path $script:HarnessState 'sprints'
    if (Test-Path -LiteralPath $sprintsRoot -PathType Container) {
        $sprintDirs = Get-ChildItem -LiteralPath $sprintsRoot -Directory -Filter 'sprint-*' -ErrorAction SilentlyContinue
        foreach ($d in $sprintDirs) {
            $report = Join-Path $d.FullName 'eval-report.json'
            if (Test-FileNonEmpty -Path $report) {
                $result = Read-JsonField -File $report -Field '.overallResult'
                if ($result -eq 'PASS') {
                    $completedSprints++
                }
            }
        }
    }

    # Plan (extend mode)
    $totalSprintsStr = Invoke-Planner -Mode 'extend'
    if ($totalSprintsStr -is [array]) { $totalSprintsStr = ($totalSprintsStr -join '') }
    $totalSprintsStr = "$totalSprintsStr".Trim()
    [int]$totalSprints = 0
    if (-not [int]::TryParse($totalSprintsStr, [ref]$totalSprints)) {
        $totalSprints = 0
    }

    Save-HarnessState -Message 'harness(plan): extend with new features'

    $newStart    = $completedSprints + 1
    $sprintCount = $totalSprints - $completedSprints

    Write-LogInfo "Added $sprintCount new sprints ($newStart-$totalSprints)"

    # Run new sprints
    for ($sprintNum = $newStart; $sprintNum -le $totalSprints; $sprintNum++) {
        try {
            Invoke-SprintCycle -SprintNumber $sprintNum -HarnessBranch $harnessBranch | Out-Null
        } catch {
            # mirror `|| true`
        }
        Test-CostCap | Out-Null
    }

    Write-LogPhase 'EXTEND COMPLETE'
    $prBody = Build-PRBody
    $extendSlug = "extend-$(ConvertTo-Slug -Value $script:UserPrompt)"
    New-HarnessPR -HarnessBranch $harnessBranch -ProjectSlug $extendSlug -PrBody $prBody
    if (-not (Test-CommandAvailable -Name 'gh')) {
        Write-Utf8NoBom -Path (Join-Path $script:HarnessState 'pr-body.md') -Value $prBody
    }
}

# Mode: fix a bug
function Invoke-Fix {
    Write-LogPhase 'HARNESS: FIX'
    Write-LogInfo "Bug: $($script:UserPrompt)"

    $configPath = Join-Path $script:HarnessState 'config.json'
    if (-not (Test-FileNonEmpty -Path $configPath)) {
        Write-LogError 'No existing harness state found.'
        exit 1
    }

    $handoffPath = Join-Path $script:HarnessState 'handoff.json'
    $harnessBranch = Read-JsonField -File $handoffPath -Field '.git.harnessBranch'
    Invoke-NativeCommand -FilePath 'git' -Arguments @('checkout', $harnessBranch)

    # Create GitHub issue (capture issue number for PR)
    $issueBody = "## Reported behavior`n$($script:UserPrompt)`n`n## Harness tracking`nAutomated fix via harness."
    $issueNumber = New-HarnessIssue -Title "Bug: $($script:UserPrompt)" -Body $issueBody

    # Determine fix sprint number
    $fixCount = 0
    $sprintsRoot = Join-Path $script:HarnessState 'sprints'
    if (Test-Path -LiteralPath $sprintsRoot -PathType Container) {
        $existing = Get-ChildItem -LiteralPath $sprintsRoot -Directory -Filter 'fix-*' -ErrorAction SilentlyContinue
        if ($existing) { $fixCount = @($existing).Count }
    }
    $fixId = "fix-{0:D3}" -f ($fixCount + 1)
    $fixDir = Join-Path $sprintsRoot $fixId
    New-Item -ItemType Directory -Path $fixDir -Force | Out-Null

    # Generate fix contract via generator
    Write-LogInfo 'Generating fix contract...'
    $contractPrompt = "Create a fix contract for this bug: $($script:UserPrompt). Write a surgical contract with criteria that verify the fix AND regression criteria from related sprints. Write to harness-state/sprints/$fixId/contract.json."
    & claude -p $contractPrompt --agent generator --output-format json --max-turns 30 2>&1 | Out-Null

    # Run fix sprint -- create a sprint branch off the harness branch
    $sprintBranch = "$harnessBranch/$fixId"
    Invoke-NativeCommand -FilePath 'git' -Arguments @('checkout', '-b', $sprintBranch, $harnessBranch)

    # Generate fix
    $fixPrompt = "Fix this bug: $($script:UserPrompt). Read the contract at harness-state/sprints/$fixId/contract.json. Write your log to harness-state/sprints/$fixId/generator-log.md. Set status to ready-for-eval."
    & claude -p $fixPrompt --agent generator --output-format json --max-turns 100 2>&1 | Out-Null

    # Evaluate fix -- our Invoke-Evaluator only takes int sprint numbers; for a fix-id we
    # call the agent directly (mirrors `invoke_evaluator "${fix_id}" 1` in the .sh).
    $evalPrompt = "Evaluate fix $fixId. Read harness-state/sprints/$fixId/contract.json. Write the report to harness-state/sprints/$fixId/eval-report.json."
    $evalCode = Invoke-ClaudeAgent -Agent 'evaluator' -MaxTurns 100 -Prompt $evalPrompt

    $reportPath = Join-Path $fixDir 'eval-report.json'
    $passed = $false
    if ($evalCode -eq 0 -and (Test-FileNonEmpty -Path $reportPath)) {
        $verdict = Invoke-JqCapture -Filter '(.overallResult // .result // .verdict // $unk) | ascii_downcase' -InputFile $reportPath -ExtraArgs @('--arg', 'unk', 'UNKNOWN')
        $verdict = "$verdict".Trim()
        if ($verdict -eq 'pass' -or $verdict -eq 'passed') {
            $passed = $true
        }
    }

    if ($passed) {
        Invoke-NativeCommand -FilePath 'git' -Arguments @('tag', "harness/$fixId/pass")
        Save-HarnessState -Message "harness($fixId): fix verified"
        New-FixPR -FixBranch $sprintBranch -BaseBranch $harnessBranch -FixId $fixId -BugDescription $script:UserPrompt -IssueNumber $issueNumber
        Write-LogSuccess 'Fix verified -- PR created'
    } else {
        Write-LogError "Fix did not pass evaluation. See $fixDir/eval-report.json"
    }
}

# Mode: refactor
function Invoke-Refactor {
    Write-LogPhase 'HARNESS: REFACTOR'
    Write-LogInfo "Refactor: $($script:UserPrompt)"

    $handoffPath = Join-Path $script:HarnessState 'handoff.json'
    $harnessBranch = Read-JsonField -File $handoffPath -Field '.git.harnessBranch'
    Invoke-NativeCommand -FilePath 'git' -Arguments @('checkout', $harnessBranch)

    # Full regression before
    Write-LogInfo 'Running pre-refactor regression baseline...'
    try {
        Invoke-Regression
    } catch {
        Write-LogWarn 'Pre-refactor regression had failures'
    }

    # Generate refactor contract
    $refDir = Join-Path $script:HarnessState 'sprints/refactor-001'
    New-Item -ItemType Directory -Path $refDir -Force | Out-Null

    $refContractPrompt = "Create a refactor contract: $($script:UserPrompt). This must not change any behavior. Include ALL prior sprint criteria as regression tests. Write to harness-state/sprints/refactor-001/contract.json."
    & claude -p $refContractPrompt --agent generator --output-format json --max-turns 30 2>&1 | Out-Null

    # Implement refactor
    $sprintBranch = "$harnessBranch/refactor-001"
    Invoke-NativeCommand -FilePath 'git' -Arguments @('checkout', '-b', $sprintBranch, $harnessBranch)

    $refImplPrompt = "Implement this refactor: $($script:UserPrompt). Read the contract at harness-state/sprints/refactor-001/contract.json. Behavior MUST NOT change. Write log to harness-state/sprints/refactor-001/generator-log.md."
    & claude -p $refImplPrompt --agent generator --output-format json --max-turns 200 2>&1 | Out-Null

    # Full regression
    $evalOK = $false
    $evalPrompt = 'Evaluate refactor-001. Read harness-state/sprints/refactor-001/contract.json. Write the report to harness-state/sprints/refactor-001/eval-report.json.'
    $evalCode = Invoke-ClaudeAgent -Agent 'evaluator' -MaxTurns 100 -Prompt $evalPrompt
    $report = Join-Path $refDir 'eval-report.json'
    if ($evalCode -eq 0 -and (Test-FileNonEmpty -Path $report)) {
        $verdict = Invoke-JqCapture -Filter '(.overallResult // .result // .verdict // $unk) | ascii_downcase' -InputFile $report -ExtraArgs @('--arg', 'unk', 'UNKNOWN')
        $verdict = "$verdict".Trim()
        if ($verdict -eq 'pass' -or $verdict -eq 'passed') {
            $evalOK = $true
        }
    }

    $regressionOK = $false
    if ($evalOK) {
        try {
            Invoke-Regression
            $regressionOK = $true
        } catch {
            $regressionOK = $false
        }
    }

    if ($evalOK -and $regressionOK) {
        Invoke-NativeCommand -FilePath 'git' -Arguments @('checkout', $harnessBranch)
        Invoke-NativeCommand -FilePath 'git' -Arguments @('merge', '--no-ff', $sprintBranch, '-m', 'harness(refactor): merge (PASS, full regression)')
        Invoke-NativeCommand -FilePath 'git' -Arguments @('tag', 'harness/refactor-001/pass')
        Invoke-NativeCommand -FilePath 'git' -Arguments @('branch', '-d', $sprintBranch)
        Save-HarnessState -Message 'harness(refactor): verified with full regression'
        Write-LogSuccess 'Refactor complete with full regression pass'
    } else {
        Write-LogError 'Refactor failed regression. See eval reports.'
    }
}

# Mode: resume
function Invoke-Resume {
    Write-LogPhase "HARNESS: RESUME from sprint $($script:FromSprint)"

    $handoffPath = Join-Path $script:HarnessState 'handoff.json'
    if (-not (Test-Path -LiteralPath $handoffPath)) {
        Write-LogError 'No handoff.json found -- nothing to resume. Run without --resume to start a new project.'
        exit 1
    }
    $harnessBranch = Read-JsonField -File $handoffPath -Field '.git.harnessBranch'
    if ([string]::IsNullOrWhiteSpace($harnessBranch)) {
        Write-LogError 'handoff.json is missing .git.harnessBranch -- cannot determine which branch to resume.'
        exit 1
    }
    Invoke-NativeCommand -FilePath 'git' -Arguments @('checkout', $harnessBranch)

    $planPath = Join-Path $script:HarnessState 'sprint-plan.json'
    $totalSprintsStr = Read-JsonField -File $planPath -Field '.sprints | length'
    [int]$totalSprints = 0
    if (-not [int]::TryParse([string]$totalSprintsStr, [ref]$totalSprints)) {
        $totalSprints = 0
    }

    for ($sprintNum = $script:FromSprint; $sprintNum -le $totalSprints; $sprintNum++) {
        try {
            Invoke-SprintCycle -SprintNumber $sprintNum -HarnessBranch $harnessBranch | Out-Null
        } catch {
            # mirror `|| true`
        }
        Test-CostCap | Out-Null
    }

    Write-LogPhase 'RESUME COMPLETE'
    $configPath = Join-Path $script:HarnessState 'config.json'
    $userPrompt = Read-JsonField -File $configPath -Field '.userPrompt'
    if ([string]::IsNullOrWhiteSpace($userPrompt)) { $userPrompt = $harnessBranch }
    if ([string]::IsNullOrWhiteSpace($userPrompt)) { $userPrompt = 'harness-project' }
    $slug = ConvertTo-Slug -Value $userPrompt
    $prBody = Build-PRBody
    New-HarnessPR -HarnessBranch $harnessBranch -ProjectSlug $slug -PrBody $prBody
    if (-not (Test-CommandAvailable -Name 'gh')) {
        Write-Utf8NoBom -Path (Join-Path $script:HarnessState 'pr-body.md') -Value $prBody
    }
}

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

function Invoke-Main {
    param([string[]]$ArgList)

    Read-CliArgs -ArgList $ArgList

    if ($script:DryRun) {
        Write-LogInfo "DRY RUN -- would execute mode: $($script:Mode)"
        Write-LogInfo "Prompt: $($script:UserPrompt)"
        Write-LogInfo "Config: type=$($script:ProjectType) strategy=$($script:ContextStrategy) model=$($script:Model) maxcost=$($script:TotalCostCap)"
        exit 0
    }

    Set-EnvDefaults
    Initialize-ClaudeWorkspace

    $startTime = [DateTime]::UtcNow

    switch ($script:Mode) {
        'new'        { Invoke-NewBuild }
        'extend'     { Invoke-Extend }
        'fix'        { Invoke-Fix }
        'refactor'   { Invoke-Refactor }
        'resume'     { Invoke-Resume }
        'regression' { Invoke-Regression }
        default {
            Write-LogError "Unknown mode: $($script:Mode)"
            exit 1
        }
    }

    $endTime  = [DateTime]::UtcNow
    $duration = $endTime - $startTime
    $hours    = [int]$duration.TotalHours
    $minutes  = $duration.Minutes

    Write-LogPhase 'DONE'
    Write-LogInfo "Total time: ${hours}h ${minutes}m"
    Write-LogInfo "Cost log: $script:HarnessState/cost-log.json"
    Write-LogInfo "Progress: $script:HarnessState/progress.md"
}

Invoke-Main -ArgList $args
