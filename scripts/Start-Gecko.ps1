param([switch]$Status)
$ErrorActionPreference = 'Stop'
if ($Status) {
    $task = Get-ScheduledTask -TaskName 'Gecko'
    $info = Get-ScheduledTaskInfo -TaskName 'Gecko'
    Write-Output "Gecko task: $($task.State); last result: $($info.LastTaskResult)"
    $statusPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'reports\gecko-command\latest.json'
    if (Test-Path -LiteralPath $statusPath) { Get-Content -LiteralPath $statusPath }
    exit 0
}
$task = Get-ScheduledTask -TaskName 'Gecko'
if ($task.State -eq 'Running') {
    Write-Output 'Gecko is already running. Use Gecko --status to see progress.'
    exit 0
}
Start-ScheduledTask -TaskName 'Gecko'
Write-Output 'Gecko started. Use Gecko --status to see progress.'
