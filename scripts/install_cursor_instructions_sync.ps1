[CmdletBinding()]
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
$taskName = 'Gecko Cursor Instructions Sync'
$projectRoot = Split-Path -Parent $PSScriptRoot
$syncScript = Join-Path $PSScriptRoot 'sync_cursor_instructions.py'
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Removed scheduled task: $taskName"
    exit 0
}

$python = (Get-Command python.exe -ErrorAction Stop).Source
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) {
    throw "pythonw.exe is missing beside $python"
}
if (-not (Test-Path -LiteralPath $syncScript)) {
    throw "Sync script is missing: $syncScript"
}

$arguments = "`"$syncScript`" watch --file AGENTS.md --tab `"Cursor Instructions`" --sheet-id 2074656464 --cell A1 --interval-seconds 60"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $projectRoot
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

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Hidden Gecko AGENTS.md and Cursor Instructions Sheet cell sync watcher.' `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Write-Output "Installed and started scheduled task: $taskName"
Write-Output "Watcher status: $(Join-Path $projectRoot 'scratch\cursor-sheet-sync\watch-status.json')"
