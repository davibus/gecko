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
$bridgeInstaller = Join-Path $PSScriptRoot 'Install-Gecko-Word-Bridge.cmd'

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
    if (-not (Test-Path -LiteralPath $bridgeHeartbeat)) {
        return $false
    }
    try {
        $heartbeat = Get-Content -LiteralPath $bridgeHeartbeat -Raw | ConvertFrom-Json
        $updated = [DateTimeOffset]::Parse([string]$heartbeat.updated_at)
        # Allow a slow Word startup or a brief desktop scheduling pause without
        # requiring the user to reinstall the already-registered bridge task.
        $fresh = ([DateTimeOffset]::UtcNow - $updated.ToUniversalTime()).TotalSeconds -le 60
        return $fresh -and $heartbeat.status -eq 'running' -and $heartbeat.user -notmatch 'codexsandbox'
    } catch {
        return $false
    }
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
        try {
            Start-ScheduledTask -TaskName 'Gecko Word Validation Bridge' -ErrorAction Stop
            Start-Sleep -Seconds 2
        } catch {
            # The sandbox normally cannot control the interactive user's task.
        }
    }
    if (-not (Test-BridgeHeartbeat)) {
        throw "Microsoft Word requires the interactive desktop session. Run this one-time installer from Windows Explorer: $bridgeInstaller"
    }

    $requestDirectory = Split-Path -Parent $ResultFile
    $requestPath = Join-Path $requestDirectory 'interactive-word-validation-request.json'
    $responsePath = Join-Path $requestDirectory 'interactive-word-validation-response.json'
    $handoffId = [Guid]::NewGuid().ToString('N')
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

    $deadline = (Get-Date).AddSeconds(150)
    do {
        Start-Sleep -Milliseconds 500
        if (Test-Path -LiteralPath $responsePath) {
            $response = Get-Content -LiteralPath $responsePath -Raw | ConvertFrom-Json
            if ([string]$response.request_id -eq $handoffId -and $response.status -eq 'error') {
                throw "Interactive Word validation failed: $($response.error)"
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

    throw "Timed out waiting for interactive Word validation request $handoffId."
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
    $logonSessionFailure = $_.Exception.Message -match 'specified logon session does not exist|80070520'
    if ($InteractiveWorker -or -not $logonSessionFailure) {
        throw
    }
    Write-Output 'Direct Word COM is unavailable in the sandbox; handing validation to the interactive desktop bridge.'
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
