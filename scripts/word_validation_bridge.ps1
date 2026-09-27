[CmdletBinding()]
param(
    [int]$PollSeconds = 2,
    [int]$StaleRequestMinutes = 60,
    [string]$ScratchRoot,
    [string]$ValidatorPath,
    [int]$MaximumRequests = 0,
    [switch]$SkipWordComProbe
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ScratchRoot)) {
    $scratchRoot = Join-Path $projectRoot 'scratch'
} else {
    $scratchRoot = [System.IO.Path]::GetFullPath($ScratchRoot)
}
$heartbeatPath = Join-Path $scratchRoot 'word-validation-bridge-heartbeat.json'
$logPath = Join-Path $scratchRoot 'word-validation-bridge.log'
$validator = if ([string]::IsNullOrWhiteSpace($ValidatorPath)) {
    Join-Path $PSScriptRoot 'validate_word_native.ps1'
} else {
    [System.IO.Path]::GetFullPath($ValidatorPath)
}
. (Join-Path $PSScriptRoot 'word_bridge_common.ps1')

$processStartedAt = ([DateTimeOffset](Get-Process -Id $PID).StartTime).ToString('o')
$instanceId = [Guid]::NewGuid().ToString('N')
$wordComAvailable = if ($SkipWordComProbe) { $true } else { Test-GeckoWordCom }
$bridgeStatus = 'running'
$activeRequestId = $null

function Write-BridgeLog {
    param([string]$Message)
    try {
        "$(Get-Date -Format o) [$PID] $Message" | Add-Content -LiteralPath $logPath -Encoding UTF8
    } catch {
        # Logging must never terminate the worker.
    }
}

function Write-Heartbeat {
    try {
        Write-GeckoJsonAtomic -Value ([ordered]@{
            status = $script:bridgeStatus
            process_id = $PID
            process_started_at = $script:processStartedAt
            instance_id = $script:instanceId
            session_id = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
            user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            word_com_available = $script:wordComAvailable
            active_request_id = $script:activeRequestId
            updated_at = (Get-Date).ToString('o')
        }) -Path $heartbeatPath
        return $true
    } catch {
        return $false
    }
}

function Write-RequestResponse {
    param(
        [object]$Request,
        [string]$FallbackDirectory,
        [string]$Status,
        [string]$ErrorMessage
    )

    $responsePath = if ($null -ne $Request -and $Request.response) {
        [string]$Request.response
    } else {
        Join-Path $FallbackDirectory 'interactive-word-validation-response.json'
    }
    $payload = [ordered]@{
        status = $Status
        request_id = if ($null -ne $Request) { [string]$Request.request_id } else { $null }
        completed_at = (Get-Date).ToString('o')
        completed_as = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    }
    if (-not [string]::IsNullOrWhiteSpace($ErrorMessage)) {
        $payload.error = $ErrorMessage
    }
    Write-GeckoJsonAtomic -Value $payload -Path $responsePath
}

function Recover-OrphanedRequests {
    $processingFiles = Get-ChildItem -LiteralPath $scratchRoot -Filter 'interactive-word-validation-processing.json' -Recurse -File -ErrorAction SilentlyContinue
    foreach ($processingFile in $processingFiles) {
        $requestPath = Join-Path $processingFile.DirectoryName 'interactive-word-validation-request.json'
        try {
            if (Test-Path -LiteralPath $requestPath) {
                $orphan = Get-Content -LiteralPath $processingFile.FullName -Raw | ConvertFrom-Json
                Write-RequestResponse -Request $orphan -FallbackDirectory $processingFile.DirectoryName -Status 'error' -ErrorMessage 'A newer validation request replaced an orphaned in-process request.'
                Remove-Item -LiteralPath $processingFile.FullName -Force
            } else {
                Move-Item -LiteralPath $processingFile.FullName -Destination $requestPath -Force
                Write-BridgeLog "Recovered orphaned request $requestPath."
            }
        } catch {
            Write-BridgeLog "Could not recover orphaned request $($processingFile.FullName): $($_.Exception.Message)"
        }
    }
}

function Remove-StaleHandoffFiles {
    $cutoff = (Get-Date).AddMinutes(-[Math]::Max(5, $StaleRequestMinutes))
    $responseCutoff = (Get-Date).AddDays(-1)
    Get-ChildItem -LiteralPath $scratchRoot -Filter 'interactive-word-validation-request.json' -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.LastWriteTime -lt $cutoff) {
            try {
                $request = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
                Write-RequestResponse -Request $request -FallbackDirectory $_.DirectoryName -Status 'error' -ErrorMessage 'The bridge discarded a stale validation request before processing.'
            } catch {
                Write-BridgeLog "Discarding unreadable stale request $($_.FullName)."
            }
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
        }
    }
    Get-ChildItem -LiteralPath $scratchRoot -Filter 'interactive-word-validation-response.json' -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.LastWriteTime -lt $responseCutoff) {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
        }
    }
    Get-ChildItem -LiteralPath $scratchRoot -Filter '*.tmp' -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
        if ($_.Name -match 'interactive-word-validation|word-validation-bridge' -and $_.LastWriteTime -lt $responseCutoff) {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
        }
    }
}

if (-not (Test-Path -LiteralPath $scratchRoot)) {
    New-Item -ItemType Directory -Path $scratchRoot -Force | Out-Null
}

Write-BridgeLog "Bridge starting. Instance=$instanceId; Word COM available=$wordComAvailable."
Recover-OrphanedRequests
Remove-StaleHandoffFiles
$lastCleanup = Get-Date
$processedRequests = 0

try {
    while ($true) {
        try {
            $bridgeStatus = 'running'
            $activeRequestId = $null
            if (-not (Write-Heartbeat)) {
                Write-BridgeLog 'Heartbeat write failed; continuing under scheduled-task supervision.'
            }

            if (((Get-Date) - $lastCleanup).TotalMinutes -ge 10) {
                Remove-StaleHandoffFiles
                $lastCleanup = Get-Date
            }

            $requests = Get-ChildItem -LiteralPath $scratchRoot -Filter 'interactive-word-validation-request.json' -Recurse -File -ErrorAction SilentlyContinue
            foreach ($requestFile in $requests) {
                $processingPath = Join-Path $requestFile.DirectoryName 'interactive-word-validation-processing.json'
                try {
                    Move-Item -LiteralPath $requestFile.FullName -Destination $processingPath -ErrorAction Stop
                } catch {
                    Write-BridgeLog "Could not claim request $($requestFile.FullName): $($_.Exception.Message)"
                    continue
                }

                $request = $null
                try {
                    $request = Get-Content -LiteralPath $processingPath -Raw | ConvertFrom-Json
                    $bridgeStatus = 'busy'
                    $activeRequestId = [string]$request.request_id
                    $null = Write-Heartbeat
                    Write-BridgeLog "Starting validation request $activeRequestId."
                    & $validator `
                        -DocxPath ([string]$request.docx) `
                        -PdfPath ([string]$request.pdf) `
                        -ResultPath ([string]$request.result) `
                        -RequestId $activeRequestId `
                        -InteractiveWorker
                    Write-RequestResponse -Request $request -FallbackDirectory $requestFile.DirectoryName -Status 'complete' -ErrorMessage $null
                    Write-BridgeLog "Completed validation request $activeRequestId."
                } catch {
                    Write-BridgeLog "Validation request failed: $($_.Exception.Message)"
                    try {
                        Write-RequestResponse -Request $request -FallbackDirectory $requestFile.DirectoryName -Status 'error' -ErrorMessage $_.Exception.Message
                    } catch {
                        Write-BridgeLog "Could not write validation error response: $($_.Exception.Message)"
                    }
                } finally {
                    Remove-Item -LiteralPath $processingPath -Force -ErrorAction SilentlyContinue
                    $bridgeStatus = 'running'
                    $activeRequestId = $null
                    $null = Write-Heartbeat
                    $processedRequests += 1
                }
            }
            if ($MaximumRequests -gt 0 -and $processedRequests -ge $MaximumRequests) {
                break
            }
        } catch {
            Write-BridgeLog "Worker loop recovered from unexpected error: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds ([Math]::Max(1, $PollSeconds))
    }
} finally {
    try {
        Write-GeckoJsonAtomic -Value ([ordered]@{
            status = 'stopped'
            process_id = $PID
            process_started_at = $processStartedAt
            instance_id = $instanceId
            session_id = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
            user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            word_com_available = $wordComAvailable
            updated_at = (Get-Date).ToString('o')
        }) -Path $heartbeatPath
    } catch { }
    Write-BridgeLog 'Bridge stopped.'
}
