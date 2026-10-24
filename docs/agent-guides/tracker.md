# Current tracker, discovery, and resume queue

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

The user renamed the qualification column to **Qualifies to Apply?** on October 20.
Its Yes/No values and eligibility behavior are unchanged. `tracker_schema`
maps the internal compatibility key `Apply?` to the physical `Qualifies to Apply?` header;
writers must resolve named headers, never create a second Apply column.

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


Read for tracker, discovery, reporting, queue, approval, or data changes.
The SQLite authority below overrides Google Sheets wording in older references,
GECKO_SYSTEM.md, project.json, and the archived procedures. Read
docs/sqlite-workspace.md for the current database behavior. Read
docs/tracker-schema.md and job-scout/tracker_schema.py for field semantics, not
historical column positions. The dashboard and configured backend are current;
docs/live-tracker-schema.md and tracker-live.json are historical Sheet snapshots.

## SQLite tracker authority — October 16, 2026

The user explicitly requested the local dashboard use SQLite as its primary
tracker. `job-scout/preferences/tracker-backend.json` selects the active backend.
After the verified cutover, `job-scout/data/jobs.sqlite3` owns job tracking,
approvals, notes, application state, resume completion, rejection history, and
run reports. `workspace_jobs` exposes current tracker records; `jobs` and its
related tables retain discovery details. Both are in the same database.

This supersedes the Google-Sheets-authoritative instructions below for normal
dashboard, daily, and resume work. Those sections describe the preserved legacy
workflow. Do not pull or sync Sheets over SQLite, revert the backend, or change
the preserved Google Sheet unless explicitly requested. Keep stable IDs,
existing-X protection, exact native Word QA, truthful master-supported content,
transactional edits, and verified completion. Imported formulas are retained as
protected historical definitions with their evaluated values; SQLite does not
recalculate spreadsheet formulas. Local run summaries and backups replace daily
Sheet report writes. See `docs/sqlite-workspace.md`.

Dashboard custom columns and row edits are authorized. Google Sheets exports are manual only: use the dashboard button under Local
workspace. Never export automatically during Run Gecko; retain its automatic local
SQLite backup step. Google Sheets is an
export-only destination: create a new timestamped export tab, preserve existing
tabs, and verify values by readback. Never import Sheet edits into SQLite.


## Current field and write rules

- October 22 resume-match admission: new discovery and tracker publication require
  a validated score of at least 80 against the current Word master, plus at least
  70% responsibilities and required-skills alignment. Unknown/failed reviews stay
  pending. Existing jobs and manual decisions are preserved. See
  `docs/resume-match-filter.md` for weights, evidence validation and cache behavior.

- October 22 user update: new jobs automatically receive **Enough Data** = Yes
  only after a content review finds pertinent, job-specific information sufficient
  to tailor a resume. Missing, irrelevant, random or generic-only descriptions are
  No. This supersedes older manual-only wording. Use `description_readiness.py`
  and its cached, source-supported review; never treat word count as the decision
  or start resume generation from it. Existing manual decisions remain preserved.
- Extend the existing formulas, validation and formatting for Enough Data and the
  renamed Gecko/FC word-count columns through the last job row. Enough Data is a
  saved automatic content-review value, not a fabricated spreadsheet formula.

- Contract jobs, including short-term contracts, are eligible for consideration
  (Dave's preference, October 22, 2026). Do not exclude a job solely for being a
  contract; retain role, location, fee, rejection, and availability checks.
- Skip new listings whose posted starting annual base salary is above $120,000;
  exactly $120,000 is allowed (October 22, 2026). Do not add excluded jobs to
  the tracker/Sheet. Compare the
  lower end, not the top of the range. Unknown/estimated pay and upper-only
  figures do not establish a starting salary. Do not remove existing jobs.
- Resolve current fields by unique names and jobs by stable ID/source/canonical
  URL (Indeed jk where applicable). A row number alone is not a durable identity.
  Use the existing tracker interface and transactions; verify every write by
  independent readback. Preserve custom columns, notes, imported protected
  formulas, manual values, rejection history, resume links, Applied, and Response.
  Stop on missing/ambiguous fields or any unsafe row movement.
- Last Updated records only an actual, evidence-backed Firecrawl/Gecko run,
  including the tool and America/Denver date/time. Detailed findings belong in
  Notes. A pull, backup, export, or instruction sync must not fabricate dates.
- Apply? = Yes requires Utah or explicit remote work and every eligibility guard.
  Explicit job-specific declarations such as `Location: Remote` or a remote title
  marker are valid fallback evidence when provider fields omit the arrangement.
  Generic remote-team experience or benefits are not evidence; preserve explicit
  on-site/hybrid requirements and do not approve unknown locations.
  A confirmed mandatory fee is Cost = x, forces Apply? = No, and blocks resumes;
  blank/unknown Cost does not. Preserve manual decisions and rejected, expired,
  duplicate, applied, and invalid-URL exclusions.
- Resume Created = X, trimmed and case-insensitive, always blocks generation,
  including blank-link cases. Preserve the marker/link exactly; report a missing
  link for manual review, never regenerate or backfill it. A nonblank Resume Link
  with a blank completion marker also requires review. Rediscovery resets neither.
- For Indeed, retain the exact visible primary application/status control text in
  its named field. If unresolved, preserve the old value. When that field equals
  This job has expired on Indeed or Expired (case/whitespace-insensitive), store
  Expired and set Apply? = No. Expiration overrides eligibility and excludes queues.
- Discovery, intake, queue, and tracker paths consult permanent rejection history.
  Match source-qualified stable ID first, canonical URL otherwise, never company
  and title alone. Reject/Delete / Reject uses job-scout/scout.py reject-jobs.
  Archive and verify the rejection before removing its visible record. Failure
  leaves the record intact; missing/moved rows never imply rejection.
- Daily discovery uses the shared scripts/generate_apply_queue.py implementation
  for all sources, not a duplicate queue. Inspect existing rows for eligibility;
  process only approved, eligible rows with both completion and link blank.
- Read docs/agent-guides/resumes.md and GECKO_SYSTEM.md before creating a resume.
  Only after the exact output/resumes DOCX passes native Word validation may
  scripts/manage_job_tracker.py add --resume <exact-docx> --job-description <listing>
  record completion. It matches the existing job by ID/canonical URL/Indeed jk;
  stop without writes if no unique match. Never bypass it or use an Excel tracker.
  Store the saved file's Path.resolve().as_uri() directly as Resume Link (no
  HYPERLINK formula or generic display text), read it back, and verify its target.
  Failed generation leaves completion blank and records retryable failure in
  Notes, never Cost. No Google Drive upload or automatic application submission.
- Daily response checking uses gmail.readonly only; never modify messages/labels.
  Only the conservatively matched applied job's Response field may be updated by
  that checker; otherwise Response is user-owned. Gmail failure is nonfatal.
- Read docs/scratch-column-ideas.md only when researching those proposed fields.
  They are proposals, not approval to add columns. Historical Sheet formatting,
  protected cells, report exceptions, and synchronization procedures are preserved
  in legacy-sheets.md for explicitly requested legacy work, not routine daily runs.


## Missing job description — user rule (October 19, 2026)

Before automatic resume generation, verify that a usable job description exists
and belongs to the exact job. If the description is missing, empty, incomplete,
or mismatched, skip resume creation and record the job status as **No job description**
in the SQLite workspace/dashboard, with the specific reason in Notes. A company
name, title, search snippet, or another job's description is not sufficient.
Continue processing other eligible jobs. Never invent requirements or create a
generic resume to bypass the missing description. Preserve existing resumes,
Resume Created markers, links, manual decisions, Applied, and protected fields.
Only remove this blocker after a matching usable description has been obtained
and verified; all normal approval and completed-resume guards still apply.


## Completion dates — user instruction October 20, 2026

Whenever a confirmed application is marked Applied, write its actual submission date to **Applied Date** in the same update. Use America/Denver dates (YYYY-MM-DD); when Dave confirms submitting today, use today. Preserve **Previous Applied Date** as history. If the actual date is unknown, ask rather than inventing it.

Whenever a resume is successfully created and verified, write its actual completion date to **Resume Created Date** together with Resume Created and Resume Link. Do not substitute CV Created Date or overwrite historical dates merely during sync. Resolve all columns by unique header name, never position. Verify both the completion marker and date by readback. This supersedes earlier wording treating Resume Created Date as exclusively user-managed.
