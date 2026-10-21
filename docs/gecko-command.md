# Gecko command

## Columns follow names, not positions

Users may move whole columns freely without asking for code or instruction updates.
Read live headers on every sync; use unique header names for fields and stable IDs
for jobs. Never restore a saved order or treat column letters/counts in documentation
as requirements. Automatic idle sync adopts the current order and preserves custom
columns, resume links and Sheet formulas. Moving columns is different from renaming
or deleting a field: missing or ambiguous names must be resolved without guessing.
Keep row 1 frozen. Historical layout tables are reference snapshots only.


## Current tracker columns

Use `docs/current-tracker-columns.md` for the current 36-column Sheet layout and field behavior. Its current-layout rules supersede historical column letters and tracker-authority text in this document. Resolve fields by unique name and jobs by ID, preserve formulas and all jobs/resumes, and always keep row 1 frozen. The qualification field is Qualifies to Apply?; Applied Date is primary and Previous Applied Date is history. Create Resume follows the saved Enough Data value and does not itself trigger generation.


**Frozen header rule:** Always keep row 1 frozen on every Gecko tracker tab and new tracker/export sheet. Preserve any larger existing frozen region. Column edits, reordering, syncing, formatting, and exports must never unfreeze row 1. Verify this after spreadsheet changes.

When the user says **run Gecko**, start the Windows Scheduled Task named
`Gecko` through `scripts/Start-Gecko.ps1`. In a terminal, the command is
`Gecko`. `Gecko --status` shows the task state and pipeline progress.

The on-demand task uses `scripts/run_gecko.py` from this Gecko Main checkout.
It has no clock-based trigger. Do not invent a recurring start time.

The stages are:

1. Run `scripts/daily_report.py --dry-run`, the existing report-writing command
   for Daily Tasks and Daily Run.
2. Run `scripts/gecko_daily.py --apply --sync-local`: discovery and job-list
   updates, local tracker synchronization before the resume queue, tailored
   resumes for approved eligible jobs, response tracking, and run history.
3. Pull the final live tracker again into the local SQLite mirror, full-cell
   JSON, current schema reference, Scratch reference, and Cursor rule.
4. Refresh today's Daily Tasks dashboard with the resulting tracker state.

The latest local references are `docs/live-tracker-schema.md`,
`docs/scratch-column-ideas.md`, and `job-scout/data/tracker-live.json`.
Existing authoritative instructions remain in AGENTS.md and GECKO_SYSTEM.md.
This sync operates inside Gecko Main; it does not change the separate v2 checkout.

Approved `Apply? = Yes` jobs still require the established eligibility checks.
Existing Resume Created = X and existing links prevent regeneration.
No application submissions or resume archiving are part of this command.

The task runs hidden as the logged-in user. Windows ignores duplicate task
starts, and the pipeline also holds a lock. A failed stage stops subsequent
stages and records its exit code. Logs and status are saved in
`reports/gecko-command/`. To add stages later, edit the ordered `STEPS` in
`scripts/run_gecko.py`.

## Run Gecko button — SQLite daily workflow

The dashboard runs scripts/run_gecko.py without a resume-ID limit. The ordered
steps are daily report, full daily discovery and eligible resume queue, local
backup, then final daily report. SQLite remains authoritative. Google Sheets
exports run only when you click **Export to Google Sheets** under **Local workspace**.
Each export creates a new dated tab in the configured workbook,
including custom fields and resume links, without overwriting historical tabs.
The latest manual export link and verification state appear in Activity.

Apply? = Yes resumes use the canonical generator, current master TXT, approved
PDF formatting model, and native Word two-page checks. Existing completion
markers or resume links block regeneration; eligibility, fee, rejection, and
already-applied guards remain active. A failed daily phase still runs the final
backup/report; any failed phase keeps the overall run marked failed.
A failed initial report stops the run before discovery or generation.

## Current tracker authority — October 20, 2026

Dave explicitly requested the existing Gecko Job Tracker Google Sheet become the
primary tracker, with dashboard and Sheet edits synchronized and all jobs/resumes
preserved. This supersedes earlier SQLite-only/export-only restrictions below.
`job-scout/preferences/tracker-backend.json` now declares
`authority: google_sheets`; `backend: sqlite` identifies the local working cache
and attachment/discovery storage, not a separate primary ledger. Keep the existing
spreadsheet ID. Do not replace tabs or upload local resume files.

`job-scout/sheet_sync.py` reconciles individual cells using the last verified
baseline, preserves custom columns and formulas, and verifies Sheet writes before
updating the cache/baseline. Dashboard synchronization runs every 30 seconds while
idle; canonical daily runs synchronize before and after processing. Conflicting
edits and row removals stop sync for review; never choose a winner silently.
Sheet rows representing jobs must retain unique positive IDs. Existing note-only
rows are left untouched. Archived local history remains archived.

Backups and reconciliation evidence: `reports/sheets-primary-cutover/`.
Never delete local jobs, resume files, attachments, drafts or rejection history
as part of synchronization. Preserve existing completion protections.

