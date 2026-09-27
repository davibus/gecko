[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DocxPath,

    [Parameter(Mandatory = $true)]
    [string]$PdfPath,

    [string]$ResultPath,

    [switch]$UpdateTracker,

    [string]$MatchReport,

    [string]$JobDescription,

    [string]$RequestId,

    [switch]$InteractiveWorker
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$scratchRoot = Join-Path $projectRoot 'scratch'
$bridgeHeartbeat = Join-Path $scratchRoot 'word-validation-bridge-heartbeat.json'
$bridgeHealthScript = Join-Path $PSScriptRoot 'Test-Gecko-Word-Bridge.ps1'
$bridgeRestartCommand = Join-Path $PSScriptRoot 'Restart-Gecko-Word-Bridge.cmd'
. (Join-Path $PSScriptRoot 'word_bridge_common.ps1')

function Resolve-ProjectPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathValue,
        [switch]$MustExist
    )

    $candidate = if ([System.IO.Path]::IsPathRooted($PathValue)) {
        $PathValue
    } else {
        Join-Path $projectRoot $PathValue
    }

    if ($MustExist) {
        return (Resolve-Path -LiteralPath $candidate).Path
    }
    return [System.IO.Path]::GetFullPath($candidate)
}

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

function Test-BridgeHeartbeat {
    # Five minutes tolerates desktop scheduling delays and normal Word startup.
    # Process liveness is intentionally not required here because a sandboxed
    # token may be unable to inspect the interactive user's process metadata.
    return Test-GeckoBridgeHeartbeatHealthy `
        -Path $bridgeHeartbeat `
        -MaximumAgeSeconds $script:GeckoWordBridgeHealthySeconds
}

function Get-BridgeHealthDiagnostics {
    try {
        $output = & powershell.exe `
            -NoProfile `
            -NonInteractive `
            -ExecutionPolicy Bypass `
            -File $bridgeHealthScript `
            -Json `
            -SkipWordComProbe 2>&1
        return (($output | Out-String).Trim() -replace '\s+', ' ')
    } catch {
        return "Health check could not run: $($_.Exception.Message)"
    }
}

function Test-DirectInteractiveWordSession {
    # The bridge worker is deliberately started with an interactive-user token,
    # even though its PowerShell host itself is non-interactive.
    if ($InteractiveWorker) {
        return $true
    }

    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $sessionId = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
    if (-not [Environment]::UserInteractive -or $sessionId -eq 0) {
        return $false
    }

    # Gecko's agent sandbox can inherit IDE/console environment variables and
    # report UserInteractive=True, but its isolated token cannot safely start
    # Word COM. The account name is the reliable discriminator for that host.
    return $identity -notmatch '(?i)codexsandbox'
}

function Get-PdfPageCount {
    param([Parameter(Mandatory = $true)][string]$PdfFile)

    $previousPdf = $env:GECKO_VALIDATION_PDF
    try {
        $env:GECKO_VALIDATION_PDF = $PdfFile
        $pdfPageText = & python -c "import fitz, os; print(len(fitz.open(os.environ['GECKO_VALIDATION_PDF'])))"
        if ($LASTEXITCODE -ne 0) {
            throw 'Python could not inspect the Word-exported PDF.'
        }
        return [int]($pdfPageText | Select-Object -Last 1)
    } finally {
        $env:GECKO_VALIDATION_PDF = $previousPdf
    }
}

function Invoke-WordPagination {
    param(
        [Parameter(Mandatory = $true)][string]$DocumentPath,
        [Parameter(Mandatory = $true)][string]$PdfFile
    )

    $word = $null
    $document = $null
    try {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $word.DisplayAlerts = 0
        $document = $word.Documents.Open($DocumentPath, $false, $true)
        $document.Repaginate()
        $wordPages = [int]$document.ComputeStatistics(2)
        $document.ExportAsFixedFormat($PdfFile, 17)
        $document.Close($false)
        $document = $null
        return $wordPages
    } finally {
        if ($null -ne $document) {
            $document.Close($false)
        }
        if ($null -ne $word) {
            $word.Quit()
        }
    }
}

function Invoke-InteractiveHandoff {
    param(
        [Parameter(Mandatory = $true)][string]$DocumentPath,
        [Parameter(Mandatory = $true)][string]$PdfFile,
        [Parameter(Mandatory = $true)][string]$ResultFile
    )

    if (-not (Test-BridgeHeartbeat)) {
        $diagnostics = Get-BridgeHealthDiagnostics
        throw "The permanent interactive-user Word bridge is unhealthy; sandboxed Gecko will not retry Word COM or control the Scheduled Task. Bridge diagnostics: $diagnostics. User-side recovery command: $bridgeRestartCommand"
    }

    $requestDirectory = Split-Path -Parent $ResultFile
    $requestPath = Join-Path $requestDirectory 'interactive-word-validation-request.json'
    $responsePath = Join-Path $requestDirectory 'interactive-word-validation-response.json'
    $processingPath = Join-Path $requestDirectory 'interactive-word-validation-processing.json'
    $handoffId = [Guid]::NewGuid().ToString('N')

    $queueDeadline = (Get-Date).AddSeconds(15)
    while ((Test-Path -LiteralPath $requestPath) -or (Test-Path -LiteralPath $processingPath)) {
        if ((Get-Date) -ge $queueDeadline) {
            throw "A validation request is already active in $requestDirectory. Bridge diagnostics: $(Get-BridgeHealthDiagnostics)"
        }
        Start-Sleep -Milliseconds 500
    }
    Remove-Item -LiteralPath $responsePath -Force -ErrorAction SilentlyContinue
    Write-JsonAtomic -Value ([ordered]@{
        request_id = $handoffId
        docx = $DocumentPath
        pdf = $PdfFile
        result = $ResultFile
        response = $responsePath
        requested_at = (Get-Date).ToString('o')
        requested_by = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    }) -Path $requestPath

    $deadline = (Get-Date).AddSeconds(300)
    try {
        do {
            Start-Sleep -Milliseconds 500
            if (Test-Path -LiteralPath $responsePath) {
                try {
                    $response = Get-Content -LiteralPath $responsePath -Raw | ConvertFrom-Json
                    if ([string]$response.request_id -eq $handoffId -and $response.status -eq 'error') {
                        throw "Interactive Word validation failed: $($response.error)"
                    }
                } catch {
                    if ($_.Exception.Message -like 'Interactive Word validation failed:*') {
                        throw
                    }
                    # The worker may be replacing the response atomically.
                }
            }
            if (Test-Path -LiteralPath $ResultFile) {
                try {
                    $record = Get-Content -LiteralPath $ResultFile -Raw | ConvertFrom-Json
                    if ([string]$record.request_id -eq $handoffId -and $record.status -in @('native-valid', 'native-invalid')) {
                        return $record
                    }
                } catch {
                    # The worker may be replacing the record atomically; retry.
                }
            }
        } while ((Get-Date) -lt $deadline)

        throw "Timed out waiting for interactive Word validation request $handoffId. Bridge diagnostics: $(Get-BridgeHealthDiagnostics)"
    } finally {
        if (Test-Path -LiteralPath $responsePath) {
            try {
                $response = Get-Content -LiteralPath $responsePath -Raw | ConvertFrom-Json
                if ([string]$response.request_id -eq $handoffId) {
                    Remove-Item -LiteralPath $responsePath -Force -ErrorAction SilentlyContinue
                }
            } catch { }
        }
        if (Test-Path -LiteralPath $requestPath) {
            try {
                $pending = Get-Content -LiteralPath $requestPath -Raw | ConvertFrom-Json
                if ([string]$pending.request_id -eq $handoffId) {
                    Remove-Item -LiteralPath $requestPath -Force -ErrorAction SilentlyContinue
                }
            } catch { }
        }
    }
}

$docx = Resolve-ProjectPath -PathValue $DocxPath -MustExist
$pdf = Resolve-ProjectPath -PathValue $PdfPath
$pdfDirectory = Split-Path -Parent $pdf
if (-not (Test-Path -LiteralPath $pdfDirectory)) {
    New-Item -ItemType Directory -Path $pdfDirectory -Force | Out-Null
}

if ([string]::IsNullOrWhiteSpace($ResultPath)) {
    $result = Join-Path $pdfDirectory 'validation-status.json'
} else {
    $result = Resolve-ProjectPath -PathValue $ResultPath
}

$status = $null
$directInteractiveSession = Test-DirectInteractiveWordSession
if ($directInteractiveSession) {
    Write-Output 'Word validation mode: Direct interactive session'
    try {
        $wordPages = Invoke-WordPagination -DocumentPath $docx -PdfFile $pdf
        $pdfPages = Get-PdfPageCount -PdfFile $pdf
        $status = [ordered]@{
            status = if ($wordPages -eq 2 -and $pdfPages -eq 2) { 'native-valid' } else { 'native-invalid' }
            docx = $docx
            pdf = $pdf
            word_pages = $wordPages
            pdf_pages = $pdfPages
            request_id = if ([string]::IsNullOrWhiteSpace($RequestId)) { $null } else { $RequestId }
            validated_at = (Get-Date).ToString('o')
            validated_as = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            validation_session_id = [System.Diagnostics.Process]::GetCurrentProcess().SessionId
        }
        Write-JsonAtomic -Value $status -Path $result
    } catch {
        throw "Direct interactive Microsoft Word automation failed. The bridge was not invoked because this process has an interactive-user session. Confirm that desktop Microsoft Word is installed and can start under this Windows account. Error: $($_.Exception.Message)"
    }
} else {
    Write-Output 'Word validation mode: Interactive-user bridge'
    $status = Invoke-InteractiveHandoff -DocumentPath $docx -PdfFile $pdf -ResultFile $result
    $wordPages = [int]$status.word_pages
    $pdfPages = [int]$status.pdf_pages
}

if ($wordPages -ne 2 -or $pdfPages -ne 2) {
    throw "Resume must be exactly two pages; Word=$wordPages, exported PDF=$pdfPages."
}

Write-Output "Native Word validation passed: Word=$wordPages pages, exported PDF=$pdfPages pages."
Write-Output "Validation record: $result"

if ($UpdateTracker) {
    if ([string]::IsNullOrWhiteSpace($MatchReport) -or [string]::IsNullOrWhiteSpace($JobDescription)) {
        throw '-UpdateTracker requires both -MatchReport and -JobDescription.'
    }
    $match = Resolve-ProjectPath -PathValue $MatchReport -MustExist
    $job = Resolve-ProjectPath -PathValue $JobDescription -MustExist
    & python (Join-Path $projectRoot 'scripts\manage_job_tracker.py') add --resume $docx --match-report $match --job-description $job
    if ($LASTEXITCODE -ne 0) {
        $status.status = 'native-valid-tracker-pending'
        $status | Add-Member -NotePropertyName tracker_updated -NotePropertyValue $false -Force
        Write-JsonAtomic -Value $status -Path $result
        throw "Native validation passed, but the tracker update failed with exit code $LASTEXITCODE."
    }
    $status | Add-Member -NotePropertyName tracker_updated -NotePropertyValue $true -Force
    Write-JsonAtomic -Value $status -Path $result
}
