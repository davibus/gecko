param([switch]$Stop, [switch]$Status)
$ErrorActionPreference = 'Stop'
$geckoRoot = Split-Path $PSScriptRoot -Parent
$pythonPath = Join-Path $geckoRoot '.tools\dashboard-python\Scripts\python.exe'
$workerScript = Join-Path $geckoRoot 'dashboard\remote_worker.py'
$pidPath = Join-Path $geckoRoot 'scratch\dashboard\remote-worker.pid'
$configPath = Join-Path $geckoRoot '.secrets\gecko-web-worker.json'
$workerProcess = $null
if (Test-Path -LiteralPath $pidPath) {
    $workerPid = [int](Get-Content -LiteralPath $pidPath -Raw).Trim()
    $candidate = Get-CimInstance Win32_Process -Filter "ProcessId=$workerPid" -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.ExecutablePath -eq $pythonPath -and $candidate.CommandLine.Contains($workerScript)) { $workerProcess = $candidate }
}
if ($Stop) {
    if ($workerProcess) { Stop-Process -Id $workerProcess.ProcessId; Write-Output 'Gecko online connection stopped. Local dashboard and workflows were left running.' }
    else { Write-Output 'Gecko online connection is not running.' }
    return
}
if ($Status) {
    if ($workerProcess) { Write-Output 'Gecko online connection process is running. Check the website for confirmed connectivity.' }
    else { Write-Output 'Gecko online connection is not running.' }
    return
}
if ($workerProcess) { Write-Output 'Gecko online connection is already running.'; return }
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Prepare the private online connection settings first. See docs/gecko-online.md.' }
$settings = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if (-not $settings.url) { throw 'The final Gecko website address has not been paired yet. See docs/gecko-online.md.' }
& (Join-Path $PSScriptRoot 'Start-Gecko-Dashboard.ps1') -NoBrowser
$logFolder = Join-Path $geckoRoot 'scratch\dashboard'
$process = Start-Process -FilePath $pythonPath -ArgumentList @('"' + $workerScript + '"') -WorkingDirectory $geckoRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logFolder 'remote-worker.log') -RedirectStandardError (Join-Path $logFolder 'remote-worker-error.log') -PassThru
Start-Sleep -Seconds 2
if ($process.HasExited) { throw 'The online connection stopped. Check scratch/dashboard/remote-worker-error.log.' }
Set-Content -LiteralPath $pidPath -Value $process.Id
Write-Output 'Gecko online connection process started. The website will show whether the connection is confirmed.'
