# Resume performance and review

From `C:\gecko_main`, process only the requested pending IDs:

```powershell
.\.tools\dashboard-python\Scripts\python.exe .\scripts\generate_apply_queue.py --ids 1234 1235
```

Replace the example IDs with actual pending job IDs. The CLI takes the existing
Gecko run lock, synchronizes current primary-Sheet inputs, and retains all queue
eligibility/completion protections. It never submits applications. The daily and
selected-job runners use the same improved queue. Keep the existing AI runner
configuration; these changes do not alter qualification thresholds or models.

The canonical factual authority remains `master-resume-v4.docx`; the established
PDF remains the visual authority. Within one batch, each source access hashes the
actual authority bytes. Unchanged DOCX content is parsed once, including table
paragraphs and list items. Source changes invalidate parsed data and old plans.
There is no persistent factual cache or alternate factual source.

Each resume prints its wall time, active time, review waiting time, phase timings
and validation/fitting counts. Batch totals and individual results are saved under
`reports/resume-performance/`. Set `GECKO_RESUME_TIMINGS` to choose a report path.
Phase times are exclusive: nested source/validation/review time is not counted a
second time in a parent phase. AI factual review is active processing; waiting for
the operator's visual decision is separate.

Fitting measures the actual Word PDF, including the usable space on page two and
overflow onto later pages. It removes lower-priority supporting detail in measured
groups, preserving anchors and role minimums, then fills available space with
distinct relevant evidence. Typography, margins and quality gates are unchanged.
Rejected experiments restore the entire prior plan and exact DOCX/PDF/native/QA
artifacts without rebuilding or revalidating unchanged content. Exceptions also
restore the last checkpoint and stop completion. Validation reuse is batch-local
and requires matching DOCX bytes, plan, authorities, runtime and validator/parser
versions. Visual approval is never supplied by that cache.

Native desktop batches start the existing Word bridge as a private, hidden,
sequential worker on the first validation. It creates its own Word COM instance,
closes every document, recycles a failed COM session, and quits its owned instance
when the batch exits. Ordinary pagination overflow keeps the session warm.
Sandbox/service tokens retain the permanent interactive-user bridge. No code
attaches to existing Word or terminates Word processes by name. The direct
single-document validator remains available. Private-worker diagnostic logs are
under `scratch/resume-word-sessions/`.

After passing native Word/PDF QA and duplicate checks, the canonical generator
renders two fresh PNGs and writes `visual-review-request.json` in the job scratch
directory. The reviewing operator/agent must open both images and compare them
with the established model, checking readability, clipping, overlap, aligned job
headings/dates, complete sections and page-two density. Write the decision to the
unique `decision_path` using the request's `decision_example`, with actual review
notes. Request ID and both artifact hashes must match; old decisions cannot
satisfy a new request. Rejection or timeout leaves the job incomplete. The
generator preserves the images and review evidence. The normal reviewing agent
can perform this check; another agent or generator is not required.
The existing `work/run_all_qualifying_resumes.py` batch recorder retains its
`visual-request-<id>.json` / `visual-<id>.json` handoff, without a second review
wait. It now archives prior approvals before requesting a fresh decision, checks
both artifact hashes, reuses the generation context, and measures its review wait.

After each approved resume, the SQLite-backed queue publishes exactly
`Resume Created`, `Resume Created Date` (America/Denver), and `Resume Link` to the
existing primary Sheet. It resolves live headers, checks stable ID/company/title/
posting URL, rechecks primary-Sheet eligibility/rejections, protects formulas,
checks three-way conflicts/removals and rechecks for edits before dispatch.
Independent readback verifies identity, all three values and frozen headers before
updating only those local cache/baseline cells. Unrelated edits wait for ordinary
reconciliation; there is no whole-row replacement, formatting reset or end-of-batch
completion buffer. A failed dispatch/readback preserves the local completion
state and baseline. If the remote write succeeded before a later readback failure,
the next ordinary reconciliation imports that result; do not regenerate it.

Preparation, Word operations and tracker writes remain sequential. Overlapping
preparation was left out: the measured local fitting/Word savings do not justify
another queue or concurrent generator, and review remains an explicit gate.

Development evidence is isolated under `scratch/resume-performance-20261026/`.
Benchmarks use the same source-backed plan/listing with old/new code and private
outputs. They do not publish resumes, modify tracker rows or generate applications.
Live Sheet latency and full AI drafting latency require a real authorized batch
and are not established by these local comparisons.

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
