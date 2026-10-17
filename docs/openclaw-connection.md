# Gecko OpenClaw connection

The verified setup uses native Windows OpenClaw 2026.10.4. State is
`C:\Users\DCALL\.openclaw`; the agent is `gecko`. The installed CLI is
`C:\Users\DCALL\AppData\Roaming\npm\openclaw.cmd`. The existing
`OpenClaw Gateway` Scheduled Task launches `gateway.vbs` / `gateway.cmd` and
listens only on `127.0.0.1:18889`. The project is `C:\gecko_main` and its Python
is `C:\gecko_main\.tools\dashboard-python\Scripts\python.exe`.

The helper uses Windows paths directly. It does not install or start a runtime,
start Gecko, restart the Gateway, or silently initiate sign-in. It refuses
configuration/environment overrides that select a different Gateway or state.

## Check the existing connection

Double-click `C:\gecko_main\scripts\Check-Gecko-OpenClaw.cmd`, or run:

```powershell
& C:\gecko_main\scripts\Gecko-OpenClaw-Connection.ps1 -Action Check
```

The default check validates the configuration and authenticated Gateway health,
including the presence of agent `gecko`. It does not run an agent turn. A healthy
Gateway does not prove provider inference, browser access, or autofill.
The health request allows 60 seconds for a slow response. A Gateway transport
failure is reported separately from provider authentication; it does not
initiate sign-in or restart the service.

For an optional isolated model response check:

```powershell
& C:\gecko_main\scripts\Gecko-OpenClaw-Connection.ps1 -Action Check -ProbeModel
```

This sends a new connection-only session asking for `GECKO_CONNECTION_OK` with
no tools or application work. It uses model allowance. It never resumes an old
batch or changes the configured model. A successful check is point-in-time
inference evidence, not application/browser verification.

## Explicit interactive sign-in

Only when a human intends to sign in, use `Reconnect-Gecko-OpenClaw.cmd`, or:

```powershell
& C:\gecko_main\scripts\Gecko-OpenClaw-Connection.ps1 -Action Login
```

The native CLI handles sign-in for `gecko`; no retired profile ID is forced.
An explicit `-ProfileId` is available if a particular current profile is needed.
Complete the provider's browser prompts yourself. Do not save or share callback
URLs, codes, or tokens. Successful sign-in is followed by an isolated model
check. Normal OAuth refresh remains OpenClaw's responsibility. Do not delete
credentials, copy tokens, force profile replacement, or create custom refresh jobs.

## Dispatch a newly authorized request

After the user explicitly authorizes the current job IDs and submission scope,
provide a newly reviewed UTF-8 request file using an absolute Windows path:

```powershell
& C:\gecko_main\scripts\Gecko-OpenClaw-Connection.ps1 -Action Run -RequestFile 'C:\gecko_main\openclaw\application-queue\CURRENT-APPROVED-REQUEST.txt'
```

The filename above is a placeholder. Historical batches are retained evidence
and must never be replayed as a connection test. Run validates the nonempty
request file, checks Gateway health and an isolated model response, then forwards
the exact local file with `--message-file` to a new `gecko` session. Failure at
the connection gate prevents dispatch. A failed dispatched request can still
have submitted individual applications; verify confirmation evidence before retrying.

Application work must follow `openclaw/application-answers.md` and the current
AGENTS.md rules. SQLite is the tracker authority. Preserve exact job identity,
existing submissions, tailored resumes, and native Word validation. Update
Applied only after employer confirmation and tracker readback. Missing required
answers stay pending; they must not be guessed.

Model-access and usage-limit failures are separate from sign-in failures. The
helper never changes models or automatically retries sign-in. Browser readiness
is documented separately in `docs/openclaw-browser-relay-setup.md`.
