# Gecko Main application packages

The Windows exporter reads the live Gecko Job Tracker and creates **one** local
JSON package per explicitly approved stable ID. It never changes Sheets, builds
a resume, opens a browser, or submits an application.

From `C:\gecko_main` in the existing Windows Python environment:

```powershell
python scripts/prepare_application_package.py --job-id <ID> --approved-job-id <ID>
```

For Indeed, supply an actual employer or ATS job URL as well:

```powershell
python scripts/prepare_application_package.py --job-id <ID> --approved-job-id <ID> --company-application-url "https://employer.example/careers/job-specific-path"
```

An explicitly selected physical row can replace `--job-id` with `--row <ROW>`;
`--approved-job-id` must still match that row's live ID. Supply these values
only after the user approves that specific job for application preparation.

The native Windows OpenClaw agent `gecko` reads:

`C:\gecko_main\openclaw\application-queue\<ID>\application-package.json`

The adjacent `audit.json` contains only the job ID, timestamp, result, and
check names. Package directories are ignored by Git. The package's approval
field means **preparation only**; it grants no permission to submit. The agent
must recheck the live listing and application controls before any later step,
because a saved package can become stale. A failed recheck does not refresh an
older package. The exporter confirms a matching employer job page through a
read-only HTTP check; it does not inspect or operate application forms.

## Mandatory application review handoff — October 21, 2026

For EVERY OpenClaw job application, fill supported answers and attach the matching tailored resume, then STOP before the final Submit, Send application, Finish, or equivalent submission action. Leave the exact application tab and draft open so Dave can review every answer and submit it himself. Do not close or refresh away the draft.

Notify Dave for each completed draft: "Ready for your review and submission," identifying the employer, job ID/title, and application link or tab. If anything remains incomplete or unverified, say "Needs your attention" and list the remaining items instead of claiming it is ready. Keep that tab open too; continue other authorized jobs independently.

This standing rule applies to every application, including batches and resumed drafts after answers, login, or CAPTCHA. A request to "apply" does not authorize automatic submission. This replaces older auto-submit instructions. Do not mark Applied merely because a draft is ready; after confirmed submission, record Applied and the actual Applied Date together and verify readback.
