# Gecko OpenClaw connection

OpenClaw runs in Ubuntu-24.04 WSL. Gecko uses the
`gecko-resume-application-assistant` agent. Its OpenAI subscription sign-in is
stored by OpenClaw; ordinary OAuth refresh is handled by OpenClaw itself.
Cursor can be used as a terminal, but does not own this connection.

On October 12, 2026, a fresh browser sign-in replaced the failed saved
connection. A live request showed that the signed-in account could not use
`openai/gpt-6-astra`. The account's native model list included
`openai/gpt-5.6-terra`, which completed a real connection test. That model was
saved specifically for the Gecko agent. Other agents retain their settings.
Model access can change; a saved catalog or successful login alone is not proof
that the next inference request will work.

## Check before applying

Double-click `C:\gecko_main\scripts\Check-Gecko-OpenClaw.cmd`, or run this in
PowerShell (including a Cursor terminal):

```powershell
& C:\gecko_main\scripts\Gecko-OpenClaw-Connection.ps1 -Action Check
```

The check sends a short request through the running OpenClaw gateway and the
Gecko agent's configured model. Success prints `Connection verified` and the
model name. It does not submit applications or change the tracker. It uses a
small amount of the account's model allowance.

## Reconnect when sign-in is required

Double-click `C:\gecko_main\scripts\Reconnect-Gecko-OpenClaw.cmd`, or run:

```powershell
& C:\gecko_main\scripts\Gecko-OpenClaw-Connection.ps1 -Action Login
```

Complete the OpenAI browser sign-in using the account you want Gecko to use.
Keep the terminal open. If the callback cannot reach localhost in WSL,
OpenClaw asks you to paste the final redirect URL into that same terminal.
Do not save that URL or an authorization code in files or share it in messages.
The helper tests a real model response after successful sign-in.

Do not repeatedly log out, copy tokens from Cursor/Codex, delete credentials,
or run competing custom refresh jobs. OpenClaw should remain the owner of its
stored refresh token. A revoked or rejected refresh token requires a new human
sign-in. No scheduled task can guarantee uninterrupted authorization.

## Run an approved request with a connection gate

After a bounded application request file has been prepared with explicit job
IDs, resume paths, and submission permission, use:

```powershell
& C:\gecko_main\scripts\Gecko-OpenClaw-Connection.ps1 -Action Run -RequestFile C:\gecko_main\openclaw\application-queue\batch-1262-1268-request.txt
```

This example is the already-authorized October 12 batch: 1262, 1263, 1265,
1266, 1267, and 1268. The helper verifies the connection before dispatching the
request. If that check fails, it does not start the application request.
The request itself must recheck live job eligibility, existing application
state, the exact tailored resume, and confirmation evidence. Do not reuse an
old batch blindly. Do not retry an ambiguous submission until its actual
outcome has been checked.

The helper never silently signs in or changes models on a failed check. A
model-access failure needs a supported model choice; a usage limit needs time
or an allowance change; neither is fixed by repeatedly signing in. A connection
that passes now can still fail later, so preserve per-job evidence and update
Applied only after confirmed submission.

## References

- [OpenClaw OAuth and automatic refresh](https://docs.openclaw.ai/concepts/oauth)
- [OpenAI account sessions and token refresh](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions)
