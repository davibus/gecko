param([string]$RequestFile, [Parameter(Mandatory=$true)][string]$SessionKey, [switch]$Abort)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$cli = Join-Path $env:APPDATA 'npm\openclaw.cmd'
if ($SessionKey -notmatch '^agent:gecko:dashboard-apply-[a-f0-9]{32}$') { throw 'Invalid application session.' }
if ($Abort) {
    $parameters = @{ sessionKey=$SessionKey; agentId='gecko' } | ConvertTo-Json -Compress
    # Windows PowerShell 5 strips native argument quotes unless escaped.
    $nativeParameters = $parameters.Replace('"', '\"')
    & $cli gateway call chat.abort --params $nativeParameters --json --timeout 15000
    exit $LASTEXITCODE
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\Gecko-OpenClaw-Connection.ps1" -Action Check *> $null
if ($LASTEXITCODE -ne 0) { exit 1 }
& $cli agent --agent gecko --session-key $SessionKey --message-file $RequestFile --timeout 600 --json
exit $LASTEXITCODE
