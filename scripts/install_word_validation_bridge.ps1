[CmdletBinding()]
param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$taskName = 'Gecko Word Validation Bridge'
$projectRoot = Split-Path -Parent $PSScriptRoot
$bridgeScript = Join-Path $PSScriptRoot 'word_validation_bridge.ps1'
$heartbeatPath = Join-Path $projectRoot 'scratch\word-validation-bridge-heartbeat.json'
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if ($currentUser -match 'codexsandbox') {
    throw 'Run this installer from the normal Windows desktop session, not from the Codex sandbox.'
}

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $heartbeatPath -Force -ErrorAction SilentlyContinue
    Write-Output "Removed scheduled task: $taskName"
    exit 0
}

if (-not (Test-Path -LiteralPath $bridgeScript)) {
    throw "Bridge script is missing: $bridgeScript"
}

$word = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $wordVersion = [string]$word.Version
} finally {
    if ($null -ne $word) {
        $word.Quit()
    }
}
Write-Output "Interactive Microsoft Word COM check passed (Word $wordVersion)."

$powerShell = Join-Path $PSHOME 'powershell.exe'
$arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$bridgeScript`""
$action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
# A transient PowerShell/Word/file-system error should not exhaust the
# bridge after three attempts. The worker also contains its own supervisor.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Processes Gecko Microsoft Word pagination requests in the interactive desktop session.' `
    -Force | Out-Null

Remove-Item -LiteralPath $heartbeatPath -Force -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $taskName

$deadline = (Get-Date).AddSeconds(20)
do {
    Start-Sleep -Milliseconds 500
    if (Test-Path -LiteralPath $heartbeatPath) {
        $heartbeat = Get-Content -LiteralPath $heartbeatPath -Raw | ConvertFrom-Json
        if ($heartbeat.status -eq 'running' -and $heartbeat.user -eq $currentUser) {
            Write-Output "Installed and started: $taskName"
            Write-Output "Bridge user: $($heartbeat.user); session: $($heartbeat.session_id); PID: $($heartbeat.process_id)"
            exit 0
        }
    }
} while ((Get-Date) -lt $deadline)

throw "The scheduled task was registered but did not produce a heartbeat at $heartbeatPath."
