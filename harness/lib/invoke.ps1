#Requires -Version 5.1
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'

# Wrapper for `claude -p` invocations with real-time progress display
# (PowerShell port of invoke.sh).
#
# Usage:
#   Invoke-ClaudeAgent -Agent NAME [-MaxTurns N] [-McpConfig FILE] -Prompt PROMPT

. (Join-Path $PSScriptRoot 'utils.ps1')

function Invoke-ClaudeAgent {
    [CmdletBinding()]
    param(
        [string]$Agent = '',
        [int]$MaxTurns = 50,
        [string]$McpConfig = '',
        [string]$Prompt = '',
        # Accept any additional positional / passthrough arguments so callers
        # can mirror the .sh `--agent NAME --max-turns N -- ... PROMPT` form.
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Rest
    )

    # Mirror the .sh argument-parsing loop: walk $Rest treating it as the
    # positional/flag tail. Anything that isn't a recognized flag becomes the prompt.
    if ($Rest) {
        $i = 0
        while ($i -lt $Rest.Count) {
            $tok = $Rest[$i]
            switch ($tok) {
                '--agent'      { $Agent     = $Rest[$i + 1]; $i += 2; continue }
                '--max-turns'  { $MaxTurns  = [int]$Rest[$i + 1]; $i += 2; continue }
                '--mcp-config' { $McpConfig = $Rest[$i + 1]; $i += 2; continue }
                default        { $Prompt    = $tok; $i += 1 }
            }
        }
    }

    # --dangerously-skip-permissions bypasses permission prompts but hooks still fire.
    # --permission-mode dontAsk DENIES Write/Bash entirely -- do NOT use it.
    $cmdArgs = @(
        '-p', $Prompt,
        '--agent', $Agent,
        '--max-turns', "$MaxTurns",
        '--dangerously-skip-permissions',
        '--output-format', 'stream-json',
        '--verbose'
    )

    # Load harness settings (hooks, etc.) via --settings flag.
    # This merges with any existing .claude/settings.json without clobbering.
    $harnessRoot = if ($env:HARNESS_ROOT) { $env:HARNESS_ROOT } else { '.' }
    $harnessSettings = Join-Path (Join-Path $harnessRoot '.claude') 'settings.json'
    if (Test-Path -LiteralPath $harnessSettings -PathType Leaf) {
        $cmdArgs += @('--settings', $harnessSettings)
    }

    if (-not [string]::IsNullOrEmpty($McpConfig)) {
        $cmdArgs += @('--mcp-config', $McpConfig)
    }

    # Stream NDJSON to a temp file, then walk it for progress display.
    $outputFile = New-TemporaryFile
    $exitCode = 0

    try {
        # Capture both stdout and stderr to the same file (matches `> file 2>&1`).
        & claude @cmdArgs *> $outputFile.FullName
        $exitCode = $LASTEXITCODE

        # Parse the stream for progress display
        $reader = [System.IO.StreamReader]::new($outputFile.FullName)
        try {
            while (-not $reader.EndOfStream) {
                $line = $reader.ReadLine()
                if ([string]::IsNullOrWhiteSpace($line)) { continue }

                $msgType = $line | & jq -r '.type // empty' 2>$null
                if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($msgType)) { continue }

                switch ($msgType) {
                    'assistant' {
                        $toolName = $line | & jq -r '.message.content[]? | select(.type=="tool_use") | .name // empty' 2>$null
                        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrEmpty($toolName)) {
                            $previewFilter = '.message.content[]? | select(.type=="tool_use") | .input | if .command then .command[:80] elif .file_path then .file_path elif .pattern then .pattern else (tostring[:60]) end'
                            $preview = $line | & jq -r $previewFilter 2>$null
                            if ($LASTEXITCODE -ne 0) { $preview = '' }
                            [Console]::Error.WriteLine("  $([char]27)[0;90m> ${toolName}: ${preview}$([char]27)[0m")
                        }
                    }
                    'result' {
                        $cost = $line | & jq -r '.total_cost_usd // empty' 2>$null
                        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrEmpty($cost) -and $cost -ne 'null') {
                            [Console]::Error.WriteLine("  $([char]27)[0;90m  Cost: `$$cost$([char]27)[0m")
                        }
                    }
                }
            }
        } finally {
            $reader.Dispose()
        }
    } finally {
        if (Test-Path -LiteralPath $outputFile.FullName) {
            Remove-Item -LiteralPath $outputFile.FullName -Force -ErrorAction SilentlyContinue
        }
    }

    # Propagate the exit code via $LASTEXITCODE; do not throw -- callers may
    # want to inspect non-zero codes (mirrors `return "$exit_code"` in the .sh).
    $global:LASTEXITCODE = $exitCode
    return $exitCode
}
