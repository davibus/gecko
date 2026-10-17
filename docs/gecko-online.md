# Gecko Main online dashboard

The Vercel website supports the current job views, notes, approvals, tracker edits,
custom columns, manual applications, full and filtered Gecko runs, activity, manual
Sheets export, and verified resume downloads. It is a private single-user workspace.
The website calls the same local dashboard actions and inherits their SQLite
transactions, stale-edit checks, processing lock, eligibility rules, and existing-X
resume protections. Opening the website or starting its connection never runs Gecko.

The Windows computer must be awake, online, and signed in for Word-based work.
The website and sign-in remain available when it is offline; job views and actions
display an offline error. This release does not move execution or SQLite to the cloud.
Opening Word remotely downloads the DOCX to the device viewing the website instead
of opening a window on the Windows computer. Application submission remains manual.

## Deploy

1. Run `scripts/prepare_gecko_web.py` with the dashboard Python runtime whenever
   local dashboard assets change. This refreshes the committed deployable copies
   in `web/assets` without editing the local originals.
2. Run `scripts/configure_gecko_web.py` with the same runtime. It generates private
   credentials in the Git-ignored `.secrets` directory and preserves existing ones.
   Never commit, paste into chat, or share these files. The sign-in password is in
   `.secrets/gecko-web-signin.txt`.
3. Push the website code to `davibus/gecko`. In the intended Vercel account, import
   that repository, use **web** as Root Directory, and use the **Flask** preset.
   Leave install, build, and output overrides disabled. Import the environment
   variables from `.secrets/gecko-web-vercel.env` before deploying. Upload only
   `web` as the project root; no tracker, resume, Google credential, or local
   environment file belongs in the function bundle.
4. Create/connect **Upstash Redis** using Vercel Storage/Marketplace. Choose a
   suitable plan yourself after reviewing current pricing. Connect it to this
   project's **Production** environment. It must supply
   `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN`; map equivalent integration
   names to these names if needed. Do not paste credentials into chat.
5. Deploy or redeploy after configuring the environment. The gateway uses Vercel's
   `VERCEL_PROJECT_PRODUCTION_URL` by default, allowing only that canonical host.
   For a custom domain set `GECKO_PUBLIC_URL` to its exact HTTPS origin. Preview
   domains deliberately cannot control the production worker. Do not connect
   preview branches to production credentials or the production request store.
6. Pair the actual deployed address:

   ```powershell
   & C:\gecko_main\.tools\dashboard-python\Scripts\python.exe C:\gecko_main\scripts\configure_gecko_web.py --url https://YOUR-ACTUAL-ADDRESS.vercel.app
   ```

   This updates the local worker address and the private environment import file.
   When the address differs from Vercel's production domain, also update
   `GECKO_PUBLIC_URL` in Vercel and redeploy.
7. Run `scripts/Start-Gecko-Online.ps1`. It starts the existing loopback dashboard
   if needed and one hidden outbound connection process. No port-forwarding,
   tunnel, public Python server, new job schedule, or Windows credentials are needed.
8. Sign in at the final address and confirm **Gecko computer connected**. Check
   that jobs and activity load. Verify a harmless notes edit on an explicitly
   chosen job and confirm it in the local dashboard. Start an actual Gecko run
   only when desired using the existing confirmation dialog. Check its run ID
   and activity in both places. Do not claim end-to-end readiness before these
   checks pass.

## Request handling and privacy

The browser authenticates with a generated strong password, a Werkzeug scrypt hash,
and Flask signed sessions. Cookies are Secure, HttpOnly, SameSite Strict, and expire
after 12 hours. Online mutations require an exact configured origin and a session
CSRF token. Login attempts have persistent per-address and global limits.

The Windows worker authenticates separately and makes HTTPS outbound requests.
Both sides restrict actions to explicit dashboard API routes. The worker never
accepts a command line, arbitrary URL, file path, or executable. The local server
continues to validate Host, Origin, and its own ephemeral token. That local token
is removed from snapshots before transmission to the temporary store.

Upstash temporarily holds job responses and command bodies over authenticated TLS.
It is not a second tracker. Queue requests expire after five minutes; commands
not claimed within 45 seconds cannot execute, and completed responses expire after
two minutes. Large responses use individually authorized compressed parts to stay
within hosting and request-store limits. The browser reconstructs the complete
response, including every Notes field, with a 30 MB uncompressed limit. Each part
is at most 480 KB of base64; at most 32 parts are accepted. Oversized responses
return an explicit error rather than incomplete data.

A claim is never requeued. The local request journal commits the request ID before
executing it and caches responses until acknowledged. Disconnections and crashes
may leave an action's outcome unconfirmed. Refresh and inspect activity/job state
before a new attempt; neither browser nor worker automatically repeats an action.
The worker process lock prevents two local worker instances. Existing Gecko run
locks still prevent overlapping workflows, including local starts.

## Stop, check, and rotate

`scripts/Start-Gecko-Online.ps1 -Status` checks the local connection process only.
The website's connected indicator and a successful jobs read prove the actual path.
`scripts/Start-Gecko-Online.ps1 -Stop` stops only the matching connection process;
it leaves the dashboard, current Gecko workflows, tracker, and journal intact.
Closing the website also leaves already-started Gecko workflows running.

No recurring task is installed. Start the connection after sign-in/restart as
needed. Existing local dashboard credentials and pipeline configuration are unchanged.
Revoke access by stopping the worker and rotating `GECKO_BRIDGE_SECRET` in both
Vercel and `.secrets/gecko-web-worker.json`; redeploy. Rotate `GECKO_SESSION_SECRET`
to invalidate all sessions and `GECKO_PASSWORD_HASH` to change the sign-in password.
Preserve the local request journal; never delete it to recover an uncertain action.

## Checks

```powershell
& C:\gecko_main\.tools\dashboard-python\Scripts\python.exe -m unittest discover -s web/tests -v
node --check web/assets/cloud.js
node --check web/assets/app.js
```

The local dashboard runtime also needs Flask (`web/requirements.txt`) for the
shared route allowlist import. Tests use a fake request store and isolated local
servers/databases. They never run discovery, generate resumes, edit the live
tracker, or export to Sheets.
