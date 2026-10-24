# Attach the matching output resume through OpenClaw

Use this procedure for requested applications. Upload authorization does not
itself authorize submission. Never reopen or resubmit a confirmed application.

1. Read the current repository instructions and tracker backend. Resolve the
   requested job by stable identity in the active SQLite tracker. Confirm company,
   title, application URL, and its exact Resume Link. Decode a file URI as a URI
   (preserve literal plus signs); do not choose the newest file or search Downloads.
   An existing Resume Created = X never authorizes regenerating a missing file.
2. Confirm that the matching nonempty DOCX exists directly in
   `C:\gecko_main\output\resumes`. Keep it there as the authoritative artifact.
   The dashboard download is a copy of that file, not another required source.
3. Run this helper using native Windows, substituting the verified exact path:

   ```powershell
   & 'C:\gecko_main\.tools\dashboard-python\Scripts\python.exe' 'C:\gecko_main\scripts\stage_openclaw_resume.py' --resume 'C:\gecko_main\output\resumes\<exact-matching-file>.docx'
   ```

   It returns JSON with `media_ref`, filename, byte count, and SHA-256. It verifies
   the managed inbound copy and refuses to replace a different file of the same
   name. Do not claim attachment yet.
4. Use OpenClaw's browser tool with profile `windows-chrome`. Locate the existing
   application tab in the OpenClaw group, verify its URL and job identity, and keep
   using that exact target. Avoid creating a second draft when the intended tab
   already exists. If the user's tab is not shared, ask them to share that tab.
5. Inspect the actual file input. Use `action: "upload"`, the exact `targetId`,
   `paths: [media_ref]`, and either `inputRef` or `element` (not both), with
   `timeoutMs: 20000`. Hidden file inputs can be targeted directly. If the page
   offers only a chooser button, use the supported upload `ref` operation.
   Do not type a path into a text field or invent an attachment confirmation.
6. Verify the ACTIVE resume selected for this exact application, not merely a
   filename in upload history, the account's saved-resume list, or a temporary
   file input. A stored/default resume (including K9 Sport Sack) must never
   replace the job-specific resume. On Indeed, review-module URLs are shared
   across jobs: identify the visible employer and role on the actual draft and
   keep the same verified browser target throughout the edit and final review.
   Open the selected attachment's preview or download through the supported
   browser path and compare its heading and professional summary with the
   exact local DOCX. Confirm the job-specific resume remains selected after
   navigation back to the final review page. If the site converts DOCX to PDF,
   verify the converted content too; filename similarity alone is insufficient.
   If preview/content or exact draft identity cannot be verified, report the
   attachment as UNVERIFIED and leave the application pending for Dave.
   Do not change the account-wide default resume or another job's draft.
   Also inspect separate resume-derived work-history/education fields. Sites may
   keep values parsed from an older resume even when the correct attachment is
   selected. Compare dates, titles, and descriptions against the chosen resume;
   correct application-specific mismatches using verified source facts. If the
   edit would change an account-wide profile, report that separately for Dave.
   Do not call the application ready while known factual mismatches remain.
7. Read back the file input's file name and size and the page's attachment status.
   Wait for the site's upload to complete and check for errors. If the field is
   cleared after the site processes it, use its visible attachment confirmation.
   A tool success alone is not proof. Stop and report any mismatch or timeout;
   do not loop the same failed upload or ask the user to locate a known existing
   resume merely because the connector failed. Submit only within the user's
   application authorization after all required fields and attachment are verified.

## Installed connector repair â€” 2026-10-16

OpenClaw 2026.10.4's extension upload route treated the browser as accepting local
filesystem paths. A synthetic file reproduced the same repeated
`locator.setInputFiles` timeout seen on Rula. The installed route now sends file
payloads through Playwright for `local-extension` mode; other browser modes are
unchanged. Existing path validation, browser access checks, and upload limits
remain in place. The file payload route requires files smaller than 50 MiB.

Installed file: `%APPDATA%\npm\node_modules\openclaw\dist\routes-OvJdcQl9.mjs`.
Original backup and test evidence:
`C:\Users\DCALL\Documents\Codex\2026-10-15\so-i\work\upload-test`.
This is a local installed-package repair. An OpenClaw update can replace it.
After an update, run a synthetic attachment check before promising uploads work;
do not blindly apply this version-specific edit to a different release.

## Mandatory application review handoff — October 21, 2026

For EVERY OpenClaw job application, fill supported answers and attach the matching tailored resume, then STOP before the final Submit, Send application, Finish, or equivalent submission action. Leave the exact application tab and draft open so Dave can review every answer and submit it himself. Do not close or refresh away the draft.

Notify Dave for each completed draft: "Ready for your review and submission," identifying the employer, job ID/title, and application link or tab. If anything remains incomplete or unverified, say "Needs your attention" and list the remaining items instead of claiming it is ready. Keep that tab open too; continue other authorized jobs independently.

This standing rule applies to every application, including batches and resumed drafts after answers, login, or CAPTCHA. A request to "apply" does not authorize automatic submission. This replaces older auto-submit instructions. Do not mark Applied merely because a draft is ready; after confirmed submission, record Applied and the actual Applied Date together and verify readback.

## Automatic application submission — user instruction October 23, 2026

Dave explicitly instructed: "From now on, automatically submit the application when it's finished."
This supersedes the October 21 mandatory review handoff and earlier stop-before-submit instructions for requested job applications, including the current batch.
Complete supported answers, attach and verify the exact matching tailored resume, then automatically submit when the application is complete. Do not ask for another submission approval. Keep incomplete or unverified applications pending and report the exact blocker; never invent answers or repeat confirmed submissions.
After employer confirmation, record Applied and the actual America/Denver Applied Date together in the current authoritative tracker and verify readback. Preserve Previous Applied Date and unrelated fields. A click, dispatch, or prepared draft alone is not proof of submission. Existing recruiting SMS No and factual-accuracy rules continue to apply.

## Direct Playwright attachment verification — October 23, 2026
Dave explicitly instructed: "Don't require a preview or content check before submission anymore."
For direct Playwright applications, a preview/download/content comparison is no longer a submission prerequisite. Verify the exact matching local file, its selected browser filename/size and successful upload. Retain factual-answer checks, exact job identity, duplicate prevention and employer-confirmation requirements. This supersedes older preview/content-check gates for this workflow. OpenClaw remains stopped.
