# OpenClaw browser connection on native Windows

## Current setup verified October 16, 2026

OpenClaw's existing native Windows Gateway runs through the `OpenClaw Gateway`
Scheduled Task at `127.0.0.1:18889`. State is
`C:\Users\DCALL\.openclaw`, CLI is
`C:\Users\DCALL\AppData\Roaming\npm\openclaw.cmd`, agent is `gecko`.

The current browser configuration is preserved:

- Browser enabled; default profile `windows-chrome`.
- Extension driver on loopback relay port `18899`.
- Browser and OpenAI plugins enabled.
- Node-proxy profile allowlist restricted to `windows-chrome`; automatic node
  updates disabled. These restrictions are retained because the installed
  browser plugin also consults node-proxy availability and an absent allowlist
  would widen the default proxy surface.

The obsolete `gateway.remote.url = ws://127.0.0.1:18789` was removed after a
private backup. Gateway mode remains local, port 18889, bind loopback;
authentication, agents, model/account settings, and browser configuration remain.
The installed CLI validates the edited configuration. Its reload policy marks
`gateway.remote` as requiring no Gateway restart.

## Read-only native checks

```powershell
$cli = 'C:\Users\DCALL\AppData\Roaming\npm\openclaw.cmd'
& $cli config validate --json
& $cli health --json
& $cli browser --browser-profile windows-chrome --timeout 10000 --json status
& $cli browser --browser-profile windows-chrome --timeout 10000 --json tabs
```

Tab metadata may be private; do not publish an unfiltered tab listing. Gateway
health, an open relay port, installed extensions, or an empty tab list do not
prove browser connectivity. Browser verification requires reading the known
title and URL of an ordinary page through this native OpenClaw profile. Autofill
requires its own real browser test and must not be inferred from tab access.

## Retired integration and cleanup boundary

The October 13 integration used a Linux Gateway on port 18789 and a separate
Windows browser-only node named `Gecko Main Windows Chrome`. That historical
result does not establish current browser connectivity. The old `OpenClaw Node`
task and its isolated runtime are absent; the current Gateway reports no nodes.
WSL and Virtual Machine Platform are disabled, no Ubuntu/WSL package or registered
distribution was found, and no Linux VM process was observed. No WSL executable
was invoked, installed, started, or removed for this cleanup.

The old `scripts/list_windows_chrome_tabs.py` uses a Linux executable and
`openclaw/windows-browser-node.json`; do not use it with the native setup.
`scratch/openclaw-relay-integration` contains the historical scripts, downloads,
and evidence. These files and `.openclaw/node.cmd`, `.openclaw/node.vbs`, and
`.wslconfig` remain in place. The five browser-node leftovers await manual
recycling because a previous automatic approval review blocked bulk deletion.
The generic WSL preference file remains ambiguous and should be preserved.
Do not retry the blocked operation through another tool.

Follow the exact manual Recycle Bin instructions in the cleanup report. Preserve
`.openclaw/gateway.cmd`, `.openclaw/gateway.vbs`, all credentials, agents,
sessions, workspace, browser profiles, Chrome extensions, and application history.
The old report was backed up before this document was updated. Historical
application batches and their results were not replayed or modified.
