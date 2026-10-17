# Retired OpenClaw setup cleanup

Verified 16-10-2026 | 9:45 AM MDT. Scope is the six requested paths, native OpenClaw configuration,
connection helper/wrappers, and related documentation. This is not a whole-PC audit.

## Outcome

No candidate files or folders were removed. The user reported a previous automatic
approval-review rejection of bulk deletion. That restriction was respected: no
Recycle Bin API, shell deletion, alternate tool, or split deletion was attempted.
The five confirmed obsolete items below require manual Recycle Bin action.
`.wslconfig` remains ambiguous and is not included in those removal instructions.
The Recycle Bin was not emptied.

## Verified running setup

- Native OpenClaw 2026.10.4 at `C:\Users\DCALL\AppData\Roaming\npm\openclaw.cmd`.
- State `C:\Users\DCALL\.openclaw`; existing/default agent `gecko`.
- Existing `OpenClaw Gateway` task Running, using `.openclaw\gateway.vbs`.
- Native Node Gateway listener `127.0.0.1:18889`, PID 17044; supervisor PID 3040.
  The same Gateway processes remained in place; no restart was requested.
- Authenticated health and edited configuration validation both passed through
  the updated Windows helper. Initial 10-second health calls timed out; a
  60-second health allowance passed. No inference turn or sign-in was initiated.
- Existing account/provider profile configuration was preserved; selected model
  remains `openai/gpt-6-astra`. Seven credential/account table fingerprints
  match the before snapshot. This is not a fresh provider inference test.
- Gecko task Ready; latest saved run already complete. No daily/discovery/resume
  or application workflow was started, interrupted, or replayed.
- Project Python is `C:\gecko_main\.tools\dashboard-python\Scripts\python.exe`.

## WSL verification without launching it

Win32_OptionalFeature reports InstallState 2 (Disabled) for both
Microsoft-Windows-Subsystem-Linux and VirtualMachinePlatform. No installed
Ubuntu/WSL Appx package, registered HKCU Lxss distribution, WSL service, or
Linux VM/Ubuntu process was found. The retired isolated
`C:\Users\DCALL\AppData\Local\OpenClawBrowserNode` runtime is absent.
The native Gateway reports no paired browser nodes. No WSL command was invoked
and nothing was installed or started. `C:\Windows\System32\wsl.exe` remains
present and untouched (274432 bytes).

The DISM cmdlet initially required elevation; the read-only WMI optional-feature
inventory supplied the state instead. No elevation or feature change was attempted.

## Individual candidate decisions

Every path resolves to exactly the requested absolute location. Windows reparse
attributes were checked on each item and its ancestors, plus all 58 descendants
of the scratch candidate: no junction, symlink, or other reparse point was found.

| Exact path | Finding and disposition |
| --- | --- |
| `C:\Users\DCALL\.wslconfig` | Generic WSL2 memory/CPU/swap/forwarding preferences. WSL is disabled, but the file contains no exclusive OpenClaw ownership marker. Ambiguous provenance; leave untouched. |
| `C:\Users\DCALL\.openclaw\node.cmd` | Retired browser-only node launcher pointing to the absent isolated runtime and old port 18789. Distinct from system Node.js and `gateway.cmd`. Confirmed obsolete; manual recycle pending. |
| `C:\Users\DCALL\.openclaw\node.vbs` | Launches only the retired `node.cmd`. No OpenClaw Node task exists. Confirmed obsolete; manual recycle pending. |
| `C:\gecko_main\scratch\openclaw-relay-integration` | 58 retired integration scripts, downloads, and test/evidence files. No active runtime/workflow dependency found. Confirmed obsolete integration scratch; manual recycle pending. |
| `C:\gecko_main\openclaw\windows-browser-node.json` | Old public routing descriptor for retired node ID, consumed only by the old tab helper and historical integration references. Current browser configuration is separately preserved in openclaw.json. Confirmed obsolete; manual recycle pending. |
| `C:\gecko_main\scripts\list_windows_chrome_tabs.py` | Uses `/home/dcall/.openclaw/bin/openclaw` and the old node descriptor. Current Windows helper and workflows do not consume it. Confirmed obsolete; manual recycle pending. |

Reference inspection covered the current project scripts/docs/configuration,
OpenClaw text configuration, 202 Scheduled Tasks, 293 services, eight startup
commands, and relevant running processes. No active task, service, startup
command, or executing browser-node workflow referenced these candidates.
Historical references and dependencies between the retired files themselves
were distinguished from active workflow consumers. Historical application
scripts/results were left untouched.

## Changes and preservation

Removed only `gateway.remote` (old URL `ws://127.0.0.1:18789`) from openclaw.json.
An exact parsed comparison confirms all other settings are unchanged. Native
configuration validation passed; rollback was available but not needed.
The installed reload policy classifies gateway.remote as requiring no restart.

Configuration backup: `C:\Users\DCALL\.openclaw\openclaw.json.before-native-cleanup-20261016T153812Z.bak`.
Earlier helper, wrappers, and documentation copies plus audit evidence are in
`C:\gecko_main\scratch\openclaw-native-cleanup-20261016T083549`. This audit folder is restricted to the current user and SYSTEM
because the configuration backup includes authentication material. Do not share it.

Updated `scripts/Gecko-OpenClaw-Connection.ps1`, its Check/Reconnect wrappers,
`docs/openclaw-connection.md`, `docs/openclaw-browser-relay-setup.md`, and the
application-package README. The helper uses native CLI/Windows request paths
and default agent gecko. It has no Linux/WSL invocation or retired profile ID.
Default Check validates configuration and Gateway health. Optional ProbeModel
and explicit Login/Run behaviors remain available; no old request is embedded.
Syntax, wrong-Gateway rejection, missing-request rejection, and the real native
Check passed. Interactive Login and application dispatch were intentionally not run.

Preserved native Node.js, Python, Git, Chrome, both saved OpenClaw extension
registrations, browser configuration/profiles, Gateway task/launchers,
credentials, agents, sessions, workspace, application answers/history, resumes,
SQLite tracker/backend, Google credentials, and existing Gecko source changes.
Eleven of fourteen selected protected-file hashes stayed unchanged, including
Gateway launchers, account storage files, tracker DB/backend, application
answers, AGENTS.md, and dashboard index.html. Three source files outside this
task's write set changed between snapshots: dashboard/static/app.js,
dashboard/static/filters.js, and dashboard/static/style.css. This task did not
write or revert those files; their newer contents remain intact. Account-table
fingerprints still match. This was not an exhaustive byte audit of every
protected file.
The node-proxy allowlist and disabled node auto-update setting were retained:
the installed browser plugin consults them, and removing the allowlist could
broaden profile access. No authentication or browser pairing was changed.

## Browser connectivity is separate

The native browser status command succeeded against windows-chrome but reported
`running=false`, `cdpReady=false`, `pageReady=false`, extension transport, port
18899, and detected native Chrome. A loopback relay listener alone does not
prove a connected extension. No known ordinary page title/URL was read through
OpenClaw, and no form/autofill test was performed. Browser connectivity and
autofill are therefore unverified. Saved Chrome registrations still include
OpenClaw Foundation 2.3.0 and OpenClaw Browser Relay 2026.2.26.
If browser automation is desired, reconnect/pair the extension with the current
native profile, then verify an ordinary page and a safe form before relying on
browser actions. No sign-in or pairing was initiated during this cleanup.

## Exact manual Recycle Bin steps

In File Explorer, show hidden items and filename extensions. For each row below,
paste the parent path into the address bar, select only the exact named item,
and press Delete (or right-click Delete). Do not use Shift+Delete. If Windows
offers permanent deletion instead of moving to the Recycle Bin, cancel.

| Parent to open | Exact item to select |
| --- | --- |
| `C:\Users\DCALL\.openclaw` | `node.cmd` |
| `C:\Users\DCALL\.openclaw` | `node.vbs` |
| `C:\gecko_main\scratch` | `openclaw-relay-integration` |
| `C:\gecko_main\openclaw` | `windows-browser-node.json` |
| `C:\gecko_main\scripts` | `list_windows_chrome_tabs.py` |

Preserve the parent directories, gateway.cmd, gateway.vbs, and .wslconfig.
Afterward, verify each selected item is absent from its original location and
present in the Recycle Bin; do not empty it. All six candidates were still
present at the end of this automated work, so removal/absence verification
remains pending your manual action. If another run or configuration change
occurs before removal, recheck references first.


## Permitted continuation - 16-10-2026 | 9:59 AM MDT

The native helper's real Check passed again: configuration valid, authenticated
Gateway health successful, and agent gecko present. Syntax validation and the
search for retired invocations/service-start commands passed. Gateway transport
errors now receive their own explanation instead of a provider sign-in suggestion.
The helper and its documentation were updated; configuration, pairing, services,
and Windows features were not edited during this continuation.

The existing Gateway supervisor PID 3040 and child PID 17044 remain running,
with loopback listeners 18889/18899. Gecko is Ready and no daily pipeline was
started. Feature state was only read: WSL and Virtual Machine Platform were
already disabled. No optional feature was disabled, enabled, installed, or started.

Paths containing spaces were passed as individual quoted PowerShell strings or
subprocess argument-list elements. Optional locations were tested for existence
before searching. Exact search outcomes:

- MATCHES_FOUND: scripts (retired tab helper only), docs (historical cleanup
  references only).
- NO_MATCHES, rg exit 1 with empty stderr: openclaw, .cursor, .vscode, current-user
  Startup, and all-users Startup.
- SKIPPED_ABSENT_OPTIONAL_PATH: C:\Users\DCALL\AppData\Local\OpenClawBrowserNode.
  This absent retired runtime is not a native installation failure.
- SEARCH_ERROR: none. rg exit codes other than 0/1 are treated as errors.
- Zero candidate references in 202 tasks, 293 services, and eight startup commands.

All six candidate paths remain present and resolve exactly as requested. No
reparse point was found on the paths, ancestors, or 58 scratch descendants.
Six selected protected-file hashes and six logical account-table fingerprints
match the continuation baseline. No candidate was removed; the same exact
manual Recycle Bin instructions above still apply. Preserve generic .wslconfig.

The fresh native browser status command succeeded but still reports
windows-chrome running=false, cdpReady=false, pageReady=false, extension transport,
port 18899, and detected C:\Program Files\Google\Chrome\Application\chrome.exe.
No browser pairing/configuration was changed and no browser autofill success is
claimed. No provider sign-in, application request, or discovery was initiated.

Detailed continuation search, candidate, browser, and preservation evidence is
in the private audit directory already listed above.
