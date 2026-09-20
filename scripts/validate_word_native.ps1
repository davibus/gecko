[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DocxPath,

    [Parameter(Mandatory = $true)]
    [string]$PdfPath,

    [string]$ResultPath,

    [switch]$UpdateTracker,

    [string]$MatchReport,

    [string]$JobDescription
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

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

$word = $null
$document = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $document = $word.Documents.Open($docx, $false, $true)
    $document.Repaginate()
    $wordPages = [int]$document.ComputeStatistics(2)
    $document.ExportAsFixedFormat($pdf, 17)
    $document.Close($false)
    $document = $null
} finally {
    if ($null -ne $document) {
        $document.Close($false)
    }
    if ($null -ne $word) {
        $word.Quit()
    }
}

$previousPdf = $env:GECKO_VALIDATION_PDF
try {
    $env:GECKO_VALIDATION_PDF = $pdf
    $pdfPageText = & python -c "import fitz, os; print(len(fitz.open(os.environ['GECKO_VALIDATION_PDF'])))"
    if ($LASTEXITCODE -ne 0) {
        throw 'Python could not inspect the Word-exported PDF.'
    }
    $pdfPages = [int]($pdfPageText | Select-Object -Last 1)
} finally {
    $env:GECKO_VALIDATION_PDF = $previousPdf
}

$status = [ordered]@{
    status = if ($wordPages -eq 2 -and $pdfPages -eq 2) { 'native-valid' } else { 'native-invalid' }
    docx = $docx
    pdf = $pdf
    word_pages = $wordPages
    pdf_pages = $pdfPages
    validated_at = (Get-Date).ToString('o')
    validated_as = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
}
$status | ConvertTo-Json | Set-Content -LiteralPath $result -Encoding UTF8

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
        $status['status'] = 'native-valid-tracker-pending'
        $status['tracker_updated'] = $false
        $status | ConvertTo-Json | Set-Content -LiteralPath $result -Encoding UTF8
        throw "Native validation passed, but the tracker update failed with exit code $LASTEXITCODE."
    }
    $status['tracker_updated'] = $true
    $status | ConvertTo-Json | Set-Content -LiteralPath $result -Encoding UTF8
}
