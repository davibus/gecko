[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$scratchRoot = Join-Path $projectRoot 'scratch'
$validator = Join-Path $PSScriptRoot 'validate_word_native.ps1'
$pending = @()

Get-ChildItem -LiteralPath $scratchRoot -Filter 'validation-status.json' -Recurse -File | ForEach-Object {
    try {
        $record = Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json
        if ($record.status -in @('native-pending', 'native-valid-tracker-pending')) {
            $pending += [pscustomobject]@{
                RecordPath = $_.FullName
                ScratchDirectory = $_.DirectoryName
                Docx = [string]$record.docx
            }
        }
    } catch {
        Write-Warning "Skipping unreadable validation record $($_.FullName): $($_.Exception.Message)"
    }
}

if ($pending.Count -eq 0) {
    Write-Output 'No pending native Word validations were found.'
    exit 0
}

$failures = @()
foreach ($item in $pending) {
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($item.Docx)
    if (-not $stem.StartsWith('Dave-Call+')) {
        $failures += "Unsupported resume filename: $($item.Docx)"
        continue
    }

    $archiveStem = $stem.Substring('Dave-Call+'.Length)
    $matchReport = Join-Path $projectRoot "output\match-reports\$stem.md"
    $jobDescription = Join-Path $projectRoot "input\job-descriptions\$archiveStem.md"
    $wordPdf = Join-Path $item.ScratchDirectory 'word-validation.pdf'

    Write-Output "Validating $stem under $([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)..."
    try {
        & $validator `
            -DocxPath $item.Docx `
            -PdfPath $wordPdf `
            -ResultPath $item.RecordPath `
            -UpdateTracker `
            -MatchReport $matchReport `
            -JobDescription $jobDescription
    } catch {
        $failures += "${stem}: $($_.Exception.Message)"
    }
}

if ($failures.Count -gt 0) {
    Write-Error ("One or more pending validations failed:`n- " + ($failures -join "`n- "))
    exit 1
}

Write-Output "Completed $($pending.Count) pending native Word validation(s) and tracker update(s)."
