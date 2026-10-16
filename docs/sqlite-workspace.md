# Gecko local database workspace

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
export or two-way synchronization after cutover. New edits belong in the local
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
