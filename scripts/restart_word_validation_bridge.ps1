[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$heartbeatPath = Join-Path $projectRoot 'scratch\word-validation-bridge-heartbeat.json'
$healthScript = Join-Path $PSScriptRoot 'Test-Gecko-Word-Bridge.ps1'
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
. (Join-Path $PSScriptRoot 'word_bridge_common.ps1')

if ($currentUser -match '(?i)codexsandbox') {
    throw 'Run the restart command from the normal Windows user session, not from the Codex sandbox.'
}

$null = Get-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName -ErrorAction Stop
$null = Get-ScheduledTask -TaskName $script:GeckoWordBridgeWatchdogTaskName -ErrorAction Stop
Stop-ScheduledTask -TaskName $script:GeckoWordBridgeWatchdogTaskName -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Remove-Item -LiteralPath $heartbeatPath -Force -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName
Start-ScheduledTask -TaskName $script:GeckoWordBridgeWatchdogTaskName

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Milliseconds 500
    if (Test-GeckoBridgeHeartbeatHealthy -Path $heartbeatPath -RequireLiveProcess) {
        Write-Output 'Gecko Word Validation Bridge restarted successfully.'
        & $healthScript
        exit $LASTEXITCODE
    }
} while ((Get-Date) -lt $deadline)

throw "The bridge restart did not become healthy within 30 seconds. Run: powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$healthScript`""
