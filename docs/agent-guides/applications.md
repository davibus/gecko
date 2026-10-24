# OpenClaw applications and saved answers

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


Read only for requested applications or application workflow changes.
Before each application, read openclaw/application-answers.md. That unchanged
file holds Dave's custom answers, identity preferences, and batch instructions.
Use Gecko in OpenClaw for the browser application work, as Dave requested.
Read openclaw/resume-upload.md before attaching a resume; use the requested job's
matching existing output/resumes artifact and verify attachment readback.
Do not regenerate an existing completed resume. Preserve explicit review-first
requests, pending drafts, human challenges, and confirmed submission identity.
The active SQLite tracker controls Applied writes; preserved Sheets references
in older notes never authorize importing or overwriting the current database.

## OpenClaw application batches

Read `openclaw/application-answers.md` before every application. For job IDs Dave
explicitly asks to apply for, prepare drafts for Dave to review and submit himself. A job needing Dave's attention must not block the rest
of the batch: preserve its draft and exact missing fields as pending, continue
immediately to the next ID, and collect the pending actions for Dave to resolve
when he returns. Use each job's matching tailored resume, never guess required
answers, and update Applied only after employer confirmation with tracker readback.
Resume pending jobs after answers arrive without repeating confirmed submissions.

## Fill known fields first and leave for review - October 19, 2026

Dave requests review before submission. This newer instruction overrides older
automatic-submission wording. Leave final submission to Dave.
Attach and verify the matching existing tailored resume and fill all accessible
fields supported by confirmed answers and the current master resume. Preserve
existing user-entered answers. Unknown required questions must remain blank, but
do not stop filling other independent fields because one answer is unknown.
Collect the exact remaining question labels and explain any page-navigation
barrier. Never guess, use placeholder answers, or bypass validation. If login,
CAPTCHA, OTP, a new agreement or a fee blocks access, preserve the draft and report
that action. Leave the existing application tab open for Dave's review, including
single-page applications with no separate review screen. Never click Submit,
Send application, Finish or another final submission control under this request.


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
