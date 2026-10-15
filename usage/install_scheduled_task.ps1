$ErrorActionPreference = 'Stop'
$name = 'Gecko Main Codex Usage Collector'
$projectRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'launch_collector.vbs'
$arguments = '//B //Nologo "' + $launcher + '"'
$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument $arguments -WorkingDirectory $projectRoot
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing) {
    $current = $existing.Actions | Select-Object -First 1
    $legacyAction = $current.Execute -like '*powershell*' -and $current.Arguments -like '*run_collector.ps1*'
    $managedAction = $current.Execute -like '*wscript*' -and $current.Arguments -like '*launch_collector.vbs*'
    if (-not ($legacyAction -or $managedAction)) {
        throw "A task named '$name' already exists with a different action. Nothing changed."
    }
    if ($current.Execute -ne $action.Execute -or $current.Arguments -ne $arguments -or $current.WorkingDirectory -ne $projectRoot) {
        $backupDir = Join-Path $projectRoot 'scratch\task-backups'
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        $backup = Join-Path $backupDir ("Gecko_Main_Codex_Usage_Collector-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.xml')
        Export-ScheduledTask -TaskName $name -TaskPath $existing.TaskPath | Set-Content -LiteralPath $backup -Encoding UTF8
        Set-ScheduledTask -TaskName $name -Action $action | Out-Null
        Write-Output "Updated scheduled task path: $name (backup: $backup)"
        exit 0
    }
    Write-Output "Existing scheduled task retained: $name"
    exit 0
}
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Description 'Refresh private Gecko Main Codex usage ledger and workbook.' | Out-Null
$task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
if ($task.State -eq 'Disabled') { throw "Task registered but disabled: $name" }
Write-Output "Registered $name to refresh every five minutes."
