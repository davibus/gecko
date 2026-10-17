[CmdletBinding()]
param(
    [ValidateSet('Check', 'Login', 'Run')]
    [string]$Action = 'Check',
    [ValidatePattern('^[a-zA-Z0-9_-]+$')]
    [string]$Agent = 'gecko',
    [string]$ProfileId,
    [switch]$ProbeModel,
    [string]$RequestFile,
    [ValidateRange(30, 3600)]
    [int]$TimeoutSeconds = 1800
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$openClawPath = Join-Path $env:APPDATA 'npm\openclaw.cmd'
$statePath = Join-Path $env:USERPROFILE '.openclaw'
$configPath = Join-Path $statePath 'openclaw.json'

function Invoke-GeckoOpenClawJson {
    param([string[]]$Arguments)
    # Windows PowerShell represents redirected native stderr as error records.
    # Collect those records and inspect the exit code instead of stopping early.
    $ErrorActionPreference = 'Continue'
    $lines = @(& $openClawPath @Arguments 2>&1)
    $nativeExit = $LASTEXITCODE
    $raw = ($lines | ForEach-Object { $_.ToString() }) -join "`n"
    # Provider/gateway messages can precede the CLI's JSON document.
    $firstBrace = $raw.IndexOf('{')
    $lastBrace = $raw.LastIndexOf('}')
    $document = $null
    if ($firstBrace -ge 0 -and $lastBrace -gt $firstBrace) {
        try { $document = $raw.Substring($firstBrace, $lastBrace - $firstBrace + 1) | ConvertFrom-Json }
        catch { $document = $null }
    }
    if ($nativeExit -ne 0 -or $null -eq $document) {
        # Do not echo raw provider output, URLs, or credentials into logs.
        $detail = ('OpenClaw {0} failed (exit {1}; JSON parsed: {2}).' -f $Arguments[0], $nativeExit, ($null -ne $document))
        if ($document.error.type -eq 'gateway_transport_error') {
            if ($document.error.kind -eq 'timeout') {
                $detail = 'The existing native Gateway health request timed out. Check the OpenClaw Gateway task; no service restart or sign-in was attempted.'
            } else {
                $detail = 'Cannot reach the existing native Gateway. Check its task and local authentication configuration; no service restart or sign-in was attempted.'
            }
        } elseif ($raw -match 'model is not supported|model_not_found') {
            $detail = 'The selected model is unavailable for this account. Recheck model access; repeating login will not fix a model choice.'
        } elseif ($Arguments[0] -eq 'agent' -and $raw -match 'auth issue|403 Forbidden|401|reauth|saved connection settings|cannot verify the owner') {
            $detail = 'OpenClaw needs a fresh OpenAI sign-in. Run this helper with -Action Login.'
        } elseif ($raw -match 'rate.limit|usage.limit|quota') {
            $detail = 'The provider reported a usage or rate limit. Wait for the limit to reset; repeated login is not a fix.'
        }
        throw $detail
    }
    return $document
}

function Test-GeckoOpenClawConnection {
    param([switch]$IncludeModelProbe)
    $validation = Invoke-GeckoOpenClawJson -Arguments @('config', 'validate', '--json')
    if (-not $validation.valid -or $validation.path -ne $configPath) {
        throw 'The native OpenClaw configuration did not validate at the expected Windows path.'
    }
    $health = Invoke-GeckoOpenClawJson -Arguments @('health', '--timeout', '60000', '--json')
    if (-not $health.ok -or -not (@($health.agents.agentId) -contains $Agent)) {
        throw 'The existing local Gateway is unhealthy or does not expose the requested agent. No service was started.'
    }
    Write-Host ('Native Gateway healthy at 127.0.0.1:18889. Agent: ' + $Agent)
    if (-not $IncludeModelProbe) {
        Write-Host 'Provider inference and browser autofill were not tested. Use -ProbeModel for an isolated model check.'
        return
    }
    Write-Host 'Testing an isolated Gecko model response through the running Gateway...'
    $key = 'agent:' + $Agent + ':connection-check-' + [guid]::NewGuid().ToString('N')
    $response = Invoke-GeckoOpenClawJson -Arguments @(
        'agent', '--agent', $Agent, '--session-key', $key,
        '--message', 'Connection check only. Reply exactly GECKO_CONNECTION_OK. Do not call tools, read files, submit applications, or modify anything.',
        '--timeout', '120', '--json'
    )
    $reply = @($response.result.payloads | ForEach-Object { $_.text }) -join "`n"
    if ($response.status -ne 'ok' -or $reply.Trim() -ne 'GECKO_CONNECTION_OK') {
        throw 'The live connection check did not complete successfully. No application request was started.'
    }
    Write-Host ('Connection verified. Model: ' + $response.result.meta.agentMeta.model)
}

try {
    if (-not (Test-Path -LiteralPath $openClawPath -PathType Leaf)) {
        throw ('The installed native Windows OpenClaw CLI is missing: ' + $openClawPath)
    }
    foreach ($setting in @(@('OPENCLAW_STATE_DIR', $statePath), @('OPENCLAW_CONFIG_PATH', $configPath))) {
        $override = [Environment]::GetEnvironmentVariable($setting[0])
        if ($override -and [IO.Path]::GetFullPath($override) -ne $setting[1]) {
            throw ('Clear the unexpected ' + $setting[0] + ' override before using the native connection helper.')
        }
    }
    if ($env:OPENCLAW_PROFILE -or $env:OPENCLAW_AGENT_DIR -or
        ($env:OPENCLAW_GATEWAY_URL -and $env:OPENCLAW_GATEWAY_URL -ne 'ws://127.0.0.1:18889')) {
        throw 'An OpenClaw environment override selects a different profile, agent directory, or Gateway. Clear it first.'
    }
    try { $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw 'The native Windows OpenClaw configuration could not be read as JSON.' }
    if ($config.gateway.mode -ne 'local' -or $config.gateway.port -ne 18889 -or $config.gateway.bind -ne 'loopback') {
        throw 'Expected the existing native local Gateway bound to loopback port 18889. Configuration was not changed.'
    }
    if ($Action -eq 'Run') {
        if (-not $RequestFile) { throw '-RequestFile is required for -Action Run.' }
        $requestPath = (Resolve-Path -LiteralPath $RequestFile).ProviderPath
        if (-not (Test-Path -LiteralPath $requestPath -PathType Leaf) -or (Get-Item -LiteralPath $requestPath).Length -eq 0) {
            throw 'The application request file must be a non-empty local file.'
        }
    }
    if ($Action -eq 'Login') {
        Write-Host 'Complete the OpenAI sign-in in your browser. If the callback does not complete, paste its redirect URL into this terminal when prompted.'
        $loginArguments = @('models', 'auth', 'login', '--provider', 'openai', '--agent', $Agent)
        if ($ProfileId) { $loginArguments += @('--profile-id', $ProfileId) }
        & $openClawPath @loginArguments
        if ($LASTEXITCODE -ne 0) { throw 'OpenAI sign-in did not complete. No application request was started.' }
    }
    Test-GeckoOpenClawConnection -IncludeModelProbe:($ProbeModel -or $Action -ne 'Check')
    if ($Action -eq 'Run') {
        Write-Host 'Connection passed. Starting the supplied application request.'
        $key = 'agent:' + $Agent + ':gecko-request-' + [guid]::NewGuid().ToString('N')
        & $openClawPath agent --agent $Agent --session-key $key --message-file $requestPath --timeout $TimeoutSeconds
        if ($LASTEXITCODE -ne 0) {
            throw 'The application request stopped. Check per-job confirmation evidence before retrying; a failed command does not prove that nothing submitted.'
        }
    }
    exit 0
} catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
