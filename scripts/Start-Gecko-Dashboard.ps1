param([int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$geckoRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $geckoRoot '.tools\dashboard-python\Scripts\python.exe'
$url = "http://127.0.0.1:$Port"
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Dashboard runtime is missing. See dashboard/README.md for setup.' }
$healthy = $false
try { $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2; $healthy = $health.app -eq 'gecko-dashboard' } catch { }
if (-not $healthy) {
    $logFolder = Join-Path $geckoRoot 'scratch\dashboard'
    New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
    $process = Start-Process -FilePath $pythonPath -ArgumentList @('"' + (Join-Path $geckoRoot 'dashboard\server.py') + '"', '--port', $Port) -WorkingDirectory $geckoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logFolder 'server.log') -RedirectStandardError (Join-Path $logFolder 'server-error.log') -PassThru
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        if ($process.HasExited) { throw 'Dashboard stopped during startup. Check scratch/dashboard/server-error.log.' }
        try { $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2; $healthy = $health.app -eq 'gecko-dashboard'; if ($healthy) { break } } catch { }
    }
    if (-not $healthy) { throw 'Dashboard did not become ready. Check scratch/dashboard/server-error.log.' }
    Set-Content -LiteralPath (Join-Path $logFolder 'server.pid') -Value $process.Id
}
if (-not $NoBrowser) { Start-Process $url }
Write-Output "Gecko dashboard: $url"
