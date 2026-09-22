[CmdletBinding()]
param(
    [int]$PollSeconds = 2
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$scratchRoot = Join-Path $projectRoot 'scratch'
$heartbeatPath = Join-Path $scratchRoot 'word-validation-bridge-heartbeat.json'
$logPath = Join-Path $scratchRoot 'word-validation-bridge.log'
$validator = Join-Path $PSScriptRoot 'validate_word_native.ps1'

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Value,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $temporary = "$Path.$PID.tmp"
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Write-Heartbeat {
    try {
        Write-JsonAtomic -Value ([ordered]@{
            status = 'running'
            process_id = $PID
            session_id = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
            user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            updated_at = (Get-Date).ToString('o')
        }) -Path $heartbeatPath
        return $true
    } catch {
        return $false
    }
}

function Write-BridgeLog {
    param([string]$Message)
    try {
        "$(Get-Date -Format o) [$PID] $Message" | Add-Content -LiteralPath $logPath -Encoding UTF8
    } catch {
        # Logging must never be allowed to terminate the worker.
    }
}

if (-not (Test-Path -LiteralPath $scratchRoot)) {
    New-Item -ItemType Directory -Path $scratchRoot -Force | Out-Null
}

while ($true) {
    try {
        if (-not (Write-Heartbeat)) {
            Write-BridgeLog 'Heartbeat write failed; continuing under supervisor.'
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
                Write-BridgeLog "Starting validation request $($request.request_id)."
                & $validator `
                    -DocxPath ([string]$request.docx) `
                    -PdfPath ([string]$request.pdf) `
                    -ResultPath ([string]$request.result) `
                    -RequestId ([string]$request.request_id) `
                    -InteractiveWorker
                if ($LASTEXITCODE -ne 0) {
                    throw "Native validator exited with code $LASTEXITCODE."
                }
                Write-BridgeLog "Completed validation request $($request.request_id)."
            } catch {
                Write-BridgeLog "Validation request failed: $($_.Exception.Message)"
                $responsePath = if ($null -ne $request -and $request.response) {
                    [string]$request.response
                } else {
                    Join-Path $requestFile.DirectoryName 'interactive-word-validation-response.json'
                }
                try {
                    Write-JsonAtomic -Value ([ordered]@{
                        status = 'error'
                        request_id = if ($null -ne $request) { [string]$request.request_id } else { $null }
                        error = $_.Exception.Message
                        completed_at = (Get-Date).ToString('o')
                        completed_as = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
                    }) -Path $responsePath
                } catch {
                    Write-BridgeLog "Could not write validation error response: $($_.Exception.Message)"
                }
            } finally {
                Remove-Item -LiteralPath $processingPath -Force -ErrorAction SilentlyContinue
            }
        }
    } catch {
        Write-BridgeLog "Worker loop recovered from unexpected error: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds ([Math]::Max(1, $PollSeconds))
}
