[CmdletBinding()]
param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$scratchRoot = Join-Path $projectRoot 'scratch'
$bridgeScript = Join-Path $PSScriptRoot 'word_validation_bridge.ps1'
$watchdogScript = Join-Path $PSScriptRoot 'word_validation_bridge_watchdog.ps1'
$heartbeatPath = Join-Path $scratchRoot 'word-validation-bridge-heartbeat.json'
$installationPath = Join-Path $scratchRoot 'word-validation-bridge-installation.json'
$healthScript = Join-Path $PSScriptRoot 'Test-Gecko-Word-Bridge.ps1'
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
. (Join-Path $PSScriptRoot 'word_bridge_common.ps1')

if ($currentUser -match '(?i)codexsandbox') {
    throw 'Run this one-time installer from the normal Windows user session, not from the Codex sandbox.'
}
if (-not [Environment]::UserInteractive -or [System.Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0) {
    throw 'Run this one-time installer from an interactive Windows desktop session.'
}

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $script:GeckoWordBridgeWatchdogTaskName -ErrorAction SilentlyContinue
    Stop-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $script:GeckoWordBridgeWatchdogTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $heartbeatPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $installationPath -Force -ErrorAction SilentlyContinue
    Write-Output "Removed scheduled tasks: $($script:GeckoWordBridgeTaskName), $($script:GeckoWordBridgeWatchdogTaskName)"
    exit 0
}

foreach ($required in @($bridgeScript, $watchdogScript, $healthScript)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required bridge component is missing: $required"
    }
}
if (-not (Test-GeckoWordCom)) {
    throw 'Microsoft Word COM is not available under the current interactive Windows user.'
}
Write-Output 'Interactive Microsoft Word COM check passed.'

if (-not (Test-Path -LiteralPath $scratchRoot)) {
    New-Item -ItemType Directory -Path $scratchRoot -Force | Out-Null
}

$powerShell = Join-Path $PSHOME 'powershell.exe'
$bridgeArguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$bridgeScript`""
$watchdogArguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$watchdogScript`""
$bridgeAction = New-ScheduledTaskAction -Execute $powerShell -Argument $bridgeArguments -WorkingDirectory $projectRoot
$watchdogAction = New-ScheduledTaskAction -Execute $powerShell -Argument $watchdogArguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# Reinstalling is safe: replace the definitions in place, then restart both
# hidden tasks so script upgrades take effect immediately.
Stop-ScheduledTask -TaskName $script:GeckoWordBridgeWatchdogTaskName -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName $script:GeckoWordBridgeTaskName `
    -Action $bridgeAction `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Hidden Gecko worker that processes Microsoft Word pagination requests in the logged-in user session.' `
    -Force | Out-Null

Register-ScheduledTask `
    -TaskName $script:GeckoWordBridgeWatchdogTaskName `
    -Action $watchdogAction `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Hidden self-healing supervisor for the Gecko Word Validation Bridge.' `
    -Force | Out-Null

Write-GeckoJsonAtomic -Value ([ordered]@{
    installed_at = (Get-Date).ToString('o')
    user = $currentUser
    bridge_task = $script:GeckoWordBridgeTaskName
    watchdog_task = $script:GeckoWordBridgeWatchdogTaskName
    bridge_script = $bridgeScript
    watchdog_script = $watchdogScript
    startup = 'interactive-user-logon'
    hidden = $true
}) -Path $installationPath

Remove-Item -LiteralPath $heartbeatPath -Force -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName
Start-ScheduledTask -TaskName $script:GeckoWordBridgeWatchdogTaskName

$deadline = (Get-Date).AddSeconds(30)
do {
    Start-Sleep -Milliseconds 500
    if (Test-GeckoBridgeHeartbeatHealthy -Path $heartbeatPath -RequireLiveProcess) {
        Write-Output "Installed and started: $($script:GeckoWordBridgeTaskName)"
        Write-Output "Installed and started: $($script:GeckoWordBridgeWatchdogTaskName)"
        & $healthScript
        exit $LASTEXITCODE
    }
} while ((Get-Date) -lt $deadline)

throw "The scheduled tasks were registered, but the bridge did not become healthy. Run: powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$healthScript`""
