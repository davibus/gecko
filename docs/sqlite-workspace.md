# Gecko local database workspace

## Columns follow names, not positions

Users may move whole columns freely without asking for code or instruction updates.
Read live headers on every sync; use unique header names for fields and stable IDs
for jobs. Never restore a saved order or treat column letters/counts in documentation
as requirements. Automatic idle sync adopts the current order and preserves custom
columns, resume links and Sheet formulas. Moving columns is different from renaming
or deleting a field: missing or ambiguous names must be resolved without guessing.
Keep row 1 frozen. Historical layout tables are reference snapshots only.


**Frozen header rule:** Always keep row 1 frozen on every Gecko tracker tab and new tracker/export sheet. Preserve any larger existing frozen region. Column edits, reordering, syncing, formatting, and exports must never unfreeze row 1. Verify this after spreadsheet changes.

## Current column layout — October 20, 2026

See `docs/current-tracker-columns.md` (repository-relative) for the verified 36-column layout and field behavior. This supersedes historical letters and schemas below. Resolve unique live headers by name and jobs by ID; never sort or move only part of a job row. Qualifies to Apply? is the eligibility field (legacy internal alias Apply?). Applied Date is primary; Previous Applied Date is preserved history, wherever those named columns are moved. Cover Letter, CV Created Date, Cover Letter Link, and Cover Letter Created Date remain user-managed. Create Resume is a preserved Sheet formula showing Yes only when Enough Data is Yes; it does not start generation. Enough Data is a saved review, not an automatic AI assessment. Preserve Job Description, Notes, Previous Notes, word-count formulas, all jobs and resumes, and frozen row 1. The removed Cursor Instructions tab must not be recreated automatically.

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


SQLite is the primary tracker after the October 16, 2026 user-authorized cutover.
The database is `job-scout/data/jobs.sqlite3`; the active backend is recorded in
`job-scout/preferences/tracker-backend.json`.

The existing discovery tables retain descriptions, source identities, scoring,
and URL evidence. `workspace_records` stores authoritative job and rejection
state with stable IDs and record versions. The `workspace_jobs` SQL view exposes
job ID, company, title, approval, application status, notes and resume links.
`workspace_events` records changes in the same transaction as each update.
`workspace_runs` stores daily outcomes and summaries. Imported historical tabs
are retained in `workspace_archive`.

The current Google Sheet is preserved as a reference, with no automatic import,
export or two-way synchronization after cutover. Use **Export to Google Sheets**
under **Local workspace** for a manual snapshot. Daily runs keep automatic local backups. New edits belong in the local
dashboard. Formula definitions and their evaluated values were preserved during
migration; SQLite does not recalculate formulas, and imported formula fields
remain protected until explicitly reviewed.

The canonical daily workflow remains reports, discovery, approved resume queue,
read-only Gmail response checking, local database backup, and final local report.
It does not submit applications. Existing completed resumes cannot be regenerated.
All new resumes still require Word-native two-page validation and completion
readback. Discovery and resumes use the same tracker interface; its SQLite
implementation has no Google service and makes no Sheets requests.

Migration evidence and the original database backup are in
`reports/sqlite-migration/20261016T114232Z`. Activation compares the complete
Sheet snapshot again and verifies that the discovery database has not changed
since backup. Automatic workspace backups use SQLite's consistent backup API
and pass `PRAGMA integrity_check`; they are stored in `reports/sqlite-backups`.
Do not replace the active database with an old snapshot after new edits.
Rollback requires reconciling post-cutover changes first.

Firecrawl public-page retrieval uses `FIRECRAWL_API_KEY` in `.env.local`. It uses
basic retrieval, caches URLs within a run, and stops repeated authentication,
billing or rate failures. Search snippets are never accepted as complete jobs.
LinkedIn access failures and pages lacking usable public job data remain visible.
The Muse uses `THE_MUSE_API_KEY`. Credentials never belong in the browser or logs.

## Editable tracker and exports

The dashboard is the primary editing workspace. Its Editable tracker tab supports
custom text columns, custom-column renaming, all-column search, and row saves.
Protected identity/completion fields cannot be changed as ordinary cells. Use job
actions for notes, approval, application recording, and follow-ups. Changes to
eligibility revoke an existing approval when necessary. Formula definitions remain
protected; new custom cells are literal text, not spreadsheet formulas.

Google Sheets is export-only. The dashboard creates a fresh timestamped tab for
each export, sends RAW values, and independently compares returned values. It
never imports edits or overwrites the historical tabs. Every custom column is
included. An unverified export is visibly reported as incomplete.
