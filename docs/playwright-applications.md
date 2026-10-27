# Direct Playwright applications

## One dedicated window, one tab total — current policy

All selected-ID browser modes (`--apply`, `--draft-only`, with or without
`--sequential`) use the single-tab lifecycle in `application_browser.py`.
`application-browser.json` records owned Chrome target/window IDs across runs.
Before every selected job and after every outcome, `browser-tab-count.json`
records the actual dedicated window's TOTAL tab count and the owned tab count.
Both must equal one. An unrelated tab is never closed to satisfy the count;
Gecko is isolated in a new window or pauses until ownership is resolved.

`recovery.json` saves the exact observed URL, outcome, missing questions, observed
fields, attachment evidence and submission evidence before a job leaves the tab.
The Sheet outcome must be read back before navigating the same tab to a blank
page and then to the next job. This applies to ALL outcomes, including CAPTCHA,
blocked and failed jobs. Unsaved entries/uploads are not guaranteed to persist;
recovery requires checking employer state and refilling supported answers.
Old draft-preservation/leave-tabs-open procedures are superseded by this policy.

An employer popup may replace the tab only with a verified Gecko-owned opener.
Save handoff information, record its target, immediately close the old tab, and
follow confirmation in the sole replacement. An attempted submission without a
verified employer receipt is saved as unconfirmed and never automatically
retried. Publish and verify that outcome, preserve the attempt ledger, then reuse
the tab for the next eligible job, including after interruptions. Individual
blockers do not pause unrelated jobs; only shared browser/control or tracker
verification failures pause the batch. Constructor 2972 remains CAPTCHA=X and
unconfirmed but is not a continuation prerequisite. This replaces the earlier
stop-on-uncertainty instruction. Never retry Submit without separate resolution.

To consolidate an old batch without starting applications, run
`scripts/reconcile_application_tabs.py --evidence-dir <existing batch> --consolidate`.
It archives live recovery information, appends and verifies Sheet recovery notes,
then closes only positively identified owned tabs. Without `--consolidate` it
only inventories ownership and windows. No fill, upload or submit is performed.

## Improved selected-job workflow - October 26, 2026

For a scoped sequential run, add `--sequential --apply` to the selected-ID
command. It reads the existing Ready to Apply?/Ready to Apply and CAPTCHA/Capture
headers without creating fields, uses current Sheet row order, and skips blanks,
prior Applied jobs and CAPTCHA markers. Each outcome appends Notes and reads it
back before advancing. CAPTCHA also sets the existing tracking field to X.
`current-progress.json` and the running console show actual per-job/batch elapsed
time; `batch-summary.json` and per-job checkpoints preserve verified outcomes.
Elapsed time in Notes is measured before the final verification; the final elapsed
time in the checkpoint includes that readback. Reuse the same evidence directory
to resume remaining jobs; completed verified outcomes are not repeated.

From `C:\gecko_main`, prepare selected jobs without opening a browser or writing
tracker cells (replace the example IDs):

```powershell
.\.tools\playwright-python\Scripts\python.exe .\scripts\playwright_direct.py --ids 1234 1235 --evidence-dir .\reports\playwright-pilot\selected-batch
```

For a batch Dave has explicitly asked to apply for, use the same command with
`--apply`. Use `--draft-only` instead to fill authorized drafts without submission.
This implementation request does not itself authorize running either browser mode
against employers. Keep using the dedicated Chrome session at `127.0.0.1:9333`.
If that browser is unavailable the command stops with its packets preserved; it
does not attach to the user's main browser or start OpenClaw.

Re-run the same IDs and evidence directory after an interruption. An OS lock
releases when a process exits; a leftover `batch.lock` is diagnostic, not a reason
to delete progress. The single owned target is reclaimed using its persisted ID.
Interrupted job information is archived and its outcome verified before reuse;
no per-job draft tab is recreated. Saved information does not guarantee saved
employer form entries. A saved receipt is
reconciled through the tracker without reopening or refilling the application.
An attempted submission without a receipt stays pending for employer-state and,
if necessary, actual submission-date reconciliation. Never retry its Submit click.
Legacy attempts in other evidence folders remain protected, and new exclusive
ID/posting-URL claims prevent repeats across batches and posting aliases.

Before the browser opens, primary-Sheet preflight checks identity, current
eligibility, location, fee/rejection/expiration/duplicate exclusions, Applied and
the matching existing nonempty DOCX. Description identity and the canonical resume
identity registry connect short resume filenames to the actual source job number.
Private Drive links resolve through the current `job-scout/resume_delivery.py`
receipt to the unchanged local DOCX; application preparation performs no Drive
uploads, downloads, public sharing or link repairs. Legacy local links remain
usable for selecting existing local application artifacts without rewriting them.
The packet records file bytes/hash and applicable confirmed answers. The native
dashboard-Python tracker worker stays alive for the batch and renews the API
transport for each request after observed stale-connection timeouts;
headers and job state are still read fresh before each application and submission.

The master DOCX (including tables and list paragraphs), saved answers and reviewed
index are parsed once per content version. Actual source bytes are checked again
before each job/step. The index records question meaning/aliases, source and quote,
confirmation date, status and employer/job scope. Changed answer-bank bytes
invalidate previously reviewed bank records until the index is reviewed against
that version. Proposed, historical-only, conflicting or unsupported entries cannot
become confirmed answers. New confirmations must update the bank and index together.

Lever, Greenhouse, Ashby and JazzHR use conservative contact-field hints observed
in existing Gecko evidence. Labelled questions retain priority over field names.
Other forms use the same semantic lookup and exact missing-question fallback.
The explicit `--request` fallback also checks answer meaning, scope and value;
it cannot fill proposed wording or submit through a generic click/Enter action.
Each preparation step inspects the form, fills confirmed fields with native browser
actions, and reads the actual DOM again after UI event processing. ARIA dropdowns
require a matching option selection and persisted value; typing is not selection.
Conditional fields or navigation create a fresh inspection. Submission guards
separately recheck live identity, attachment and validation.
Populated answers are preserved; an unknown required answer or a new agreement is
not treated as confirmed merely because it is populated. Account/profile edits,
login and human verification stay pending as saved information. Exact questions,
URLs and recovery evidence are checkpointed, and the same tab continues to the
next authorized ID only after the current outcome is verified in the Sheet.

Resume selection is read back by exact filename/size. Upload waits watch busy,
completion and error conditions with a 20-second bound; they do not sleep a fixed
number of seconds. Native forms that send the selected file with the final form
retain that existing verification policy. Previously acknowledged matching uploads
are reused. A positive receipt is saved durably, then Applied and the actual Denver
Applied Date are written together immediately and independently read back before
optional screenshot work. Only those two named cells are updated; formulas, prior
dates, manual fields, formatting and larger frozen regions are preserved.

`packets.json`, `preparation.json`, per-job `state.json`/`latest.json`, and
`progress.json` stay under the chosen ignored evidence directory. Timings report
exclusive preparation, inspection, filling, upload, condition waiting, confirmation
and tracker-update seconds, plus wall time and counts. Preparation totals include
the initial batch preflight; individual job reports include their fresh checks.

## Isolated verification and measurements

```powershell
.\.tools\playwright-python\Scripts\python.exe -m unittest discover -s scripts -p test_application_workflow.py
.\.tools\playwright-python\Scripts\python.exe -m unittest discover -s scripts -p test_playwright_submission.py
```

The tests use temporary source/resume fixtures, local DOM pages with network
aborted, and mocked tracker operations. Their buttons change fixture text only.
They test scopes and proposals, changed sources, unknown/conditional required
questions, upload conditions, duplicate claims, interrupted checkpoints/locks,
receipt recovery, immediate per-job updates, formula/movement conflicts and frozen
header readback. No employer application or live tracker row is changed.

Comparable old/new helper measurements and the preserved pre-change helper are
under `scratch/application-performance-20261026/`. Reproduce them with:

```powershell
.\.tools\playwright-python\Scripts\python.exe .\scripts\benchmark_application_workflow.py --baseline-source .\scratch\application-performance-20261026\playwright_batch_before.py --out .\scratch\application-performance-20261026\comparison.json --samples 3
```

The comparison uses identical local forms and Chrome, alternates old/new order,
aborts all network and mocks tracker preflight/writes. It establishes local helper
costs only. Three runs per version on October 26 produced these median milliseconds
(phase medians do not necessarily sum to the median wall time):

| Phase | Before, ms | After, ms |
| --- | ---: | ---: |
| Preparation | 1.5 | 4.2 |
| Form inspection | 163.8 | 94.7 |
| Filling | 67.9 | 13.6 |
| Resume selection/upload verification | 17.6 | 51.4 |
| Waiting | 8,027.0 | 9.6 |
| Submission/confirmation and evidence | 156.8 | 195.5 |
| Mocked tracker update | <1 | <1 |
| Total wall time | 8,450.4 | 435.7 |

Snapshots fell from five to two per fixture application, including the fresh
submission guard. Master, saved-answer bank and index parsing each occurred once
across the three-job batch. Added upload verification and durable submission
guards have measurable costs; their phases are not claimed to be faster. The
total reduction primarily comes from eliminating fixed waits. This is not a live
end-to-end application-speed measurement.

Real employer response times, Google Sheets latency, login/CAPTCHA and
unfamiliar/unknown questions remain unmeasured bottlenecks. Delivery links without
an unchanged registered local receipt are held for review rather than guessed
back into filenames. No completed resume is regenerated to bypass a blocker.

## Application failure repairs - October 27, 2026

CAPTCHA classification now checks live frame ancestry, visibility and opacity.
An invisible reCAPTCHA badge, empty integration container, or hidden challenge
frame is not a blocking challenge. A visible verification checkbox/challenge still
blocks the job and is never solved automatically. `captcha_detection` records the
matched visible evidence before an existing CAPTCHA field is marked. Historical
CAPTCHA marks are not cleared automatically; review each before an authorized retry.

Resume discovery excludes site-wide profile uploaders, including Jobicy's
`global_resume_upload_input`. Such a listing needs its employer application URL;
do not upload a resume to a global account/profile control. Legitimate hidden
employer resume inputs remain supported. Capture browser filename/size before an
upload handler clears/replaces the input, then require completion acknowledgement.
Navigation invalidates old field handles; inspect the destination before further
actions. The observed Breezy `Apply To Position` link is supported.

Exact, reviewed LinkedIn and compensation wording variants are indexed. The old
confirmed Pearmill budget response is employer-scoped; AI-generated drafts are not
promoted to confirmed answers. Unknown questions still need Dave's answer. Existing
manual Applied markers and dates always win over readiness or historical blockers.

Automation failures carry a workflow fingerprint so an implementation repair can
invalidate their cached diagnosis in a newly authorized run. Do not delete prior
attempt ledgers or automatically retry uncertain submissions. Finished checkpoints
remain historical outcomes; a supervised retry uses a fresh evidence directory and
fresh eligibility checks. No large batch was restarted during this repair.

Regression verification: `scripts/test_application_repairs.py` uses local synthetic
forms and blocked external requests. The October 26 performance numbers above are
historical measurements, not measurements of the repaired October 27 workflow.

## Earlier one-job interfaces and evidence

The current October 23 batch runs locally with Python Playwright and installed Google Chrome. OpenClaw remains stopped. The scripts make no model calls; Codex assistance with unfamiliar forms and questions still uses the account allowance. No scheduled job was installed.

## Runtime and evidence

Use `.tools/playwright-python/Scripts/python.exe` with the pinned `scripts/playwright-requirements.txt`. Installed Chrome uses a separate `.tools/playwright-direct-profile` and a loopback-only debugging endpoint at `127.0.0.1:9333`. The user's main browser profile is separate. Closing a short-lived script preserves browser tabs.

`scripts/playwright_direct.py --request <request.json>` processes explicit actions on the exact job tab. The current packet/evidence directory is `reports/playwright-pilot/direct-20261023`. Its batch paths are specific to this authorized 40-job run; do not reuse it for unrelated applications. Private application evidence is ignored by Git.

The older `playwright_application.py` is a draft-only single-job pilot. `playwright_batch.py` supplies shared helpers and the older command-folder worker. Keep earlier submission-attempt ledgers: a new folder does not authorize a repeat submission.

## Submission policy

Dave authorizes automatic submission of complete applications from this batch. Read the answer bank before each application; preserve confirmed Applied jobs and unknown-answer drafts. Use only the matching existing tailored resume. Preview or downloaded-content checks are no longer required. Verify the source file, matching selected filename and size, and site attachment acknowledgement. Some sites send selected files with the final form rather than uploading separately; require the matching selection and displayed filename, followed by employer confirmation.

The same-stem PDF is permitted for 829 Studios after native Word/PDF validation. Humana's shortened upload copy must remain byte-identical to its original tracked DOCX. Neither operation regenerates or replaces the original tailored resume.

Never solve or bypass CAPTCHA, invent qualifications, create accounts automatically, or repeat a submission with an unresolved result. Leave CAPTCHA applications for Dave after other complete applications.

## Confirmation and tracking

Fresh Google Sheet preflight checks the unique ID, employer/title, eligibility, exclusions, existing Applied state, and exact Resume Link. A submission-attempt ledger is written before the final click. A click or timeout never marks Applied.

After a positive employer receipt, `scripts/playwright_tracker.py --receipt <receipt.json>` writes Applied=X and the actual America/Denver Applied Date together in the primary Google Sheet, verifies both by readback, and preserves Previous Applied Date, formulas, unrelated cells, and frozen row 1. A screenshot failure must not prevent an already-confirmed receipt from reaching the tracker.

If an employer uses unexpected confirmation wording, inspect the saved page and reconcile its positive receipt through the tracker helper without clicking Submit again. Email verification remains pending until completed.

## Checks

`test_playwright_submission.py` exercises required-answer and attachment checks, positive receipt handling, tracker verification, and repeat-submission prevention against a local fake form. It never sends an employer application.


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

### Agreement control repair and validation evidence - October 27, 2026

Inspect associated visible labels for styled native radio buttons and checkboxes.
A hidden native input does not make its visible label unavailable. Ashby marks
some required groups on the question heading instead of the native input; read
that marker within the actual field container. Do not infer it from another field
or the whole page. Use the observed label to click, then read the checked state.

The reviewed agreement answer can cover equivalent terms/privacy acceptance
questions; it does not answer arbitrary Yes controls, factual certifications, or
recruiting-message opt-ins. Missing or unsupported required answers still block
submission. After Submit, collect displayed validation messages immediately and
save submission-validation.json. Include those messages in the verified tracker
outcome. A validation message is not a receipt and does not erase an attempt claim.

Regression evidence: scratch/application-agreements-20261027/. Live Graphite
inspection verified the required marker and persistent Agree selection without
another Submit click. That inspection alone does not reconcile its earlier attempt.

Breezy questions can use headings instead of native labels. Read their local
question container, choice-option text, and empty selected-option text; an Angular
placeholder value is not an answer. Verify named checkbox groups against reviewed
choice lists, and treat at least one selected supported option as satisfying a
required group. Preserve a resume-imported summary only after reviewing it against
the exact matching resume and indexing that supported wording. Salary frequency
is a separate field from the annual amount.

Breezy disables Submit while processing the uploaded resume. A selected filename
alone does not end that wait. Observe the employer's busy/disabled state; after it
clears, inspect the form again for imported or conditional fields. Bounded waits
report processing problems rather than treating a temporary disabled button as
a missing final control.

Confirmation polling tolerates a temporarily missing document body during
navigation. If the initial check fails, a freshly captured recovery page can
reconcile a receipt only with the matching attempt, job identity, later capture
time, same-origin application path, explicit completion wording and no remaining
visible input fields. Save that receipt and verify Applied/date before leaving.
This never repeats Submit and never converts a timeout alone into success.

Plan Left 2993 was confirmed on October 27 in
reports/playwright-pilot/supervised-2993-completion-20261027/2993/receipt.json;
Applied=X and Applied Date=2026-10-27 were independently read back. Graphite 2990
remains protected as unconfirmed; its agreement-control fix is verified separately.
