[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'PromptFile')]
    [ValidateNotNullOrEmpty()]
    [string]$PromptFile,

    [Parameter(Mandatory = $true, ParameterSetName = 'PromptText')]
    [ValidateNotNullOrEmpty()]
    [string]$Prompt,

    [string]$Workspace = (Split-Path -Parent $PSScriptRoot),
    [string]$StateDirectory = 'scratch\cursor-overnight',
    [string]$AgentPath,
    [int]$MinimumRetrySeconds = 900,
    [switch]$TestMode
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path, [string]$BasePath = (Get-Location).Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Path))
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Text)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-UtcTimestamp {
    return [DateTime]::UtcNow.ToString('o')
}

function Set-CheckpointValue {
    param(
        [Parameter(Mandatory = $true)]$Checkpoint,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )

    if ($Checkpoint.PSObject.Properties.Name -contains $Name) {
        $Checkpoint.$Name = $Value
    }
    else {
        $Checkpoint | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Save-Checkpoint {
    param(
        [Parameter(Mandatory = $true)]$Checkpoint,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $temporaryPath = "$Path.tmp"
    $Checkpoint | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporaryPath -Encoding UTF8
    Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
}

function Get-RetryAfterSeconds {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][int]$MinimumSeconds
    )

    $candidates = New-Object System.Collections.Generic.List[double]
    $durationPattern = '(?im)(?:retry[- ]?after|try again in|retry in|resets? in|retry_after)[^0-9]{0,20}(?<value>\d+(?:\.\d+)?)\s*(?<unit>milliseconds?|msecs?|ms|seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)?'
    foreach ($match in [regex]::Matches($Text, $durationPattern)) {
        $value = [double]::Parse($match.Groups['value'].Value, [Globalization.CultureInfo]::InvariantCulture)
        $unit = $match.Groups['unit'].Value.ToLowerInvariant()
        $seconds = switch -Regex ($unit) {
            '^(milliseconds?|msecs?|ms)$' { $value / 1000; break }
            '^(minutes?|mins?|m)$' { $value * 60; break }
            '^(hours?|hrs?|h)$' { $value * 3600; break }
            default { $value }
        }
        $candidates.Add($seconds)
    }

    $timestampPattern = '(?im)(?:retry[- ]?after|try again after)[^\r\n]{0,10}(?<timestamp>\d{4}-\d{2}-\d{2}T[^\s,;]+)'
    foreach ($match in [regex]::Matches($Text, $timestampPattern)) {
        $parsed = [DateTimeOffset]::MinValue
        if ([DateTimeOffset]::TryParse($match.Groups['timestamp'].Value, [ref]$parsed)) {
            $seconds = ($parsed.ToUniversalTime() - [DateTimeOffset]::UtcNow).TotalSeconds
            if ($seconds -gt 0) {
                $candidates.Add($seconds)
            }
        }
    }

    $longestReported = 0
    if ($candidates.Count -gt 0) {
        $longestReported = [Math]::Ceiling(($candidates | Measure-Object -Maximum).Maximum)
    }
    return [int][Math]::Max($MinimumSeconds, $longestReported)
}

function Get-FailureKind {
    param([Parameter(Mandatory = $true)][string]$Text)

    if ($Text -match '(?im)\b(401|unauthenticated|authentication failed|invalid (?:api[ -]?key|token)|not logged in|please (?:log|sign) in|login required)\b') {
        return 'authentication'
    }
    if ($Text -match '(?im)\b(403|forbidden|permission denied|access denied|not authorized|workspace is not trusted)\b') {
        return 'permission'
    }
    if ($Text -match '(?im)\b(payment required|card declined|billing account|billing error|insufficient credits?|credit balance)\b') {
        return 'billing'
    }
    if ($Text -match '(?im)(\b429\b|rate[ -]?limit|usage[ -]?limit|quota (?:exceeded|exhausted)|too many requests|resource exhausted|capacity limit)') {
        return 'retryable-limit'
    }
    return 'non-retryable'
}

function Resolve-AgentPath {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        $resolved = Resolve-FullPath -Path $RequestedPath
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            throw "Cursor Agent executable was not found: $resolved"
        }
        return $resolved
    }

    $command = Get-Command agent.cmd -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $installedPath = Join-Path $env:LOCALAPPDATA 'cursor-agent\agent.cmd'
    if (Test-Path -LiteralPath $installedPath -PathType Leaf) {
        return $installedPath
    }
    throw 'Cursor Agent CLI was not found. Install it with: irm ''https://cursor.com/install?win32=true'' | iex'
}

if ($TestMode) {
    if ($env:CURSOR_OVERNIGHT_TEST_MODE -ne '1') {
        throw 'TestMode is restricted to the automated test harness.'
    }
    if ($MinimumRetrySeconds -lt 1) {
        throw 'MinimumRetrySeconds must be at least 1 in TestMode.'
    }
}
elseif ($MinimumRetrySeconds -lt 900) {
    throw 'MinimumRetrySeconds cannot be less than 900 (15 minutes) outside TestMode.'
}

$workspacePath = Resolve-FullPath -Path $Workspace
if (-not (Test-Path -LiteralPath $workspacePath -PathType Container)) {
    throw "Workspace does not exist: $workspacePath"
}

if ($PSCmdlet.ParameterSetName -eq 'PromptFile') {
    $promptPath = Resolve-FullPath -Path $PromptFile -BasePath $workspacePath
    if (-not (Test-Path -LiteralPath $promptPath -PathType Leaf)) {
        throw "Prompt file does not exist: $promptPath"
    }
    $taskPrompt = Get-Content -LiteralPath $promptPath -Raw
}
else {
    $promptPath = $null
    $taskPrompt = $Prompt
}

$automationGuard = @'

OVERNIGHT AUTOMATION CONTRACT:
- Work idempotently. Inspect existing files, task state, and canonical Google Sheet rows before writing.
- Use the repository's canonical scripts and unique job identifiers for upserts. Never create duplicate work or duplicate Google Sheets entries.
- Resume incomplete work from its existing artifacts. Do not repeat already completed external writes.
- Do not purchase usage, add credits, change plans, bypass limits, apply for jobs, or send messages.
- Finish only after the requested workflow's own validation and read-back requirements pass.
'@
$initialPrompt = $taskPrompt.TrimEnd() + $automationGuard
$resumePrompt = @'
Continue the original task from the existing session and repository state. Inspect what already completed before acting, do not repeat completed writes, and finish the original task's validation and read-back requirements. Do not purchase additional usage or bypass limits.
'@
$taskHash = Get-Sha256 -Text $initialPrompt
$statePath = Resolve-FullPath -Path $StateDirectory -BasePath $workspacePath
New-Item -ItemType Directory -Path $statePath -Force | Out-Null
$checkpointPath = Join-Path $statePath 'checkpoint.json'
$logPath = Join-Path $statePath 'overnight.log'
$lockPath = Join-Path $statePath 'run.lock'
$resolvedAgentPath = Resolve-AgentPath -RequestedPath $AgentPath

function Write-RunLog {
    param([Parameter(Mandatory = $true)][string]$Message)
    $line = "$(Get-UtcTimestamp) $Message"
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
    Write-Host $line
}

try {
    $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
}
catch {
    throw "Another overnight Cursor run is already using '$statePath'. Stop it before starting another. $($_.Exception.Message)"
}

try {
    if (Test-Path -LiteralPath $checkpointPath) {
        $checkpoint = Get-Content -LiteralPath $checkpointPath -Raw | ConvertFrom-Json
        if ($checkpoint.taskHash -ne $taskHash) {
            throw "The checkpoint belongs to a different prompt. Use a different -StateDirectory; refusing to resume the wrong session."
        }
        if ($checkpoint.status -eq 'completed') {
            Write-RunLog "Task is already completed (session $($checkpoint.sessionId)); no Cursor request was made."
            exit 0
        }
    }
    else {
        $checkpoint = [pscustomobject]@{
            schemaVersion = 1
            taskHash = $taskHash
            promptFile = $promptPath
            workspace = $workspacePath
            agentPath = $resolvedAgentPath
            sessionId = $null
            status = 'initialized'
            attempt = 0
            createdAt = Get-UtcTimestamp
            updatedAt = Get-UtcTimestamp
            lastAttemptStartedAt = $null
            lastAttemptEndedAt = $null
            lastExitCode = $null
            lastEventType = $null
            lastEventSubtype = $null
            nextRetryAt = $null
            completedAt = $null
            failureKind = $null
            lastError = $null
        }
        Save-Checkpoint -Checkpoint $checkpoint -Path $checkpointPath
    }

    Write-RunLog "Cursor Agent preflight: $resolvedAgentPath status"
    $statusOutput = @(& $resolvedAgentPath status 2>&1 | ForEach-Object { $_.ToString() })
    $statusExitCode = $LASTEXITCODE
    $statusText = $statusOutput -join [Environment]::NewLine
    $statusFailureKind = Get-FailureKind -Text $statusText
    if (($statusExitCode -ne 0) -or ($statusFailureKind -eq 'authentication')) {
        Set-CheckpointValue $checkpoint 'status' 'failed'
        Set-CheckpointValue $checkpoint 'failureKind' 'authentication'
        Set-CheckpointValue $checkpoint 'lastError' $statusText
        Set-CheckpointValue $checkpoint 'updatedAt' (Get-UtcTimestamp)
        Save-Checkpoint -Checkpoint $checkpoint -Path $checkpointPath
        Write-RunLog "Authentication preflight failed with exit code $statusExitCode. $statusText"
        exit 20
    }

    while ($true) {
        $attempt = [int]$checkpoint.attempt + 1
        Set-CheckpointValue $checkpoint 'attempt' $attempt
        Set-CheckpointValue $checkpoint 'status' 'running'
        Set-CheckpointValue $checkpoint 'lastAttemptStartedAt' (Get-UtcTimestamp)
        Set-CheckpointValue $checkpoint 'updatedAt' (Get-UtcTimestamp)
        Set-CheckpointValue $checkpoint 'nextRetryAt' $null
        Set-CheckpointValue $checkpoint 'failureKind' $null
        Set-CheckpointValue $checkpoint 'lastError' $null
        Save-Checkpoint -Checkpoint $checkpoint -Path $checkpointPath

        $attemptLogPath = Join-Path $statePath ("attempt-{0:D4}.ndjson" -f $attempt)
        $agentArguments = @(
            '-p',
            '--force',
            '--trust',
            '--output-format', 'stream-json',
            '--workspace', $workspacePath
        )
        if ($checkpoint.sessionId) {
            $agentArguments += "--resume=$($checkpoint.sessionId)"
            $attemptPrompt = $resumePrompt
            Write-RunLog "Attempt $attempt resuming session $($checkpoint.sessionId)."
        }
        else {
            $attemptPrompt = $initialPrompt
            Write-RunLog "Attempt $attempt starting a new session."
        }
        $agentArguments += $attemptPrompt

        $capturedLines = New-Object System.Collections.Generic.List[string]
        $terminalSuccess = $false
        & $resolvedAgentPath @agentArguments 2>&1 | ForEach-Object {
            $line = $_.ToString()
            $capturedLines.Add($line)
            Add-Content -LiteralPath $attemptLogPath -Value $line -Encoding UTF8
            Write-Host $line

            try {
                $event = $line | ConvertFrom-Json
                if ($event.session_id -and (-not $checkpoint.sessionId)) {
                    Set-CheckpointValue $checkpoint 'sessionId' ([string]$event.session_id)
                }
                if ($event.type) {
                    Set-CheckpointValue $checkpoint 'lastEventType' ([string]$event.type)
                }
                if ($event.subtype) {
                    Set-CheckpointValue $checkpoint 'lastEventSubtype' ([string]$event.subtype)
                }
                if (($event.type -eq 'result') -and ($event.subtype -eq 'success') -and (-not $event.is_error)) {
                    $terminalSuccess = $true
                }
                Set-CheckpointValue $checkpoint 'updatedAt' (Get-UtcTimestamp)
                Save-Checkpoint -Checkpoint $checkpoint -Path $checkpointPath
            }
            catch {
                # Non-JSON stderr is retained verbatim in the attempt log and classified below.
            }
        }
        $exitCode = $LASTEXITCODE
        $attemptText = $capturedLines -join [Environment]::NewLine
        Set-CheckpointValue $checkpoint 'lastExitCode' $exitCode
        Set-CheckpointValue $checkpoint 'lastAttemptEndedAt' (Get-UtcTimestamp)
        Set-CheckpointValue $checkpoint 'updatedAt' (Get-UtcTimestamp)

        if (($exitCode -eq 0) -and $terminalSuccess) {
            Set-CheckpointValue $checkpoint 'status' 'completed'
            Set-CheckpointValue $checkpoint 'completedAt' (Get-UtcTimestamp)
            Set-CheckpointValue $checkpoint 'nextRetryAt' $null
            Save-Checkpoint -Checkpoint $checkpoint -Path $checkpointPath
            Write-RunLog "Task completed successfully on attempt $attempt (session $($checkpoint.sessionId))."
            exit 0
        }

        $failureKind = Get-FailureKind -Text $attemptText
        Set-CheckpointValue $checkpoint 'failureKind' $failureKind
        Set-CheckpointValue $checkpoint 'lastError' (($capturedLines | Select-Object -Last 30) -join [Environment]::NewLine)

        if ($failureKind -ne 'retryable-limit') {
            Set-CheckpointValue $checkpoint 'status' 'failed'
            Save-Checkpoint -Checkpoint $checkpoint -Path $checkpointPath
            Write-RunLog "Attempt $attempt failed with non-retryable kind '$failureKind' and exit code $exitCode. Stopping."
            exit 21
        }

        $retrySeconds = Get-RetryAfterSeconds -Text $attemptText -MinimumSeconds $MinimumRetrySeconds
        $retryAt = [DateTimeOffset]::UtcNow.AddSeconds($retrySeconds)
        Set-CheckpointValue $checkpoint 'status' 'waiting-for-limit'
        Set-CheckpointValue $checkpoint 'nextRetryAt' $retryAt.ToString('o')
        Save-Checkpoint -Checkpoint $checkpoint -Path $checkpointPath
        Write-RunLog "Attempt $attempt reached a usage/rate limit. Waiting $retrySeconds seconds until $($retryAt.ToLocalTime().ToString('o')); then the same session will be resumed when available."

        while ([DateTimeOffset]::UtcNow -lt $retryAt) {
            $remaining = [Math]::Ceiling(($retryAt - [DateTimeOffset]::UtcNow).TotalSeconds)
            Start-Sleep -Seconds ([Math]::Min(30, [Math]::Max(1, $remaining)))
        }
    }
}
finally {
    if ($lockStream) {
        $lockStream.Dispose()
    }
}
