$ErrorActionPreference = 'Stop'
$mutex = [System.Threading.Mutex]::new($false, 'Local\GeckoMainCodexUsageCollector')
if (-not $mutex.WaitOne(0)) { exit 0 }
try {
$usageDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python -ErrorAction Stop).Source
$node = (Get-Command node -ErrorAction Stop).Source
$deps = 'C:\Users\DCALL\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
if (-not (Test-Path -LiteralPath $deps)) { throw "Bundled spreadsheet dependency is unavailable: $deps" }
$env:CODEX_USAGE_NODE_MODULES = $deps
$snapshot = Join-Path $usageDir 'codex_usage.snapshot.json'
$workbook = Join-Path $usageDir 'codex_usage.xlsx'
& $python (Join-Path $usageDir 'codex_usage.py') --export-json $snapshot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $node (Join-Path $usageDir 'export_workbook.mjs') $snapshot $workbook
exit $LASTEXITCODE
} finally {
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
