$script:GeckoWordBridgeTaskName = 'Gecko Word Validation Bridge'
$script:GeckoWordBridgeWatchdogTaskName = 'Gecko Word Validation Bridge Watchdog'
$script:GeckoWordBridgeHealthySeconds = 300
$script:GeckoWordBridgeRestartSeconds = 420

function Write-GeckoJsonAtomic {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $directory = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $temporary = "$Path.$PID.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        $Value | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $temporary -Encoding UTF8
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally {
        Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    }
}

function Read-GeckoBridgeHeartbeat {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Get-GeckoHeartbeatAgeSeconds {
    param([object]$Heartbeat)

    if ($null -eq $Heartbeat -or [string]::IsNullOrWhiteSpace([string]$Heartbeat.updated_at)) {
        return [double]::PositiveInfinity
    }
    try {
        $updated = [DateTimeOffset]::Parse([string]$Heartbeat.updated_at)
        return [Math]::Max(0, ([DateTimeOffset]::UtcNow - $updated.ToUniversalTime()).TotalSeconds)
    } catch {
        return [double]::PositiveInfinity
    }
}

function Test-GeckoBridgeProcessAlive {
    param([object]$Heartbeat)

    if ($null -eq $Heartbeat -or -not ([string]$Heartbeat.process_id -match '^\d+$')) {
        return $false
    }
    try {
        $process = Get-Process -Id ([int]$Heartbeat.process_id) -ErrorAction Stop
        if ($Heartbeat.process_started_at) {
            $expected = [DateTimeOffset]::Parse([string]$Heartbeat.process_started_at).ToUniversalTime()
            $actual = ([DateTimeOffset]$process.StartTime).ToUniversalTime()
            if ([Math]::Abs(($actual - $expected).TotalSeconds) -gt 5) {
                return $false
            }
        }
        return $true
    } catch {
        return $false
    }
}

function Test-GeckoBridgeHeartbeatHealthy {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$MaximumAgeSeconds = $script:GeckoWordBridgeHealthySeconds,
        [switch]$RequireLiveProcess
    )

    $heartbeat = Read-GeckoBridgeHeartbeat -Path $Path
    if ($null -eq $heartbeat) {
        return $false
    }
    $healthyStatus = [string]$heartbeat.status -in @('running', 'busy')
    $healthyUser = -not ([string]$heartbeat.user -match '(?i)codexsandbox')
    $fresh = (Get-GeckoHeartbeatAgeSeconds -Heartbeat $heartbeat) -le $MaximumAgeSeconds
    $processOkay = -not $RequireLiveProcess -or (Test-GeckoBridgeProcessAlive -Heartbeat $heartbeat)
    return $healthyStatus -and $healthyUser -and $fresh -and $processOkay
}

function Get-GeckoInteractiveUser {
    param([object]$Heartbeat, [object]$Installation)

    try {
        $user = [string](Get-CimInstance Win32_ComputerSystem -ErrorAction Stop).UserName
        if (-not [string]::IsNullOrWhiteSpace($user)) {
            return $user
        }
    } catch {
        # Cross-token CIM access can be denied inside the Codex sandbox.
    }
    if ($null -ne $Heartbeat -and -not [string]::IsNullOrWhiteSpace([string]$Heartbeat.user)) {
        return [string]$Heartbeat.user
    }
    if ($null -ne $Installation -and -not [string]::IsNullOrWhiteSpace([string]$Installation.user)) {
        return [string]$Installation.user
    }
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
}

function Test-GeckoWordCom {
    $word = $null
    try {
        $word = New-Object -ComObject Word.Application
        $word.Visible = $false
        $word.DisplayAlerts = 0
        $null = [string]$word.Version
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $word) {
            try { $word.Quit() } catch { }
        }
    }
}
