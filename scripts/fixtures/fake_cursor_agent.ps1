param([Parameter(ValueFromRemainingArguments = $true)][string[]]$AgentArguments)

$ErrorActionPreference = 'Stop'
$stateFile = $env:CURSOR_OVERNIGHT_FAKE_STATE
if (-not $stateFile) {
    [Console]::Error.WriteLine('CURSOR_OVERNIGHT_FAKE_STATE is required.')
    exit 99
}

if ($AgentArguments.Count -gt 0 -and $AgentArguments[0] -eq 'status') {
    Write-Output 'Logged in (fake test agent)'
    exit 0
}

$count = 0
if (Test-Path -LiteralPath $stateFile) {
    $count = [int](Get-Content -LiteralPath $stateFile -Raw)
}
$count++
Set-Content -LiteralPath $stateFile -Value $count -Encoding ASCII
Add-Content -LiteralPath "$stateFile.args" -Value (($AgentArguments -join '|')) -Encoding UTF8

if ($env:CURSOR_OVERNIGHT_FAKE_SCENARIO -eq 'auth') {
    Write-Output 'Authentication failed: please log in'
    exit 1
}

if ($count -eq 1) {
    Write-Output '{"type":"system","subtype":"init","session_id":"fake-session-123"}'
    Write-Output '429 usage limit reached; retry after 2 seconds'
    exit 75
}

if (-not ($AgentArguments -contains '--resume=fake-session-123')) {
    Write-Output 'Expected the second attempt to resume fake-session-123'
    exit 98
}
Write-Output '{"type":"assistant","subtype":"progress","session_id":"fake-session-123"}'
Write-Output '{"type":"result","subtype":"success","is_error":false,"session_id":"fake-session-123","result":"done"}'
exit 0
