[CmdletBinding()]
param(
    [ValidateSet('Check', 'Login', 'Run')]
    [string]$Action = 'Check',
    [string]$Distribution = 'Ubuntu-24.04',
    [string]$Agent = 'gecko-resume-application-assistant',
    [string]$ProfileId = 'openai:setup-755aae44-a859-405b-b318-ede81b8d9332',
    [string]$RequestFile,
    [ValidateRange(30, 3600)]
    [int]$TimeoutSeconds = 1800
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$openClawPath = '/home/dcall/.openclaw/bin/openclaw'

function Invoke-GeckoOpenClawJson {
    param([string[]]$Arguments)
    # Windows PowerShell represents redirected native stderr as error records.
    # Collect those records and inspect the exit code instead of stopping early.
    $ErrorActionPreference = 'Continue'
    $lines = @(& wsl.exe -d $Distribution -- $openClawPath @Arguments 2>&1)
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
        $detail = 'OpenClaw did not return a successful response.'
        if ($raw -match 'model is not supported|model_not_found') {
            $detail = 'The selected model is unavailable for this account. Recheck model access; repeating login will not fix a model choice.'
        } elseif ($raw -match 'auth issue|403 Forbidden|401|reauth|saved connection settings|cannot verify the owner') {
            $detail = 'OpenClaw needs a fresh OpenAI sign-in. Run this helper with -Action Login.'
        } elseif ($raw -match 'rate.limit|usage.limit|quota') {
            $detail = 'The provider reported a usage or rate limit. Wait for the limit to reset; repeated login is not a fix.'
        }
        throw $detail
    }
    return $document
}

function Test-GeckoOpenClawConnection {
    Write-Host 'Testing Gecko through the running OpenClaw gateway...'
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
    if ($Action -eq 'Run') {
        if (-not $RequestFile) { throw '-RequestFile is required for -Action Run.' }
        $requestPath = (Resolve-Path -LiteralPath $RequestFile).ProviderPath
        if (-not (Test-Path -LiteralPath $requestPath -PathType Leaf) -or (Get-Item -LiteralPath $requestPath).Length -eq 0) {
            throw 'The application request file must be a non-empty local file.'
        }
        # Forward slashes survive WSL's native argument handling on PowerShell 5.
        $wslRequest = @(& wsl.exe -d $Distribution -- wslpath -a -u ($requestPath.Replace('\', '/')))
        if ($LASTEXITCODE -ne 0 -or $wslRequest.Count -ne 1) { throw 'Cannot resolve the request file in WSL.' }
    }
    if ($Action -eq 'Login') {
        Write-Host 'Complete the OpenAI sign-in in your browser. If the callback does not complete, paste its redirect URL into this terminal when prompted.'
        & wsl.exe -d $Distribution -- $openClawPath models auth login --provider openai --agent $Agent --profile-id $ProfileId
        if ($LASTEXITCODE -ne 0) { throw 'OpenAI sign-in did not complete. No application request was started.' }
    }
    Test-GeckoOpenClawConnection
    if ($Action -eq 'Run') {
        Write-Host 'Connection passed. Starting the supplied application request.'
        $key = 'agent:' + $Agent + ':gecko-request-' + [guid]::NewGuid().ToString('N')
        & wsl.exe -d $Distribution -- $openClawPath agent --agent $Agent --session-key $key --message-file ($wslRequest[0].Trim()) --timeout $TimeoutSeconds
        if ($LASTEXITCODE -ne 0) {
            throw 'The application request stopped. Check per-job confirmation evidence before retrying; a failed command does not prove that nothing submitted.'
        }
    }
    exit 0
} catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
