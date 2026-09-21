$ErrorActionPreference = 'Stop'
$projectRoot = 'C:\Users\DCALL\Desktop\gecko'
$logPath = Join-Path $projectRoot 'scratch\Trove-Brands+5750188863\native-validation-task.log'
try {
    & (Join-Path $projectRoot 'scripts\validate_word_native.ps1') `
        -DocxPath (Join-Path $projectRoot 'output\resumes\Dave-Call+Trove-Brands+5750188863.docx') `
        -PdfPath (Join-Path $projectRoot 'scratch\Trove-Brands+5750188863\word-validation.pdf') `
        -ResultPath (Join-Path $projectRoot 'scratch\Trove-Brands+5750188863\validation-status.json') `
        *> $logPath
} catch {
    $_ | Out-String | Add-Content -LiteralPath $logPath -Encoding UTF8
    exit 1
}
