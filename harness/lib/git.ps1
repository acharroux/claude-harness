#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Git operations for the harness orchestrator (PowerShell port of git.sh)

# Dot-source utils so logging / sprint helpers are available.
. (Join-Path $PSScriptRoot 'utils.ps1')

# ----------------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------------

# Capture stdout from a git command without throwing on non-zero exit.
# Returns: [pscustomobject]@{ Output = string; ExitCode = int }
function Invoke-GitCapture {
    param([Parameter(Mandatory)][string[]]$Args)
    # PS 5.1: native-command stderr becomes a terminating NativeCommandError under
    # $ErrorActionPreference=Stop even with 2>$null. Temporarily lower the pref so
    # stderr is silently discarded, then restore it. $LASTEXITCODE is still set correctly.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'SilentlyContinue'
    $out = & git @Args 2>$null
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($null -eq $out) { $out = '' }
    if ($out -is [array]) { $out = ($out -join "`n") }
    return [pscustomobject]@{ Output = "$out"; ExitCode = $code }
}

# Determine the default base branch (origin/HEAD or fallback).
function Get-BaseBranch {
    $r = Invoke-GitCapture -Args @('symbolic-ref', 'refs/remotes/origin/HEAD')
    if ($r.ExitCode -eq 0 -and $r.Output) {
        $b = $r.Output.Trim() -replace '^refs/remotes/origin/', ''
        if ($b) { return $b }
    }
    return 'main'
}

function Test-GitRefExists {
    param([Parameter(Mandatory)][string]$Ref)
    $r = Invoke-GitCapture -Args @('rev-parse', '--verify', $Ref)
    return ($r.ExitCode -eq 0)
}

function Test-CommandAvailable {
    param([Parameter(Mandatory)][string]$Name)
    return [bool](Get-Command -Name $Name -ErrorAction SilentlyContinue)
}

# ----------------------------------------------------------------------------
# Public functions
# ----------------------------------------------------------------------------

# Create the harness branch from main (mirrors git_create_harness_branch)
function New-HarnessBranch {
    param([Parameter(Mandatory)][string]$ProjectSlug)

    $harnessBranch = "harness/$ProjectSlug"

    $baseBranch = Get-BaseBranch

    # If the resolved base branch doesn't exist locally, fall back to current branch or main.
    if (-not (Test-GitRefExists -Ref $baseBranch)) {
        $cur = Invoke-GitCapture -Args @('branch', '--show-current')
        if ($cur.ExitCode -eq 0 -and $cur.Output.Trim()) {
            $baseBranch = $cur.Output.Trim()
        } else {
            $baseBranch = 'main'
        }
    }

    Write-LogInfo "Creating harness branch: $harnessBranch from $baseBranch"

    # If branch already exists (e.g. resuming after a crash), just check it out.
    if (Test-GitRefExists -Ref $harnessBranch) {
        Write-LogInfo "Branch $harnessBranch already exists -- resuming"
        $r = Invoke-GitCapture -Args @('checkout', $harnessBranch)
        if ($r.ExitCode -ne 0) {
            throw "Failed to checkout existing harness branch: $harnessBranch"
        }
    } else {
        $r = Invoke-GitCapture -Args @('checkout', '-b', $harnessBranch, $baseBranch)
        if ($r.ExitCode -ne 0) {
            throw "Failed to create harness branch: $harnessBranch (exit $($r.ExitCode))"
        }
    }

    return $harnessBranch
}

# Create a sprint branch for the generator to work in (mirrors git_create_sprint_branch)
function New-SprintBranch {
    param(
        [Parameter(Mandatory)][string]$HarnessBranch,
        [Parameter(Mandatory)][int]$SprintNumber
    )

    $padded = Format-SprintNumber -SprintNumber $SprintNumber
    $sprintBranch = "$HarnessBranch-sprint-$padded"

    Write-LogInfo "Creating sprint branch: $sprintBranch"

    # Clean up any existing sprint branch (from a previous failed attempt)
    if (Test-GitRefExists -Ref $sprintBranch) {
        Invoke-GitCapture -Args @('branch', '-D', $sprintBranch) | Out-Null
    }

    Invoke-NativeCommand -FilePath 'git' -Arguments @('checkout', '-b', $sprintBranch, $HarnessBranch)

    return $sprintBranch
}

# Merge a sprint branch back to the harness branch on PASS (mirrors git_merge_sprint)
function Merge-SprintBranch {
    param(
        [Parameter(Mandatory)][string]$HarnessBranch,
        [Parameter(Mandatory)][int]$SprintNumber,
        [Parameter(Mandatory)][int]$Attempt
    )

    $padded = Format-SprintNumber -SprintNumber $SprintNumber
    $sprintBranch = "$HarnessBranch-sprint-$padded"

    Write-LogInfo "Merging sprint $padded to $HarnessBranch"

    # Commit any uncommitted changes on the sprint branch (evaluator may have written files)
    Invoke-GitCapture -Args @('add', '-A') | Out-Null
    $diff = Invoke-GitCapture -Args @('diff', '--cached', '--quiet')
    if ($diff.ExitCode -ne 0) {
        Invoke-GitCapture -Args @('commit', '-q', '-m', "harness(sprint-$padded): evaluator artifacts") | Out-Null
    }

    Invoke-NativeCommand -FilePath 'git' -Arguments @('checkout', $HarnessBranch)
    Invoke-NativeCommand -FilePath 'git' -Arguments @(
        'merge', '--no-ff', $sprintBranch,
        '-m', "harness(sprint-$padded): merge (PASS, attempt $Attempt)"
    )

    $headRef = Invoke-GitCapture -Args @('rev-parse', 'HEAD')
    $mergeSha = $headRef.Output.Trim()

    # Tag the merge point
    $tag = "harness/sprint-$padded/pass"
    Invoke-NativeCommand -FilePath 'git' -Arguments @('tag', $tag)
    Write-LogSuccess "Tagged: $tag"

    # Delete the sprint branch (merged)
    Invoke-NativeCommand -FilePath 'git' -Arguments @('branch', '-d', $sprintBranch)

    return $mergeSha
}

# Tag a failed sprint attempt for forensics, then delete the branch
# (mirrors git_fail_sprint_attempt)
function Invoke-FailSprintAttempt {
    param(
        [Parameter(Mandatory)][string]$HarnessBranch,
        [Parameter(Mandatory)][int]$SprintNumber,
        [Parameter(Mandatory)][int]$Attempt
    )

    $padded = Format-SprintNumber -SprintNumber $SprintNumber
    $sprintBranch = "$HarnessBranch-sprint-$padded"

    # Tag for forensics
    $tag = "harness/sprint-$padded/attempt-$Attempt"
    Invoke-GitCapture -Args @('tag', $tag) | Out-Null
    Write-LogWarn "Tagged failed attempt: $tag"

    # Stash any uncommitted changes from the failed attempt
    Invoke-GitCapture -Args @('stash', '-q') | Out-Null
    Invoke-NativeCommand -FilePath 'git' -Arguments @('checkout', $HarnessBranch)
    Invoke-GitCapture -Args @('stash', 'drop', '-q') | Out-Null
    Invoke-GitCapture -Args @('branch', '-D', $sprintBranch) | Out-Null
}

# Commit harness-state files (mirrors git_commit_harness_state)
function Save-HarnessState {
    param([Parameter(Mandatory)][string]$Message)

    Invoke-GitCapture -Args @('add', "$script:HarnessState/") | Out-Null
    Invoke-GitCapture -Args @('add', '-u', "$script:HarnessState/") | Out-Null

    $diff = Invoke-GitCapture -Args @('diff', '--cached', '--quiet')
    if ($diff.ExitCode -eq 0) {
        Write-LogInfo "No harness-state changes to commit"
        return
    }

    Invoke-NativeCommand -FilePath 'git' -Arguments @('commit', '-m', $Message)
}

# Create PR from harness branch to main (mirrors git_create_pr)
function New-HarnessPR {
    param(
        [Parameter(Mandatory)][string]$HarnessBranch,
        [Parameter(Mandatory)][string]$ProjectSlug,
        [Parameter(Mandatory)][string]$PrBody
    )

    if (-not (Test-CommandAvailable -Name 'gh')) {
        Write-LogWarn "gh CLI not found -- skipping PR creation"
        Write-LogInfo "Harness branch ready: $HarnessBranch"
        Write-LogInfo "Create PR manually: git push && gh pr create"
        return
    }

    $remote = Invoke-GitCapture -Args @('remote', 'get-url', 'origin')
    if ($remote.ExitCode -ne 0) {
        Write-LogWarn "No git remote configured -- skipping PR creation"
        Write-LogInfo "Harness branch ready: $HarnessBranch"
        return
    }

    Write-LogInfo "Pushing harness branch and creating PR..."
    Invoke-NativeCommand -FilePath 'git' -Arguments @('push', '-u', 'origin', $HarnessBranch)

    $baseBranch = Get-BaseBranch

    $prTitle = "harness: $ProjectSlug"
    if ($prTitle.Length -gt 256) {
        $prTitle = $prTitle.Substring(0, 253) + '...'
    }

    Invoke-NativeCommand -FilePath 'gh' -Arguments @(
        'pr', 'create',
        '--base', $baseBranch,
        '--head', $HarnessBranch,
        '--title', $prTitle,
        '--body', $PrBody
    )
}

# Create a PR for a fix branch (mirrors git_create_fix_pr)
function New-FixPR {
    param(
        [Parameter(Mandatory)][string]$FixBranch,
        [Parameter(Mandatory)][string]$BaseBranch,
        [Parameter(Mandatory)][string]$FixId,
        [Parameter(Mandatory)][string]$BugDescription,
        [string]$IssueNumber = ''
    )

    if (-not (Test-CommandAvailable -Name 'gh')) {
        Write-LogWarn "gh CLI not found -- skipping PR creation"
        Write-LogInfo "Fix branch ready: $FixBranch"
        Write-LogInfo "Create PR manually: git push && gh pr create"
        return
    }

    $remote = Invoke-GitCapture -Args @('remote', 'get-url', 'origin')
    if ($remote.ExitCode -ne 0) {
        Write-LogWarn "No git remote configured -- skipping PR creation"
        Write-LogInfo "Fix branch ready: $FixBranch"
        return
    }

    # If the base branch doesn't exist on the remote, fall back to default branch.
    $remoteHeads = Invoke-GitCapture -Args @('ls-remote', '--heads', 'origin', $BaseBranch)
    if ([string]::IsNullOrWhiteSpace($remoteHeads.Output)) {
        $fallback = Get-BaseBranch
        Write-LogWarn "Base branch '$BaseBranch' not found on remote, falling back to '$fallback'"
        $BaseBranch = $fallback
    }

    Write-LogInfo "Pushing fix branch and creating PR..."
    Invoke-NativeCommand -FilePath 'git' -Arguments @('push', '-u', 'origin', $FixBranch)
    Invoke-GitCapture -Args @('push', 'origin', "harness/$FixId/pass") | Out-Null

    $issueRef = ''
    if (-not [string]::IsNullOrEmpty($IssueNumber)) {
        $issueRef = "Fixes #$IssueNumber"
    }

    $prBody = @"
## Fix: $FixId

### Bug
$BugDescription

### Verification
- Fix evaluated and passed all criteria
- Regression registry updated
$issueRef

---
Built with the [Planner-Generator-Evaluator Harness](https://www.anthropic.com/engineering/harness-design-long-running-apps)
"@

    $shortBug = if ($BugDescription.Length -gt 50) { $BugDescription.Substring(0, 50) } else { $BugDescription }

    Invoke-NativeCommand -FilePath 'gh' -Arguments @(
        'pr', 'create',
        '--base', $BaseBranch,
        '--head', $FixBranch,
        '--title', "harness($FixId): $shortBug",
        '--body', $prBody
    )
}

# Create a GitHub issue for a bug fix; returns the issue number string
# (mirrors git_create_issue)
function New-HarnessIssue {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$Body
    )

    if (-not (Test-CommandAvailable -Name 'gh')) {
        Write-LogWarn "gh CLI not found -- skipping issue creation"
        return ''
    }

    $remote = Invoke-GitCapture -Args @('remote', 'get-url', 'origin')
    if ($remote.ExitCode -ne 0) {
        Write-LogWarn "No git remote configured -- skipping issue creation"
        return ''
    }

    $issueUrl = & gh issue create --title $Title --body $Body --label 'harness-fix,bug' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $issueUrl) {
        Write-LogWarn "Failed to create issue"
        return ''
    }

    if ($issueUrl -is [array]) { $issueUrl = ($issueUrl -join "`n") }
    $issueUrl = "$issueUrl".Trim()

    # Extract trailing digits from the URL
    $m = [regex]::Match($issueUrl, '(\d+)\s*$')
    if ($m.Success) {
        return $m.Groups[1].Value
    }
    return ''
}

# Generate PR body from harness state (mirrors generate_pr_body)
function Build-PRBody {
    $configPath = Join-Path $script:HarnessState 'config.json'
    $promptRaw  = Read-JsonField -File $configPath -Field '.userPrompt'
    if ($null -eq $promptRaw) { $promptRaw = '' }
    $projectName = if ($promptRaw.Length -gt 80) { $promptRaw.Substring(0, 80) } else { $promptRaw }

    $planPath = Join-Path $script:HarnessState 'sprint-plan.json'
    $countStr = Read-JsonField -File $planPath -Field '.sprints | length'
    $sprintCount = 0
    if (-not [string]::IsNullOrEmpty($countStr)) { [int]::TryParse($countStr, [ref]$sprintCount) | Out-Null }

    $rows = @()
    for ($i = 1; $i -le $sprintCount; $i++) {
        $padded = Format-SprintNumber -SprintNumber $i
        $dir = Get-SprintDirectory -SprintNumber $i
        $idx = $i - 1
        $name = Read-JsonField -File $planPath -Field ".sprints[$idx].name"
        $status = 'pending'
        $criteria = '-'
        $pass = '-'
        $fail = '-'
        $attempts = '-'

        $evalReport = Join-Path $dir 'eval-report.json'
        if (Test-FileNonEmpty -Path $evalReport) {
            $status   = Read-JsonField -File $evalReport -Field '.overallResult'
            $criteria = Read-JsonField -File $evalReport -Field '.passCount + .failCount'
            $pass     = Read-JsonField -File $evalReport -Field '.passCount'
            $fail     = Read-JsonField -File $evalReport -Field '.failCount'
            $attempts = Read-JsonField -File $evalReport -Field '.attempt'
        }

        $rows += "| $padded | $name | $status | $criteria | $pass | $fail | $attempts | - |"
    }

    $sprintRows = $rows -join "`n"

    $model            = Read-JsonField -File $configPath -Field '.model'
    $contextStrategy  = Read-JsonField -File $configPath -Field '.contextStrategy'
    $projectType      = Read-JsonField -File $configPath -Field '.projectType'

    return @"
## Harness: $projectName

### Sprint Results

| Sprint | Name | Status | Criteria | Pass | Fail | Attempts | Cost |
|--------|------|--------|----------|------|------|----------|------|
$sprintRows

### Configuration
- Model: $model
- Context strategy: $contextStrategy
- Project type: $projectType

---
Built with the [Planner-Generator-Evaluator Harness](https://www.anthropic.com/engineering/harness-design-long-running-apps)
"@
}
