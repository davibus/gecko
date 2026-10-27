# Gecko Main — essential instructions

## Current application browser rule — October 26, 2026

Use ONE dedicated Chrome window with ONE tab TOTAL. Reuse the same Gecko-owned
tab for successive jobs. Before leaving any job, save its exact URL, outcome,
missing questions, attachment evidence and available recovery information;
publish the outcome to the primary Google Sheet and verify readback. Then reuse
the tab for blocked, CAPTCHA, skipped, failed and completed jobs alike.
Saving a blocked application means saving information. Unsaved form entries and
uploads are not guaranteed to persist; never claim a server-saved draft without
evidence. Do not retain application tabs as a recovery mechanism.

Adopt an employer popup only when its opener is positively Gecko-owned; save
handoff information and immediately close the old owned tab. Verify both owned
tab count and the dedicated window's TOTAL tab count before every job and after
every outcome. Archive and verify outcomes before reconciling extra owned tabs.
Never close unrelated tabs or windows; isolate Gecko in its own window when
necessary. Unknown ownership or failed recovery/publication pauses the workflow.

An attempted submission without employer confirmation is a JOB-LEVEL blocker.
Save its exact evidence, publish and verify the unconfirmed outcome, preserve
the durable no-retry ledger, then reuse the same tab for the next eligible job.
Never mark it Applied or automatically retry it. Individual blocked, CAPTCHA,
or uncertain applications must not stop unrelated jobs. Pause only for shared
failures such as lost browser control or unverified tracker updates. Constructor
2972 remains CAPTCHA=X and unconfirmed, is never automatically retried, and is
NOT a prerequisite for other applications. This supersedes ALL historical
leave-tabs-open instructions below, in application guides and in the answer bank.
The October 23 automatic-submission policy remains current; OpenClaw stays stopped.
Keep live Ready to Apply=X gating, existing Capture/CAPTCHA=X tracking, actual
elapsed timers and immediate per-job Sheet readback. Historical answer-bank
procedures do not override this lifecycle rule or automatic-submission policy.

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

October 22 user update: Enough Data now receives an automatic content review for
new jobs. Yes requires pertinent job-specific duties, requirements, skills or
outcomes sufficient to tailor a resume; missing, irrelevant, random or unusable
text is No. Use the cached review in description_readiness.py, not a word-count
threshold. Preserve prior manual decisions and all resume-generation safeguards.
This supersedes the older manual-only Enough Data wording above. Formula and
format extension must recognize renamed Gecko/FC word-count columns and reach
the final job row; never copy another job's literal readiness answer.

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

## Automatic application submission — user instruction October 23, 2026

Dave explicitly instructed: "From now on, automatically submit the application when it's finished."
This supersedes the October 21 mandatory review handoff and earlier stop-before-submit instructions for requested job applications, including the current batch.
Complete supported answers, attach and verify the exact matching tailored resume, then automatically submit when the application is complete. Do not ask for another submission approval. Keep incomplete or unverified applications pending and report the exact blocker; never invent answers or repeat confirmed submissions.
After employer confirmation, record Applied and the actual America/Denver Applied Date together in the current authoritative tracker and verify readback. Preserve Previous Applied Date and unrelated fields. A click, dispatch, or prepared draft alone is not proof of submission. Existing recruiting SMS No and factual-accuracy rules continue to apply.

## Direct Playwright attachment verification — October 23, 2026
Dave explicitly instructed: "Don't require a preview or content check before submission anymore."
For direct Playwright applications, a preview/download/content comparison is no longer a submission prerequisite. Verify the exact matching local file, its selected browser filename/size and successful upload. Retain factual-answer checks, exact job identity, duplicate prevention and employer-confirmation requirements. This supersedes older preview/content-check gates for this workflow. OpenClaw remains stopped.


## Discovery query provenance - October 24, 2026
Populate the existing **Query Used to Find** column for discovered jobs from the actual recorded discovery query. Preserve nonblank values and formulas. Never infer a query from the job title or the target-role list. For a genuine full-feed source, identify the feed and say no search query was used. Keep this behavior for future Gecko searches.


## Match threshold experiment - October 25, 2026
Dave requested all three resume-match thresholds: overall at least 60/100, responsibilities at least 50%, and required skills at least 50%. All three must pass. The thresholds are controlled by job-scout/preferences/resume-match.json. Reuse cached evidence but recalculate acceptance against the current thresholds. Keep scoring weights and the evidence, mandatory-blocker, location, salary, fee, rejection and duplicate safeguards unchanged. This overrides earlier references to an overall 80-point minimum or 70% category floors.

## Job-specific resume headline - user instruction October 26, 2026

For EVERY resume, customize the specialization/main title directly below Dave's
name to the exact job's responsibilities, priorities, and required skills. Read
`Variations of Specialization/Main Titles` in the current
`input/master-resume/master-resume-v4.docx`. These are examples, not a closed list:
select, combine, or create the best concise, natural headline supported by Dave's
actual master-resume experience. Lead with the most relevant specialization; omit
unrelated areas and unsupported expertise, seniority, credentials, or claims.
Never automatically reuse `Marketing Technology/AI | Paid Media | E-Commerce |
Analytics | Digital Marketing` across jobs. It is acceptable only when its full
emphasis is genuinely the best fit after reviewing that specific posting.

Review the headline together with the summary and supporting accomplishments,
then inspect its rendered fit in the established header and two-page layout.
The generator ranks master examples as an initial suggestion; the agent must
review suitability and may create better wording. For a custom headline, call
`scripts/gecko_v2.py`'s `set_reviewed_headline(plan, headline, rationale)` before
generation, recording why its claims are supported and relevant. Never bypass
headline validation or copy the master default into every plan. This headline is
professional positioning; preserve verified employment titles and filename/job
identity rules. Existing completed resumes are not regenerated without a request.

## Usable Google Sheets resume links - October 26, 2026

Dave explicitly selected PRIVATE GOOGLE DRIVE LINKS, usable across devices.
Every new resume's Resume Link must be a clickable HTTPS link to the exact
completed DOCX in his private Drive. Keep the validated local DOCX for job
applications. A raw local path or `file:///` URI is not usable in Google Sheets;
HYPERLINK cannot fix that unsupported protocol. This instruction supersedes all
earlier no-upload and raw-file-URI requirements for resume delivery only. Never
make resumes public, convert the validated DOCX, or share them with others.

After native Word and visual QA, upload the exact final DOCX with the connected
Google Drive `upload_file` tool, preserving its filename and DOCX MIME type. Use
the private folder configured in `job-scout/preferences/resume-delivery.json`:
`https://drive.google.com/drive/folders/1Noy8XUqlL5ufqA4aU9jZWdwpMYeCVmol`.
Reuse a verified unchanged upload instead of creating duplicates. Read back the
Drive metadata (ID, observed URL, filename, MIME type, size, parents and private
owner-only permissions), download its raw bytes and compare SHA-256 with the
local DOCX. Save a receipt JSON containing `path`, `metadata` from that readback,
and `download: {"sha256": "<actual downloaded SHA-256>"}`. Register it using
`scripts/register_resume_drive_link.py --receipt <receipt.json>`.

The canonical publisher resolves that verified receipt to its observed HTTPS
URL. Write Resume Link as a clickable Google Sheets hyperlink, verify the cell's
actual hyperlink target, and preserve completion dates, job identity, formulas,
formatting and unrelated fields. Resume Created still requires all existing QA
and completion safeguards. If the connector is unavailable, retain the finished
local file and report Private Drive publication pending; do not silently fall
back to file:/// or claim a working tracker link. Unattended queue runs without
a registered delivery receipt stop at this publication gate and need a connected
agent to perform the upload. Dashboard and applications resolve registered Drive
URLs back to the unchanged local file through `job-scout/resume_delivery.py`.

## Canadian remote jobs allowed - user instruction October 26, 2026

Dave explicitly instructed: If it is Canada, allow it. Treat Canadian remote
jobs, including Canada-only postings and country codes CA/CAN, as geographically
eligible for Gecko discovery, qualification, resume queues and tracker review.
Do not set Qualifies to Apply? to No solely because the country is Canada or the
ATS applicant country is Canadian. This supersedes earlier U.S./Utah-only remote
country restrictions for Canada. Marketbridge ID 2983 is the confirmed example.

Keep other safeguards: fees, permanent rejections, completed-resume protection,
match thresholds, usable job descriptions, and genuine additional location or
residency restrictions. Required Eastern working hours alone are not an Eastern
residency restriction. This does not authorize inventing Canadian citizenship,
work authorization, residency or willingness to relocate; answer application
questions truthfully and surface any unsupported mandatory requirement. The
exception permits remote Canada jobs; it does not make Canadian onsite/hybrid
jobs local Utah jobs or permit every other foreign-country requisition.


## Confirmed GitHub profile - October 26, 2026

Dave confirmed his GitHub profile is https://github.com/davibus
(user-supplied address: www.github.com/davibus). Use this URL for GitHub profile
fields in Gecko applications and relevant profile/contact information. A general
profile URL does not establish a particular project repository, ownership, or
access to an older account. Preserve project-specific answers and their scope.

## Application agreements - standing authorization October 27, 2026

Dave instructed: "Yes. Always agree to any application. Put that in the Gecko instructions."
For jobs Dave authorizes Gecko to apply for, automatically select Agree, I agree,
Accept, or the equivalent for application terms and conditions, privacy notices,
and consent to process the application. This includes Graphite's HR Privacy Notice.
Do not ask Dave for agreement approval again. This supersedes older instructions
to pause merely because an application agreement needs acceptance.

Read the agreement label and context, select the actual control (including a
visible label for a styled radio/checkbox), and verify the selection persists.
Check displayed validation messages before treating the form as complete. This
permission does not establish career facts or answers to eligibility questions.
Dave's separate No preference for optional recruiting SMS/messages still applies.
Keep one tab, Ready to Apply=X eligibility, CAPTCHA skipping, duplicate prevention,
and employer-confirmed submission with immediate verified tracker updates.
An agreement answer does not by itself clear an uncertain submission or authorize
repeating a prior Submit click.
