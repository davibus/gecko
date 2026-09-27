[CmdletBinding()]
param(
    [int]$PollSeconds = 30,
    [int]$RestartAfterSeconds = 420
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$scratchRoot = Join-Path $projectRoot 'scratch'
$heartbeatPath = Join-Path $scratchRoot 'word-validation-bridge-heartbeat.json'
$logPath = Join-Path $scratchRoot 'word-validation-bridge-watchdog.log'
. (Join-Path $PSScriptRoot 'word_bridge_common.ps1')

function Write-WatchdogLog {
    param([string]$Message)
    try {
        "$(Get-Date -Format o) [$PID] $Message" | Add-Content -LiteralPath $logPath -Encoding UTF8
    } catch { }
}

if (-not (Test-Path -LiteralPath $scratchRoot)) {
    New-Item -ItemType Directory -Path $scratchRoot -Force | Out-Null
}

Write-WatchdogLog 'Watchdog started.'
while ($true) {
    try {
        $healthy = Test-GeckoBridgeHeartbeatHealthy `
            -Path $heartbeatPath `
            -MaximumAgeSeconds ([Math]::Max($script:GeckoWordBridgeHealthySeconds, $RestartAfterSeconds)) `
            -RequireLiveProcess
        if (-not $healthy) {
            $task = Get-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName -ErrorAction Stop
            Write-WatchdogLog "Bridge unhealthy; scheduled task state=$($task.State). Restarting it."
            Stop-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 1
            Remove-Item -LiteralPath $heartbeatPath -Force -ErrorAction SilentlyContinue
            Start-ScheduledTask -TaskName $script:GeckoWordBridgeTaskName -ErrorAction Stop
        }
    } catch {
        Write-WatchdogLog "Watchdog check failed and will retry: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds ([Math]::Max(10, $PollSeconds))
}
