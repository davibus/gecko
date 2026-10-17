param([Parameter(Mandatory=$true)][string]$RequestFile)
$ErrorActionPreference = 'Stop'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\Gecko-OpenClaw-Connection.ps1" -Action Check *> $null
if ($LASTEXITCODE -ne 0) { exit 1 }
$cli = Join-Path $env:APPDATA 'npm\openclaw.cmd'
$session = 'agent:gecko:manual-read-' + [guid]::NewGuid().ToString('N')
& $cli agent --agent gecko --session-key $session --message-file $RequestFile --timeout 150 --json
exit $LASTEXITCODE
