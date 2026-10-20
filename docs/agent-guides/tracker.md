# Current tracker, discovery, and resume queue

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
  Do not infer remote work from listing prose or approve unknown locations.
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
