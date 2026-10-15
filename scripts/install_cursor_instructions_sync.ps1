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

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    $current = $existing.Actions | Select-Object -First 1
    if ($existing.Actions.Count -ne 1) { throw "Unexpected action count for $taskName" }
    if ($current.Execute -ne $action.Execute -or $current.Arguments -ne $action.Arguments -or $current.WorkingDirectory -ne $projectRoot) {
        $backupDir = Join-Path $projectRoot 'scratch\task-backups'
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        $backup = Join-Path $backupDir ("Gecko_Cursor_Instructions_Sync-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.xml')
        Export-ScheduledTask -TaskName $taskName -TaskPath $existing.TaskPath | Set-Content -LiteralPath $backup -Encoding UTF8
        Set-ScheduledTask -TaskName $taskName -Action $action | Out-Null
        Write-Output "Updated action for $taskName (backup: $backup)"
    }
} else {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description 'Hidden Gecko AGENTS.md and Cursor Instructions Sheet cell sync watcher.' | Out-Null
}

if ((Get-ScheduledTask -TaskName $taskName).State -ne 'Running') {
    Start-ScheduledTask -TaskName $taskName
}
Write-Output "Installed and running scheduled task: $taskName"
Write-Output "Watcher status: $(Join-Path $projectRoot 'scratch\cursor-sheet-sync\watch-status.json')"
