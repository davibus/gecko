[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$SkipWordComProbe,
    [string]$HeartbeatPath
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$scratchRoot = Join-Path $projectRoot 'scratch'
if ([string]::IsNullOrWhiteSpace($HeartbeatPath)) {
    $HeartbeatPath = Join-Path $scratchRoot 'word-validation-bridge-heartbeat.json'
}
$installationPath = Join-Path $scratchRoot 'word-validation-bridge-installation.json'
. (Join-Path $PSScriptRoot 'word_bridge_common.ps1')

$heartbeat = Read-GeckoBridgeHeartbeat -Path $HeartbeatPath
$installation = $null
if (Test-Path -LiteralPath $installationPath) {
    try { $installation = Get-Content -LiteralPath $installationPath -Raw | ConvertFrom-Json } catch { }
}

$task = $null
$watchdogTask = $null
$taskAccessError = $null
try {
    $task = Get-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName -ErrorAction Stop
    $watchdogTask = Get-ScheduledTask -TaskName $script:GeckoWordBridgeWatchdogTaskName -ErrorAction SilentlyContinue
} catch {
    $taskAccessError = $_.Exception.Message
}

$installed = $null -ne $task -or $null -ne $installation
$taskState = if ($null -ne $task) { [string]$task.State } elseif ($taskAccessError) { 'UNKNOWN (access denied or unavailable)' } else { 'NOT INSTALLED' }
$watchdogState = if ($null -ne $watchdogTask) { [string]$watchdogTask.State } elseif ($taskAccessError) { 'UNKNOWN' } else { 'NOT INSTALLED' }
$processAlive = Test-GeckoBridgeProcessAlive -Heartbeat $heartbeat
$heartbeatAge = Get-GeckoHeartbeatAgeSeconds -Heartbeat $heartbeat
$heartbeatFresh = $heartbeatAge -le $script:GeckoWordBridgeHealthySeconds
$interactiveUser = Get-GeckoInteractiveUser -Heartbeat $heartbeat -Installation $installation
$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$canProbeCom = -not $SkipWordComProbe -and $currentIdentity -notmatch '(?i)codexsandbox' -and [Environment]::UserInteractive -and [System.Diagnostics.Process]::GetCurrentProcess().SessionId -ne 0
$wordComAvailable = if ($canProbeCom) {
    Test-GeckoWordCom
} elseif ($null -ne $heartbeat -and $null -ne $heartbeat.word_com_available) {
    [bool]$heartbeat.word_com_available
} else {
    $false
}

$taskHealthy = ($null -ne $task -and [string]$task.State -eq 'Running') -or ($null -eq $task -and $taskAccessError -and $processAlive)
$watchdogHealthy = ($null -ne $watchdogTask -and [string]$watchdogTask.State -eq 'Running') -or ($null -eq $watchdogTask -and $taskAccessError -and $installed)
$heartbeatStatusHealthy = $null -ne $heartbeat -and [string]$heartbeat.status -in @('running', 'busy') -and [string]$heartbeat.user -notmatch '(?i)codexsandbox'
$overallHealthy = $installed -and $taskHealthy -and $watchdogHealthy -and $processAlive -and $heartbeatFresh -and $heartbeatStatusHealthy -and $wordComAvailable

$report = [ordered]@{
    installed = if ($installed) { 'yes' } else { 'no' }
    scheduled_task_state = $taskState
    watchdog_task_state = $watchdogState
    bridge_process_alive = if ($processAlive) { 'yes' } else { 'no' }
    heartbeat_age_seconds = if ([double]::IsPositiveInfinity($heartbeatAge)) { $null } else { [Math]::Round($heartbeatAge, 1) }
    heartbeat_status = if ($null -ne $heartbeat) { [string]$heartbeat.status } else { 'missing' }
    interactive_windows_user = $interactiveUser
    bridge_user = if ($null -ne $heartbeat) { [string]$heartbeat.user } else { $null }
    word_com_available = if ($wordComAvailable) { 'yes' } else { 'no' }
    overall_status = if ($overallHealthy) { 'HEALTHY' } else { 'UNHEALTHY' }
}

if ($Json) {
    $report | ConvertTo-Json -Depth 5
} else {
    Write-Output "installed: $($report.installed)"
    Write-Output "scheduled task state: $($report.scheduled_task_state)"
    Write-Output "watchdog task state: $($report.watchdog_task_state)"
    Write-Output "bridge process alive: $($report.bridge_process_alive)"
    $ageText = if ($null -eq $report.heartbeat_age_seconds) { 'unavailable' } else { "$($report.heartbeat_age_seconds) seconds" }
    Write-Output "heartbeat age: $ageText"
    Write-Output "interactive Windows user: $($report.interactive_windows_user)"
    Write-Output "Word COM availability: $($report.word_com_available)"
    Write-Output "overall status: $($report.overall_status)"
}

if (-not $overallHealthy) {
    exit 1
}
