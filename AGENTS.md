# Gecko Main — essential instructions

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


- Canonical project: `C:\gecko_main` (`gecko_main`, not the retired `gecko_website`).
  Preserve unrelated changes, credentials, resumes, job data, and manual fields.
  Opening the workspace must not launch tasks or scripts. Use native Windows.
- **SQLite is authoritative:** `job-scout/preferences/tracker-backend.json` selects
  the backend; `job-scout/data/jobs.sqlite3` owns current tracker state. This rule
  supersedes older Sheets wording in other files. Never import/sync Sheets over
  SQLite or revert the backend. Sheets exports are manual via the dashboard only;
  daily runs retain local backups. See `docs/sqlite-workspace.md` when needed.
- Execute requested work through the canonical live path and verify actual results
  by readback. Preserve protected/manual fields, stable job identity, eligibility,
  fee and rejection exclusions. Do not infer permission for unrelated actions,
  schedules, messages, purchases, or applications from setup or a normal daily run.
- **Existing resume guard:** trimmed/case-insensitive `Resume Created = X` always
  blocks regeneration, even with a blank link. Preserve it and report missing links
  for review; do not backfill. A link with a blank marker also requires review.
- **Resume authorities:** facts only from `input/master-resume/master-resume-v4.docx`;
  layout only from `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`.
  Re-read sources for generation, invent no claims, and stop if either is missing.
  Final DOCX must pass native Word validation as exactly two pages before completion.
- “Run Gecko” uses the existing `Gecko` task via `scripts/Start-Gecko.ps1`;
  `Gecko --status` checks progress. Read the operations guide first, do not duplicate
  an active run, and do not invent a schedule. It does not submit applications.

## Load only the guide needed for the task

These guides are mandatory for their matching work, not a startup reading list.
Follow their additional references only when the relevant workflow requires them.

| Work | Required guide |
| --- | --- |
| Daily run, runner, workspace or terminals | `docs/agent-guides/operations.md` |
| Resume generation, tailoring, naming or Word QA | `docs/agent-guides/resumes.md` and `GECKO_SYSTEM.md` |
| Tracker, discovery, approvals, reports or resume queue | `docs/agent-guides/tracker.md` |
| Requested applications or application automation | `docs/agent-guides/applications.md`; custom answers remain in `openclaw/application-answers.md` |
| Dashboard table changes | `dashboard/AGENTS.md` |
| Explicit work on the preserved Google Sheet | `docs/agent-guides/legacy-sheets.md` |

Keep workflow details in these guides rather than expanding this root file.
Dave's detailed resume rules and custom answers remain binding in their task scope.

For each job description, select only relevant, source-supported facts from the version 4 master. The master is a career archive, not content to include in full; keep the established two-page resume format.

User-confirmed version 4 exception: if an employment title is omitted in the master, retain the verified company and location without inventing a title. The master archive itself has no one-line or page-limit requirement; apply layout rules only to the finished resume.

Read the version 4 Word master directly for every resume, including paragraphs, tables, and list items. No text export, older master, or cover letter is an alternate factual source. Fill as much of both pages as practical with relevant, distinct, master-supported evidence; never add filler or inflate spacing to fill pages. The master cover letter is reserved for a later explicit request.

## Resume content density

Exactly two pages is necessary but not sufficient when useful, job-relevant evidence remains. Education & Certifications should finish within approximately 0.5 inch (36 points) above the normal bottom text boundary on page two. Use distinct, source-supported accomplishments and relevant project detail, prioritizing the most relevant roles; there is no fixed two- or three-bullet ceiling. Keep standard sections, readable model typography, and normal margins/spacing. Do not fill space with larger fonts, inflated spacing, blank paragraphs, repeated claims, unrelated material, or an education footer/text box. Inspect both rendered pages and measure the final section after native Word/PDF validation. If genuinely relevant evidence is exhausted, document the reviewed evidence and explain the remaining gap; page count alone is not completion.


## Completion dates — user instruction October 20, 2026

Whenever a confirmed application is marked Applied, write its actual submission date to **Applied Date** in the same update. Use America/Denver dates (YYYY-MM-DD); when Dave confirms submitting today, use today. Preserve **Previous Applied Date** as history. If the actual date is unknown, ask rather than inventing it.

Whenever a resume is successfully created and verified, write its actual completion date to **Resume Created Date** together with Resume Created and Resume Link. Do not substitute CV Created Date or overwrite historical dates merely during sync. Resolve all columns by unique header name, never position. Verify both the completion marker and date by readback. This supersedes earlier wording treating Resume Created Date as exclusively user-managed.

## Mandatory application review handoff — October 21, 2026

For EVERY OpenClaw job application, fill supported answers and attach the matching tailored resume, then STOP before the final Submit, Send application, Finish, or equivalent submission action. Leave the exact application tab and draft open so Dave can review every answer and submit it himself. Do not close or refresh away the draft.

Notify Dave for each completed draft: "Ready for your review and submission," identifying the employer, job ID/title, and application link or tab. If anything remains incomplete or unverified, say "Needs your attention" and list the remaining items instead of claiming it is ready. Keep that tab open too; continue other authorized jobs independently.

This standing rule applies to every application, including batches and resumed drafts after answers, login, or CAPTCHA. A request to "apply" does not authorize automatic submission. This replaces older auto-submit instructions. Do not mark Applied merely because a draft is ready; after confirmed submission, record Applied and the actual Applied Date together and verify readback.

## Recruiting message consent — October 21, 2026
Dave's standing instruction: select No whenever any company asks permission to send recruiting text/SMS messages or recruiting-message updates. Apply automatically to all current and future applications, including PerfectServe and Opiniion. This supersedes earlier employer-specific Yes answers, including Five Star. Do not treat this as refusal of ordinary application email correspondence or required account verification messages.
