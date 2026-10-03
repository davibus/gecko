$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$runner = Join-Path $PSScriptRoot 'run_cursor_overnight.ps1'
$fakeAgent = Join-Path $PSScriptRoot 'fixtures\fake_cursor_agent.ps1'
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gecko-cursor-overnight-{0}" -f [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null

try {
    $env:CURSOR_OVERNIGHT_TEST_MODE = '1'
    $env:CURSOR_OVERNIGHT_FAKE_SCENARIO = 'limit-then-success'
    $env:CURSOR_OVERNIGHT_FAKE_STATE = Join-Path $testRoot 'fake-count.txt'
    $stateDirectory = Join-Path $testRoot 'state'

    $started = [DateTimeOffset]::UtcNow
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner `
        -Prompt 'Perform the fake idempotent task.' `
        -Workspace (Split-Path -Parent $PSScriptRoot) `
        -StateDirectory $stateDirectory `
        -AgentPath $fakeAgent `
        -MinimumRetrySeconds 1 `
        -TestMode
    if ($LASTEXITCODE -ne 0) {
        throw "Limit/resume test failed with exit code $LASTEXITCODE."
    }
    $elapsed = ([DateTimeOffset]::UtcNow - $started).TotalSeconds
    if ($elapsed -lt 1.8) {
        throw "Reported retry-after was not respected; elapsed only $elapsed seconds."
    }

    $checkpoint = Get-Content -LiteralPath (Join-Path $stateDirectory 'checkpoint.json') -Raw | ConvertFrom-Json
    if ($checkpoint.status -ne 'completed' -or $checkpoint.sessionId -ne 'fake-session-123' -or [int]$checkpoint.attempt -ne 2) {
        throw 'Checkpoint did not record two attempts, the session ID, and successful completion.'
    }
    $invocationCount = [int](Get-Content -LiteralPath $env:CURSOR_OVERNIGHT_FAKE_STATE -Raw)
    if ($invocationCount -ne 2) {
        throw "Expected two fake model invocations, found $invocationCount."
    }

    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner `
        -Prompt 'Perform the fake idempotent task.' `
        -Workspace (Split-Path -Parent $PSScriptRoot) `
        -StateDirectory $stateDirectory `
        -AgentPath $fakeAgent `
        -MinimumRetrySeconds 1 `
        -TestMode
    if ($LASTEXITCODE -ne 0) {
        throw "Completed-task rerun test failed with exit code $LASTEXITCODE."
    }
    $rerunCount = [int](Get-Content -LiteralPath $env:CURSOR_OVERNIGHT_FAKE_STATE -Raw)
    if ($rerunCount -ne 2) {
        throw 'A completed task was incorrectly sent to Cursor again.'
    }

    $argsText = Get-Content -LiteralPath "$($env:CURSOR_OVERNIGHT_FAKE_STATE).args" -Raw
    if ($argsText -notmatch [regex]::Escape('--resume=fake-session-123')) {
        throw 'Resume session argument was not passed to the fake agent.'
    }

    $env:CURSOR_OVERNIGHT_FAKE_SCENARIO = 'auth'
    $env:CURSOR_OVERNIGHT_FAKE_STATE = Join-Path $testRoot 'auth-count.txt'
    $authStateDirectory = Join-Path $testRoot 'auth-state'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner `
        -Prompt 'Perform a fake task that encounters authentication failure.' `
        -Workspace (Split-Path -Parent $PSScriptRoot) `
        -StateDirectory $authStateDirectory `
        -AgentPath $fakeAgent `
        -MinimumRetrySeconds 1 `
        -TestMode
    if ($LASTEXITCODE -eq 0) {
        throw 'Authentication failure should have returned a nonzero exit code.'
    }
    $authCount = [int](Get-Content -LiteralPath $env:CURSOR_OVERNIGHT_FAKE_STATE -Raw)
    if ($authCount -ne 1) {
        throw "Authentication failure was retried; invocation count was $authCount."
    }

    Write-Host 'PASS: retry-after, same-session resume, completion guard, checkpoints, logs, and non-retryable exit.'
}
finally {
    Remove-Item Env:CURSOR_OVERNIGHT_TEST_MODE -ErrorAction SilentlyContinue
    Remove-Item Env:CURSOR_OVERNIGHT_FAKE_SCENARIO -ErrorAction SilentlyContinue
    Remove-Item Env:CURSOR_OVERNIGHT_FAKE_STATE -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
