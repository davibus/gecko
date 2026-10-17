# Preserved Google Sheets procedures — historical / explicitly requested use only

Do not load this guide for routine SQLite tasks. These are the full procedures
moved from the former root AGENTS.md, retained so no user preference or legacy
procedure is lost. Statements below that call Sheets canonical are superseded
by the SQLite cutover. They do not authorize switching backends, importing,
two-way synchronization, or automatic exports. For routine work use tracker.md.
Only apply these Sheet-specific mechanics when the user explicitly requests work
on the preserved Sheet; verify the live destination, headers, and protections.

## Job List validation

### Last run and Notes columns (verified 2026-10-14)

The live `Job List` column R is named `Last Updated`; it records the last
actual Firecrawl or Gecko run for that job. Column I is `Notes` and holds
posting details, research findings, review reasons, and manual comments.
Resolve both by their unique live headers, never by a hard-coded letter.
Record the actual run date/time in America/Denver and identify Firecrawl or
Gecko. A local tracker pull or instruction sync does not represent a job run
and must not fabricate or reset Last Updated. Preserve notes and formulas.
Only recover a historical date when existing evidence explicitly states it;
never assign today's date to old research. Current live columns are:
J Indeed application text, K Response, L Location, M Work Arrangement,
N Employment Type, O Salary, P Job URL, Q Resume Link, R Last Updated,
S Date Posted, T Date Found, U Last Seen. Current live headers remain authoritative.

Read `docs/scratch-column-ideas.md` for the user's Scratch-tab notes.
These are proposed research fields, not approved new spreadsheet columns.
Preserve the Scratch tab and sync its text into that reference file when asked.

For live URL, application-status, cost, eligibility, highlighting, and existing
resume-link maintenance, use `python scripts/validate_job_list.py --apply`.
The command resolves current `Job List` columns by unique header name
before writing, including inserted columns. It never generates resumes or submits applications. It records
original URLs and links in `reports/job-list-validation/` before changing them,
preserves formula cells, and marks inaccessible sites for review. Its red A:E
highlight is a dedicated conditional-format rule; existing rules remain in place.
Google Sheets `HYPERLINK` does not support `file:///` targets, so existing
local resume files use rich-text links when the Sheets API accepts them.
If Google rejects a local-file link, preserve the original URI and report it.
Do not backfill a blank Resume Link on a `Resume Created = X` row.

The Gecko Job Tracker spreadsheet has been rearranged. The current `Job List` header row is authoritative: column E is `Apply?`, column H is `Cost`, and there is no `Status` column. Resolve fields by unique header name, never by a historical position. A resume requires `Apply? = Yes` plus Utah or explicit remote eligibility. Write `Cost = x` only for a confirmed required application fee; unknown Cost stays blank and does not block approval. `Cost = x` forces `Apply? = No` and excludes resume generation. Unknown location does not approve a job. Every existing and newly inserted workbook row is 21 pixels high.
Read `docs/tracker-schema.md` for the verified workbook tabs, current header names, alias mapping, status rules, and protected fields before tracker work. `job-scout/tracker_schema.py` is the central runtime schema. Re-read live tabs and headers before tracker operations; stop on missing or ambiguous fields. `scripts/daily_report.py` writes the five-date vertical dashboard in `Daily Tasks` and inserts `Daily Run` history at row 3, preserving older blocks. See `docs/daily-report.md`. `Scratch` contains the user's research-field ideas, mirrored in `docs/scratch-column-ideas.md`, and has no job-data writer. `Daily Reports` and `List of Job Sources` are absent; `Deleted Jobs` is empty and has no inferred writer. Do not create or rename tabs implicitly.

`python scripts/daily_report.py --dry-run` is the authorized reporting exception: it reads job data, writes the owned A:F vertical dashboard blocks in the existing `Daily Tasks` tab, inserts a history block in `Daily Run`, and writes local audit files. A missing report tab is a blocker; the command never creates one. `Daily Tasks` keeps the five newest distinct America/Denver dates in descending order, one variable-height report per date. A same-date rerun replaces that date's block, including a historical `--date` rerun at its sorted position. `Daily Run` inserts at row 3 without overwriting older history. Never change unrelated tabs, unrelated `Daily Tasks` cells, or job data. The command never launches job discovery, Indeed page checks, Gmail tracking, resume generation, or live tracker sync. Run-level discovery and projections that require those operations retain `Unavailable` internally; only the specified `Daily Run` display metrics show numeric zero. Re-read protected tabs and unrelated task cells after the report write and fail if they changed. See `docs/daily-report.md`.

All Google Sheets writers must update only explicitly managed cells by their current, unambiguous headers. Preserve custom columns, existing formulas, and ARRAYFORMULA anchors and output ranges. Before each managed-cell write, read its formula state; skip and report formula-protected updates. Never replace whole rows or clear ranges that contain unmanaged cells. Sorting, cleanup, deletion, or row movement must stop with a clear explanation when formulas cannot be guaranteed to remain attached to the correct jobs. Keep rejection history, raw resume file-URI links, and the existing Resume Created = X guard intact.

For Source = Indeed, the 'Apply or on Company Website (If Indeed)' field stores the exact visible text of the primary application/status control on the Indeed job page. Examples include 'Apply Now', 'Apply on Company Website', 'Already applied', and 'Job no longer available'. Do not normalize the text. If it cannot be reliably resolved, leave the current value unchanged and continue.

Exception for expired Indeed jobs: when the named application/status field equals `This job has expired on Indeed` or `Expired`, ignoring case and surrounding whitespace, write `Expired` for the full message and set the named `Apply?` or `Apply` field to `No`. Expiration overrides Utah and remote approval and excludes the row from resume queues. Update only affected non-formula cells, report skipped formula cells, and verify writes by readback. Preserve `Resume Created = X`, resume links, and files.

# AntiGravity Project Instructions — Gecko

You are working inside the Gecko resume-customization project.

Always read `GECKO_SYSTEM.md` before performing resume work.
## Job tracker

Google Sheets is the canonical job tracker. Do not create or update a local Excel job tracker. Every successfully completed Gecko resume must be recorded through the tracker command as the final workflow step. Run:

`python scripts/manage_job_tracker.py add --resume "output/resumes/<resume-file>.docx" --job-description "input/job-descriptions/<archived-listing-file>.md"`

The current workbook has `Job List` as its job ledger and no `Job Tracker` tab. The tracker script matches an existing `Job List` row by `ID`, canonical `Job URL`, or Indeed `jk` before recording a completed resume. If no unique row exists, stop without a write. If a legacy application tab exists in another configured workbook, its separate Job Number and Resume #/Index logic applies only there. Do not directly rewrite existing tracker rows or clear user-maintained fields such as `Applied` and `Response`.

Daily Job Scout also runs the reusable read-only Gmail response checker after the resume queue. It may update only the `Response` cell for a conservatively matched applied job. OAuth must use only `gmail.readonly`; Gmail messages and labels must never be modified. Gmail failures are nonfatal to discovery and resume creation.

Never bypass `scripts/manage_job_tracker.py`, because it also marks the matching Scout row `Resume Created`. If Google Sheets is unavailable, report the error; do not create a local tracker or silently fall back.

### Permanent job rejection

`Rejected Jobs` is Gecko's hidden, durable rejection-history tab. Job Scout, manual Indeed intake, Indeed-only resume runs, tracker upserts, and the shared resume queue must consult it in addition to ordinary duplicate detection. Match a permanent rejection by source-qualified stable Job ID first (use Indeed `jk` whenever available), then by normalized canonical job URL when no stable ID is available. Never permanently reject by Company + Job Title alone; a similar role or repost may be a legitimate new opening.

To permanently remove a job, set its `Apply?` cell to `Reject` (also accepted: `Delete / Reject`) and run:

`python job-scout/scout.py reject-jobs`

Daily and Sheet-sync operations also process marked rows. Gecko must write and read back the complete rejection record before deleting the visible `Job List` row. If the support write or verification fails, leave the visible row intact. Never infer rejection from an ordinary missing, moved, or manually deleted row.

### Daily all-source resume queue

`python job-scout/scout.py daily` is the complete discovery-to-resume workflow. After discovery and Sheet synchronization, it must invoke the canonical `scripts/generate_apply_queue.py` implementation automatically for all sources; do not create a duplicate queue workflow or require a second manual command.

On every non-dry daily run, inspect all existing `Job List` rows. Set `Apply?` to `Yes` when `Location`/`Work Arrangement` proves Utah or explicit remote work and all other eligibility safeguards pass. A blank Cost does not block approval; a confirmed required application fee is `Cost = x` and forces `Apply? = No`. Do not infer remote work from listing prose. Preserve explicit manual decisions and rejected, expired, duplicate, applied, and invalid-URL exclusions.

Resolve queue fields by their exact, unambiguous headers on the configured intake worksheet before reading or writing; never assume the application-history worksheet is the queue. Before creating or queuing a resume for any job from any scout, read the existing tracker row by stable identity. If `Resume Created` is `X` after trimming and case normalization, skip generation, preserve the marker and existing link exactly, even when the link is blank, and report a missing link for manual review. A nonblank `Resume Link` with a blank marker also stops generation for manual review. Rediscovery must not reset either state. If `Cost` is `x` after trimming and case normalization, skip creation. Process qualifying `Apply? = yes` rows only when both `Resume Created` and `Resume Link` are blank.

Only after the exact DOCX exists under `output/resumes` and passes validation may the workflow write `Resume Created = X` and a clickable absolute file-URI link in `Resume Link`. Build the link from the actual saved file with Python `Path.resolve().as_uri()`, verify the DOCX exists before writing, and store the complete `file:///` URL directly as the visible `Resume Link` value. Never use a `HYPERLINK` formula or `Open Resume` display text. A failed new generation leaves Resume Created blank and logs the retryable failure in `Notes`, never `Cost`. Never upload resumes to Google Drive, mark Applied, or submit an application.
## Persistent Google Sheets formatting

Preserve user colors, filters, checkbox values, frozen rows, column widths, conditional formatting, formulas, hyperlinks, and manual fields on the live `Job List` tab. Routine operations update only Gecko-managed cell values in place. Never recreate tabs, rewrite entire ranges, change physical row order, or reset formatting or filter criteria. Outside the Gmail response checker, preserve `Response` as a user-owned field.
