# Gecko local workspace

## Current selected-job test

Run Gecko is pinned server-side to IDs 2555 through 2568 by
`job-scout/preferences/dashboard-run.json`. The dialog shows the exact IDs before
starting. The selected pipeline validates IDs and required resume authorities,
refreshes reports, uses the canonical targeted resume queue without automatic
approval, checks employer responses only for selected applied jobs, backs up
SQLite, refreshes results, and exports the full current tracker to a new Sheets
tab. Broad discovery and rejection cleanup are excluded from this bounded test.
The `GECKO_ALLOWED_JOB_IDS` guard is inherited by subprocesses and rejects tracker
writes outside the selected IDs. Existing completion, application, eligibility,
and native Word QA protections remain in force. This setup does not start a run.

Open **Gecko Dashboard** from the desktop, or run `scripts/Start-Gecko-Dashboard.ps1`.
The launcher starts one hidden loopback-only server and opens http://127.0.0.1:8765.
It does not run discovery or generate resumes just by opening the dashboard.

## Daily workflow

1. Refresh the local SQLite tracker and review Today.
2. Open a job to review its posting, archived description, saved assessment, and notes.
3. Approve or decline the job. Decline sets Apply? to No, retains the row, and does not permanently reject/delete it.
4. Prepare a resume for one approved eligible job. This invokes the canonical targeted queue with the exact tracker ID, preserves existing resumes, and uses existing Word-native validation and tracker readback.
5. Open the linked resume in Word and the employer's application page. Submit the application yourself.
6. Select “I applied to this job”, set a follow-up date, and save notes. Update the application stage as conversations progress.
7. Use Activity to monitor operations. “Run Gecko” runs the full existing daily pipeline, including discovery and all eligible approved resumes. The review dialog explains these effects before starting.

## Data and protection

SQLite is authoritative. Use **Editable tracker** to add custom text columns,
rename custom columns, search all fields, and edit values with verified row saves.
Custom fields survive discovery and resume runs. Existing imported formula fields
remain protected historical values; this release does not calculate formulas.
Identity and completion fields are protected. Notes, approval, application status,
and follow-ups use the job workspace actions. Edits that make an approved job
ineligible also revoke approval in the same transaction.

**Export to Google Sheets** creates a new timestamped tab in the configured
workbook, writes literal values (including custom columns), and verifies readback.
Existing tabs are preserved. Sheet edits never flow back into SQLite. An export is
a snapshot, not a live mirror. Failed or unverified exports are reported explicitly.

Row saves compare the original row inside a SQLite transaction. Stale edits and
formula edits fail without partial changes; successful saves are audited and read
back. All mutations retain the shared processing lock and local API protections.

Only exact source/ID/URL matches may display local discovery descriptions and saved scoring. Cached scoring is labeled with its evaluation date. Existing file availability is not a new assertion that historical Word QA passed.

Resume serving and opening are restricted to non-empty DOCX files directly in output/resumes whose links are read from the live job. The HTTP server binds only to 127.0.0.1, validates Host/Origin, blocks cross-site requests, and requires an ephemeral token on mutation requests. There is no arbitrary command or filesystem endpoint. Do not expose this service through a tunnel or public interface.

Google token timestamps use an HTTPS Date sample from Google's OAuth endpoint when launched through this dashboard. This avoids the observed Windows clock drift without changing the OS clock. The optional GECKO_GOOGLE_AUTH_SERVER_CLOCK flag is inherited by dashboard-started workflows; ordinary existing commands are unchanged. Business dates continue to use America/Denver on the computer.

## Run state and logs

The canonical processing lock prevents overlapping pipeline/resume jobs and dashboard edits. Dashboard operations and edit audits live under ignored scratch/dashboard. The full pipeline also writes reports/gecko-command. A server restart marks prior dashboard operations as unknown rather than falsely complete; the processing lock remains the source for whether work is active. The Windows scheduled Gecko task is not required by this dashboard: the Run button calls the canonical scripts/run_gecko.py pipeline directly.

## Setup and checks

Use a working Python 3.11+ interpreter to create `.tools/dashboard-python`, then install `dashboard/requirements.txt` in that environment. Existing Gecko .env files supply optional Sheets export configuration; never copy credentials into frontend files. The server needs Windows for the shared process lock and local document opening.

Run tests from the project root:

```powershell
& .tools/dashboard-python/Scripts/python.exe -m unittest discover -s dashboard/tests -v
node --check dashboard/static/app.js
```

The dashboard intentionally leaves submission, messages, destructive rejection cleanup, and historical-data backfills outside its per-job actions. Broader operations retain the existing canonical Gecko rules.

## First-release verification — October 16, 2026

- 23 dashboard tests passed, including exact-ID resume dispatch, subprocess failures, missing-result detection, stale edits, header reordering, formula/spill protection, API origin/token checks, and application/follow-up history.
- Live Google Sheets loaded 1,016 jobs, all with unambiguous numeric IDs. 432 linked local resume files were available. These counts are a snapshot, not constants.
- A live same-value Notes write on job 2240 passed independent readback; the entire target job remained unchanged.
- Canonical read-only queue classification for job 1261 selected exactly ID 1261, with no generation or tracker changes.
- Browser checks verified live totals, navigation, search, descriptions, notes, existing-resume actions, and no regeneration control for a completed resume.
- The original 65-test resume queue baseline had 20 failures and 7 errors, reproduced without the auth-clock change. These were repaired on October 16: fixtures now use current headers, valid URLs separate from descriptions, sufficient description content, exact recovery identity, and the current approval/application protections. All 68 tests pass, including three added regressions for invalid URLs, insufficient descriptions, and an application recorded during generation. Baseline and final logs are in scratch/dashboard/baseline-queue-tests.log and scratch/dashboard/queue-repair-final.log.
- No new real resume was generated, no application was submitted or marked applied, and the full daily pipeline was not run for this UI build. Those actions are available through the dashboard but are not claimed as live end-to-end verified in this release.

## Live workflow follow-up — October 16, 2026

- 138 focused checks passed: resume queue (68), resume generation/native validation contract (23), candidate profile (12), AI pipeline (10), dashboard (23), and daily launcher (2).
- The full daily run was started from the dashboard. Its first report passed. Discovery parsed 21,427 listings, added 28 jobs to Sheets, and retired two verified-expired postings while retaining their manual fields. Eight providers reported partial failures; The Muse also lacked credentials.
- The daily workflow stopped before its resume phase because the compact candidate profile no longer matched the current master. The selected profile was backed up, reviewed against the complete current master, updated, and validated. The failed run record is retained; this is not a clean full-pipeline pass.
- A real dashboard resume action for Rula, ID 2554, exposed Windows resolving the PDF validator's Python command to an unusable default runtime. Native QA now supplies the current interpreter directory on the child PATH. The retry succeeded: Word and exported PDF both have exactly two pages, all QA checks passed, and Sheets completion/link readback passed. The dashboard shows Resume ready. No application was submitted or marked applied.
- Local tracker/Cursor synchronization passed with a verified snapshot. Verification evidence is under scratch/dashboard/workflow-verification; native QA is under scratch/Rula+6e3f93c0-d1ad-4129-ab76-6362d7e14d69.
- The remaining steps were exercised separately after the failed full run: Gmail checked 343 messages and matched 19, with 11 distinct Response rows changed by independent comparison. (Its existing summary reports 22 managed writes, including timestamps.) Daily Tasks refreshed successfully with readback; Daily Run retains the original failure. All 432 prior completed resumes, all Applied values, formulas, and prior unkeyed records were preserved. Bulk resume processing for the remaining queue was not rerun; full-pipeline verification remains partial.

## Table heading filters
Opportunity, Location / salary, Progress, and Next action have funnel buttons. Filters combine with source, stage, and search controls and apply before pagination. Progress supports excluded stages and hiding every applied job. Salary uses overlapping annual USD ranges; unknown, hourly, and other-currency values have an explicit inclusion choice. Filters change the view only and reset on page reload. Highlighted icons and filter chips identify active filters; Clear column filters restores the view without changing job data.


## Run Gecko button — SQLite daily workflow

The dashboard runs scripts/run_gecko.py without a resume-ID limit. The ordered
steps are daily report, full daily discovery and eligible resume queue, local
backup, final daily report, then a verified Google Sheets export. SQLite remains
authoritative. Each export creates a new dated tab in the configured workbook,
including custom fields and resume links, without overwriting historical tabs.
The latest automatic export link and verification state appear in Activity.

Apply? = Yes resumes use the canonical generator, current master TXT, approved
PDF formatting model, and native Word two-page checks. Existing completion
markers or resume links block regeneration; eligibility, fee, rejection, and
already-applied guards remain active. A failed daily phase still runs the final
backup/report/export; any failed phase keeps the overall run marked failed.
A failed initial report stops the run before discovery or generation.
