# OpenClaw workflow instructions

## Columns follow names, not positions

Users may move whole columns freely without asking for code or instruction updates.
Read live headers on every sync; use unique header names for fields and stable IDs
for jobs. Never restore a saved order or treat column letters/counts in documentation
as requirements. Automatic idle sync adopts the current order and preserves custom
columns, resume links and Sheet formulas. Moving columns is different from renaming
or deleting a field: missing or ambiguous names must be resolved without guessing.
Keep row 1 frozen. Historical layout tables are reference snapshots only.


## Current column layout — October 20, 2026

See `docs/current-tracker-columns.md` (repository-relative) for the verified 36-column layout and field behavior. This supersedes historical letters and schemas below. Resolve unique live headers by name and jobs by ID; never sort or move only part of a job row. Qualifies to Apply? is the eligibility field (legacy internal alias Apply?). Applied Date is primary; Previous Applied Date is preserved history, wherever those named columns are moved. Cover Letter, CV Created Date, Cover Letter Link, and Cover Letter Created Date remain user-managed. Create Resume is a preserved Sheet formula showing Yes only when Enough Data is Yes; it does not start generation. Enough Data is a saved review, not an automatic AI assessment. Preserve Job Description, Notes, Previous Notes, word-count formulas, all jobs and resumes, and frozen row 1. The removed Cursor Instructions tab must not be recreated automatically.

Follow the root AGENTS.md. For requested applications or application automation,
read docs/agent-guides/applications.md and openclaw/application-answers.md before
acting. The answer bank retains Dave's custom answers and preferences. For resume
attachments read openclaw/resume-upload.md. Do not load the answer bank for unrelated
connector maintenance. Never repeat a confirmed application submission.


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

## Job-specific resume headline - October 26, 2026

Any resume creation triggered from this workflow must follow the job-specific
headline rule in `docs/agent-guides/resumes.md`: read the master v4 section
`Variations of Specialization/Main Titles` as examples, then select, combine, or
create the best source-supported specialization for the exact posting. Do not
reuse the broad master headline automatically. Review the headline with its
summary and accomplishments, preserve historical employment titles, and check
its rendered fit before marking a new resume complete.

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
