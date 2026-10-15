13-10-2026 | 4:28 PM MDT

# OpenClaw native Windows Chrome integration

**Verified working through the persistent Windows browser-node service. Tests A–E pass.** An authenticated request from the existing WSL Gateway listed native Windows Chrome tabs with title **Example Domain** and URL **https://example.com/** after the service started. Previous findings are preserved in `scratch/openclaw-relay-integration/report-before-final-20261013T222819Z.md` and `report-before-continuation-20261013T210048Z.md`.

## Root cause and supported repair

The original WSL `chrome` profile hosted its extension relay in Linux, while Windows lacked the current Foundation extension and a Windows browser host. The automatic native-bootstrap route also lacked `OpenClaw.BrowserBootstrap.exe`.

Bounded official checks found no bootstrap executable in the installed Companion, the digest-verified Companion 2026.9.8-1 portable archive, current Companion source/release metadata, or the integrity-verified OpenClaw 2026.10.3 npm archive. Main release assets did not supply a Windows bootstrap. Reinstalling unchanged Companion software would not solve this.

The supported alternative is an enrolled **Windows browser-only node with advanced manual extension pairing**. Its extension key is generated locally on Windows. Native-host registration and verification are **not applicable to this working route**; the missing executable was not repaired. The Foundation manifest includes nativeMessaging for its optional automatic route.

Sources: [official extension documentation](https://docs.openclaw.ai/tools/chrome-extension), [official Foundation Store page](https://chromewebstore.google.com/detail/openclaw/kcdjddhmeafeomebliikmbpblkmkfoig), [node CLI](https://docs.openclaw.ai/cli/node), and [remote browsers](https://docs.openclaw.ai/tools/browser/remote).

## Components actually installed and configured

- Official isolated Node.js **24.21.0** under `C:\Users\DCALL\AppData\Local\OpenClawBrowserNode\runtime\node-v24.21.0-win-x64`. SHA-256 matched official SHASUMS256.txt: `158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541`. System Node 22 and global PATH were preserved.
- Official Windows OpenClaw CLI **2026.10.3**, under the installation's `cli` directory. npm archive SHA-512 matched official registry integrity metadata. Scoped rebuilds completed required package lifecycle steps; global npm policy was preserved.
- New private Windows state at **`C:\Users\DCALL\.openclaw`**, with user/SYSTEM access. This default Windows state was absent before the task. The initially isolated state was officially backed up/restored and relocated within the same Windows account for canonical service installation. WSL credentials were not copied to Windows.
- Official scheduled task **OpenClaw Node**, installed and started by the CLI. Its generated node.vbs launches node.cmd with window style 0. Task running, native Node process main window handle 0. No second Gateway was started.
- User installed and approved **OpenClaw Foundation 2.3.0**, ID **kcdjddhmeafeomebliikmbpblkmkfoig**, in native Chrome's **Default** profile. Saved disable reasons are empty. User completed advanced manual pairing and Selected tabs mode. Older relay extension preserved.
- Public routing settings `openclaw/windows-browser-node.json` and verified read-only helper `scripts/list_windows_chrome_tabs.py` added.

## Final architecture and exact configuration scope

```text
Existing Ubuntu-24.04 Gateway :18789
  <-> authenticated paired Windows node via localhost/WSL forwarding
Windows OpenClaw Node service (DCALL, Node 24.21.0, CLI 2026.10.3)
  <-> Windows loopback extension relay 127.0.0.1:18899
Foundation extension 2.3.0, advanced manual pairing, Selected tabs
  <-> native Windows Google Chrome, Default profile
```

Node name: **Gecko Main Windows Chrome**. Public node ID: `90e588b69b7814d451cb03604ef693f4ec79632a46e18939e356ded8412d7c3f`. Gateway reports approved, paired, connected, platform Windows, capability exactly browser, command exactly browser.proxy. The proxy allows only windows-chrome; only the browser plugin is allowed. Installed-app sharing and node automatic updates are disabled.

Fields created in the new Windows config:

- gateway.mode=remote; gateway.remote.url=ws://127.0.0.1:18789; gateway.port=18889. No local Gateway launched.
- browser.enabled=true; browser.defaultProfile=windows-chrome; browser.profiles.windows-chrome.driver=extension; browser.profiles.windows-chrome.cdpPort=18899.
- nodeHost.browserProxy.enabled=true; nodeHost.browserProxy.allowProfiles=[windows-chrome]; nodeHost.autoUpdate.enabled=false.
- plugins.allow=[browser]; plugins.entries.browser.enabled=true; logging.level and consoleLevel=silent to protect enrollment output.

Existing WSL default **openclaw**, existing WSL chrome profile/port18799, Gateway binding, Companion settings, credentials, model/provider settings, and automations were preserved. Explicit node routing avoids redirecting Linux workflows. No firewall, public binding, authentication or certificate-verification changes were made. Windows relay listens only on 127.0.0.1:18899.

## Commands executed and relevant results

Windows commands executed directly in PowerShell; Ubuntu commands used `wsl -d Ubuntu-24.04 -e bash -ic`. Exact scripts and non-sensitive evidence are under scratch/openclaw-relay-integration.

| Command/operation | Actual result |
| --- | --- |
| openclaw health --json; systemctl --user is-active openclaw-gateway.service | ok:true, service active, gecko-resume-application-assistant present |
| Official release/archive/npm integrity checks | Automatic bootstrap unavailable; unchanged Companion not reinstalled |
| install-browser-node-runtime.ps1; scoped npm rebuild | Verified isolated runtime and CLI installed |
| Windows config validate --json | New Windows configuration valid |
| devices join-code --json | Rejected non-TLS advertised LAN URL; security settings preserved |
| gateway call device.pair.setupCode with bootstrapProfile=node, includeQr=false | Official one-time enrollment captured privately; never printed |
| Windows node run --pair <private-one-time-value> --host 127.0.0.1 --port 18789 --commands browser.proxy --display-name "Gecko Main Windows Chrome" --no-share-installed-apps | Browser-only Windows node approved and paired; existing Gateway key not copied |
| Windows browser --browser-profile windows-chrome extension pair --json | Windows-local key privately placed on clipboard, consumed by user, matching staged clipboard value cleared |
| backup create --no-include-workspace --verify; backup restore | Archive and restored SQLite inventory verified |
| node install using custom/named state | Canonical-state guards rejected installation; no bypass or executable patch |
| Windows node install --host 127.0.0.1 --port 18789 --commands browser.proxy --display-name "Gecko Main Windows Chrome" --no-share-installed-apps --runtime node --runtime-path <isolated-node.exe> --json; node start --json | Official canonical-state scheduled task installed and running |
| WSL nodes status --json | Exact node approved, paired, connected, browser-only |
| nodes invoke --node <public-id> --command browser.proxy --params <request-json> --json | GET / ready; POST /tabs/open example.com successful; GET /tabs returned title/URL |
| Get-NetTCPConnection and process executable inspection | Loopback relay owned by Windows Node; established extension client is native Windows chrome.exe |
| Companion/WSL configuration SHA-256 readback | Both unchanged against pre-task hashes |

Startup took several minutes. During service handoff an early tab list was empty; that was not accepted as success. After reconnect, a fresh test tab was opened. Final helper readback listed **two eligible example.com test tabs**, both titled Example Domain. Both remain open; no Chrome restart or existing tab closure occurred.

## Tests A–E

| Test | Result |
| --- | --- |
| A — Existing Gateway | **PASS.** Authenticated health ok:true; systemd active; Gecko agent present. Existing Companion and WSL configuration hashes unchanged. Gecko workspace preserved. |
| B — Windows host | **PASS, supported alternative.** Official Windows runtime and browser-only service enrolled/connected. Explicit node/profile verified. Native-host verification **N/A**; automatic bootstrap remains unavailable. |
| C — Extension | **PASS.** Official Foundation ID/version installed in Default profile, no disable reasons. User approved permissions/manual pairing; authenticated connection observed. |
| D — Relay | **PASS.** Actual endpoint http://127.0.0.1:18899; running:true, cdpReady:true, pageReady:true, extension transport, no unresolved pairing error. |
| E — Windows Chrome inspection | **PASS after persistent service startup.** Explicit-node listing returned Example Domain / https://example.com/. Native Windows Chrome executable owns extension connection; status detects C:\Program Files\Google\Chrome\Application\chrome.exe, headless:false, attachOnly:true. Not Linux headless Chromium. |

Evidence: foundation-extension-final.json, windows-browser-status-service.json, example-com-service-tab.json, test-e-service-result.json. Only ordinary test-page metadata retained. No sensitive page/form inspection, file upload, or application submission occurred.

## Backups and preservation

- Earlier reports: preserved paths above, earlier evidence retained.
- WSL config backup: `/home/dcall/.openclaw/backups/windows-browser-relay-20261013/2026-10-13T15-22-08.257-06-00-openclaw-backup.tar.gz`; directory700/archive600.
- Verified private Windows state backup: `C:\Users\DCALL\AppData\Local\OpenClawBrowserNode\backups\2026-10-13T16-05-49.799-06-00-openclaw-backup.tar.gz`. Credential-bearing archive; do not share. Original private state remains under the installation's state directory; config revisions backed up before changes.
- Windows backup verification passed; temporary scratch cleanup reported EPERM. No broad doctor repair/deletion was run to silence this non-blocking warning.
- New task definition: scratch/openclaw-relay-integration/installed-node-task-definition.xml.
- configuration-final-readback.json confirms existing Companion settings.json and WSL openclaw.json unchanged. Existing terminals, schedules, Gecko tracker, resumes, workspace, agent/model settings and Chrome work preserved.

No outstanding approval or software dependency blocks current read-only Windows Chrome control. Automatic native-bootstrap setup still requires an official compatible Windows helper; this working manual route does not.

Computer Use ended when automatic approval review rejected further UI input because the current Windows browser URL could not be reliably determined. No UI bypass was attempted. The user completed Chrome installation and pairing directly; independent terminal work continued.

## Exact future Windows Chrome tab command

Verified from PowerShell through the persistent service:

```powershell
wsl -d Ubuntu-24.04 -e bash -ic 'python3 /mnt/c/gecko_main/scripts/list_windows_chrome_tabs.py'
```

This explicitly selects the enrolled Windows node and windows-chrome profile. It lists eligible tabs; avoid sharing unfiltered output because future tab metadata can be sensitive. In Selected tabs mode, the extension's OpenClaw tab group controls access. The old browser --browser-profile chrome tabs command still targets the unchanged WSL profile.

## Future Gecko application workflow — documented only

1. For an explicitly approved eligible job, read openclaw/application-answers.md, verify stable job identity and approved application URL, then open that URL through this Windows node/profile.
2. Use a fresh snapshot to read actual application fields and confirm job/employer/tab identity.
3. Upload the matching existing tailored resume after verifying identity and successful native Word validation. Resolve supported Windows-node upload/staging at that time; a Linux staging path or Windows file URI alone is insufficient. This node advertises only browser.proxy; any additional upload command needs scoped authorization/configuration then.
4. Populate fields only from verified applicant information and approved answers.
5. Answer screening questions only from approved evidence; never guess required answers.
6. Preserve drafts and identify exact missing required fields/answers.
7. Pause at final review and present the completed application and gaps.
8. Wait for explicit user approval before submission under this documented workflow.
9. Record Applied only after employer confirmation through the canonical tracker workflow, with current live headers and tracker readback. Preserve formulas, manual fields, resume links, and Resume Created markers.

No job application was opened, filled, uploaded, submitted, or marked Applied during this integration.
