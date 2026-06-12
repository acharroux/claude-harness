#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Contract negotiation: generator proposes, evaluator reviews, iterate
# (PowerShell port of contract.sh)

. (Join-Path $PSScriptRoot 'utils.ps1')
. (Join-Path $PSScriptRoot 'invoke.ps1')

function Invoke-ContractNegotiation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][int]$SprintNumber
    )

    # Resolve max rounds: prefer env var (matches .sh ${MAX_CONTRACT_ROUNDS:-3}),
    # fall back to harness-state/config.json's maxContractRounds, then default 3.
    $maxRounds = 3
    if ($env:MAX_CONTRACT_ROUNDS) {
        [int]::TryParse($env:MAX_CONTRACT_ROUNDS, [ref]$maxRounds) | Out-Null
    } else {
        $configPath = Join-Path $script:HarnessState 'config.json'
        if (Test-FileNonEmpty -Path $configPath) {
            $cfgVal = Read-JsonField -File $configPath -Field '.maxContractRounds'
            if (-not [string]::IsNullOrWhiteSpace($cfgVal) -and $cfgVal -ne 'null') {
                [int]::TryParse($cfgVal, [ref]$maxRounds) | Out-Null
            }
        }
    }

    $dir = Get-SprintDirectory -SprintNumber $SprintNumber
    $padded = Format-SprintNumber -SprintNumber $SprintNumber

    Write-LogPhase "CONTRACT NEGOTIATION -- Sprint $padded"

    New-Item -ItemType Directory -Path $dir -Force | Out-Null

    $proposalPath = Join-Path $dir 'contract-proposal.json'
    $reviewPath   = Join-Path $dir 'contract-review.json'
    $contractPath = Join-Path $dir 'contract.json'

    for ($round = 1; $round -le $maxRounds; $round++) {
        Write-LogInfo "Round $round/$maxRounds"

        # Generator proposes
        Write-LogInfo 'Generator proposing contract...'
        $genPrompt = "Propose a sprint contract for sprint $SprintNumber. Read harness-state/product-spec.md and harness-state/sprint-plan.json for context. Read harness-state/handoff.json for current state. Write your proposal to harness-state/sprints/sprint-$padded/contract-proposal.json."

        if ($round -gt 1) {
            $genPrompt = "$genPrompt The evaluator has provided feedback in harness-state/sprints/sprint-$padded/contract-review.json. Address all feedback in your revised proposal."
        }

        $code = Invoke-ClaudeAgent -Agent 'generator' -MaxTurns 30 -Prompt $genPrompt
        if ($code -ne 0) {
            Write-LogError 'Generator contract proposal failed'
            throw 'Generator contract proposal failed'
        }

        if (-not (Test-FileNonEmpty -Path $proposalPath)) {
            Write-LogError 'Generator did not produce contract-proposal.json'
            throw 'Generator did not produce contract-proposal.json'
        }

        # Tolerate different structures: .criteria[], .features[].acceptanceCriteria[], or flat .acceptanceCriteria[]
        $criteriaFilter = @'
if .criteria then (.criteria | length)
elif .features then [.features[].acceptanceCriteria // .features[].criteria // [] | length] | add // 0
elif .acceptanceCriteria then (.acceptanceCriteria | length)
else 0 end
'@
        $criteriaCount = & jq $criteriaFilter $proposalPath 2>$null
        if ($LASTEXITCODE -ne 0) { $criteriaCount = '0' }
        if ($criteriaCount -is [array]) { $criteriaCount = ($criteriaCount -join '') }
        $criteriaCount = "$criteriaCount".Trim()
        Write-LogInfo "Proposal: $criteriaCount criteria"

        # Evaluator reviews
        Write-LogInfo 'Evaluator reviewing contract...'
        $reviewPrompt = "Review the sprint contract proposal at harness-state/sprints/sprint-$padded/contract-proposal.json. Check that criteria are testable, complete, and cover the sprint's features from the sprint plan. Write your review to harness-state/sprints/sprint-$padded/contract-review.json."
        $code = Invoke-ClaudeAgent -Agent 'evaluator' -MaxTurns 30 -Prompt $reviewPrompt
        if ($code -ne 0) {
            Write-LogError 'Evaluator contract review failed'
            throw 'Evaluator contract review failed'
        }

        if (-not (Test-FileNonEmpty -Path $reviewPath)) {
            Write-LogError 'Evaluator did not produce contract-review.json'
            throw 'Evaluator did not produce contract-review.json'
        }

        # Tolerate: .decision, .reviewVerdict, .verdict -- and "accepted", "accept", "approved"
        $decision = & jq -r '(.decision // .reviewVerdict // .verdict // "unknown") | ascii_downcase' $reviewPath 2>$null
        if ($decision -is [array]) { $decision = ($decision -join '') }
        $decision = "$decision".Trim()

        if ($decision -eq 'accepted' -or $decision -eq 'accept' -or $decision -eq 'approved' -or $decision -eq 'approve') {
            Copy-Item -LiteralPath $proposalPath -Destination $contractPath -Force
            Write-LogSuccess "Contract agreed (round $round, $criteriaCount criteria)"
            return
        }

        $feedback = & jq -r '.feedback // .verdictReason // .reason // .comments // "no feedback provided"' $reviewPath 2>$null
        if ($feedback -is [array]) { $feedback = ($feedback -join '') }
        $feedbackStr = "$feedback"
        if ($feedbackStr.Length -gt 200) { $feedbackStr = $feedbackStr.Substring(0, 200) }
        Write-LogWarn "Evaluator requested revisions: $feedbackStr"
    }

    # Max rounds reached -- accept the latest proposal
    Write-LogWarn 'Max negotiation rounds reached. Accepting latest proposal.'
    Copy-Item -LiteralPath $proposalPath -Destination $contractPath -Force
}
