# Current live Gecko tracker

Google Sheets remains authoritative.
Read at 2026-10-16T11:16:19.465149+00:00; workbook 1-HnqGq3Il7SZDlNdB6vChN4GAznxWh8ZHjS7Czq8t8I.

Resolve headers by name; preserve formulas and manual fields.
A local pull must preserve Last Updated. Existing Resume Created = X blocks generation.

## Daily Tasks (ID 1035087580)

DAILY TASKS

## Daily Run (ID 2104308869)



## Job List (ID 1274044170)

ID, Source, Company, Job Title, Apply?, Resume Created, Applied, Cost, Notes, Apply or on Company Website (If Indeed), Response, Location, Work Arrangement, Employment Type, Salary, Job URL, Resume Link, Last Updated, Date Posted, Date Found, Last Seen

## Deleted Jobs (ID 1798362999)



## Scratch (ID 1775950516)



## Rejected Jobs (ID 1868015582)

Source, Job ID, Original Job URL, Normalized Job URL, Company, Job Title, Date Rejected, Reason or Status

## Cursor Instructions (ID 2074656464)

## Canonical project name

## Run Gecko command

When the user says **run Gecko**, start the on-demand Windows task named
`Gecko` with `scripts/Start-Gecko.ps1` (terminal command: `Gecko`).
Use `Gecko --status` for progress. Follow `docs/gecko-command.md` for the
ordered daily report, discovery, local tracker/Cursor sync, tailored approved
resume workflow, and final refresh. Do not start a second run while it is
active. No clock-based schedule has been requested.

## Canonical project identity

The canonical project name is **Gecko Main** and its canonical directory is `gecko_main`. The former directory/name `gecko_website` is deprecated. All new scripts, documentation, commands, paths, and configuration must use Gecko Main and `gecko_main`. Do not rename the current project root or any external resource as part of this naming rule.

## Cursor terminals

See `docs/cursor-terminals.md` for the global persistence settings and workspace-specific terminal behavior. Preserve restored sessions and their existing names and working directories. Opening the workspace must not launch terminal tasks or project scripts.

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

## Execution default

Execute the live write path by default for requested work. Implement the requested change and run the affected canonical workflow so the real files and configured Google Sheet results are visible. Do not substitute a dry run, preview, simulation, mock execution, or instructions for an authorized live execution, and do not stop after editing code when execution is necessary to complete the request. Explicit dry-run and other read-only commands remain available only when the user requests them or when the command is inherently diagnostic.

Authorization covers the requested work and its necessary writes, including generated resumes and managed tracker cells. It does not authorize unrelated actions, job applications, messages, purchases, destructive operations, or bypassing access restrictions. Preserve eligibility rules, Cost `x` exclusion, duplicate prevention, protected/manual fields, and unrelated data. After every live tracker write, read the affected cells back and verify the expected values and resume link target. If execution is blocked, report the exact blocker and what actually changed; never claim a live write succeeded without verification. Do not ask the user to reconfirm actions already authorized by the request.

## Source of truth

The permanent Gecko authorities are:

- Content: `input/master-resume/master-resume-v2.txt`
- Visual format and layout: `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`

In this checkout the absolute content path is `C:\gecko_main\input\master-resume\master-resume-v2.txt`. Resolve the repository-relative path from the current `gecko_main` root for every generation, then read the TXT anew. A same-named file elsewhere, cached profile, prior DOCX, or PDF cannot supply resume facts. Missing, unreadable, or empty TXT content stops generation.

The TXT is the only default source for resume facts. The PDF is the only default visual model. Re-read the TXT and verify both files before every generation. Never use an older or previously tailored resume as a content source or formatting starting point, and never silently fall back if either required file is missing. These rules override older source/template instructions unless the user explicitly makes a job-specific exception. The complete controlling text is in `GECKO_SYSTEM.md`.

Do not invent employers, dates, degrees, metrics, certifications, tools, or accomplishments. If a job description requests something not supported by the current master archive, describe it as a gap rather than manufacturing experience.

## Default output

The three-page AI review sample under `output/examples/` is an experiment only.
Never use it as a template or default for future resumes. Keep the standard
two-page section structure; do not add its separate AI & Automation Projects
section unless the user explicitly requests it again. Relevant AI experience
from the canonical master may still be tailored into the existing sections.

Professional Summaries must select job-relevant facts from the current master,
including newer AI, CRM, automation, and e-commerce work when relevant. Vary
the substantive emphasis across postings, even repeated titles. Never publish
the same resume twice: compare normalized visible content and summaries against
saved resumes before publication. Saved documents are duplicate-check inputs
only, never factual sources. Preserve the existing Resume Created = X guard.
Exact byte or text uniqueness alone does not establish meaningful tailoring.
Use a distinct role-relevant summary opening and business focus, select supporting
accomplishments, and reject near-identical visible document content before publication.

When asked to "use Gecko" for a job:

1. Read the job listing.
2. Analyze the job requirements against the master archive.
3. Create a dedicated scratch subfolder: `scratch/{Company-Name}+{JobNumber}/`.
4. Tailor the resume naturally.
5. Produce an exactly two-page DOCX using reusable generators in `scripts/`.
6. Save the resume under `output/resumes/`.
7. After the final resume has been created and validated successfully, add or update the job in the canonical Google Sheet with `scripts/manage_job_tracker.py`.

### Permanent resume content structure

- Every generated resume must include **CORE STRENGTHS** with at least 8 job-relevant, master-supported entries. Use professional Title Case for every entry and include more than 8 when useful.
- Every generated resume must include **TOOLS & PLATFORMS** with at least 8 job-relevant, master-supported products or platforms. Preserve official brand capitalization and never use generic lowercase capabilities as tool entries.
- Every **PROFESSIONAL EXPERIENCE** job must have one physical header line with `Job Title - Company Name - City, ST` on the left and verified employment dates flush with the right text margin. Use exactly one space around each normal hyphen. Preserve the verified title, company, location, and dates from the master TXT. Use a borderless two-column table with zero cell padding, one bold paragraph/run for the complete left heading, and a right-aligned date paragraph. No manual alignment spaces, hard breaks, tabs, or separate company/location/date lines. Compact verified month names and recover width from indentation before minimal heading-only size adjustments. If both fields cannot fit legibly on one line without overlap, fail validation. Accomplishments follow below.
- Target 3 concise, master-supported accomplishment bullets per **PROFESSIONAL EXPERIENCE** job, chosen for relevance to the job description. Use 2 when a third distinct, useful bullet is unnecessary or when native Microsoft Word pagination requires it. The exactly-two-page limit always takes priority over keeping a third bullet.
- Before the final DOCX is saved, use Gecko's cleanup and validation logic to correct and verify both section counts, canonical capitalization, each complete one-line job header with right-aligned source dates, and removal of lowercase placeholder entries. Word-rendered headings and dates must share one line, with every date at the same right margin. A resume that fails these checks is not final.

### Mandatory pagination validation

- The final DOCX must be exactly two pages when opened or exported by Microsoft Word. A browser, HTML, PDF, or fallback renderer alone is not sufficient proof of DOCX pagination.
- Prefer Microsoft Word COM pagination and confirm both Word's computed page count and the exported PDF page count equal 2.
- Use `scripts/validate_word_native.ps1` as the single authoritative check in every environment. Sandboxed agents always submit requests through that entry point to the permanently available interactive-user bridge; they must never attempt direct Word COM, start or control the Scheduled Task, or ask the user to validate a resume manually. The bridge and its watchdog run hidden under the logged-in Windows user, start automatically at logon, and recover after process failure.
- Standard invocation: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_word_native.ps1 -DocxPath "output\resumes\<resume-file>.docx" -PdfPath "scratch\<Company-Name>+<JobNumber>\word-validation.pdf" -ResultPath "scratch\<Company-Name>+<JobNumber>\validation-status.json"`
- The one-time interactive-user installation command is `scripts\Install-Gecko-Word-Bridge.cmd`. Normal Gecko use must not require rerunning it. Health diagnostics are available through `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-Gecko-Word-Bridge.ps1`; exceptional user-side recovery is `scripts\Restart-Gecko-Word-Bridge.cmd`.
- If bridge validation fails, run/report the health diagnostics once and stop before the tracker update. Do not repeatedly retry Word COM from the sandbox, do not ask the user to perform manual pagination, and do not add a tracker row while validation is `native-pending`.
- If native Word pagination is unavailable, use a conservative layout with substantial bottom-page safety margin, clearly disclose that native validation is unavailable, and do not describe fallback-only pagination as equivalent to Word validation.
- Never add content merely to fill space when doing so risks a third page. An underfilled second page is preferable to a three-page resume.
- If a three-bullet draft runs over two pages, remove the least job-relevant third bullets first and repeat native Word validation after each reduction; do not reduce a displayed job below two bullets solely to make it fit.
- Do not claim the Gecko workflow is fully validated until the actual DOCX has been confirmed as exactly two pages in Microsoft Word.

If the job comes from Indeed, retain the full `jk` as the internal job number and use a short resume identifier in the DOCX name:
`Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`
Name the archived job description:
`<Company-Name>+<jk>.md`

Sanitize `<Company-Name>` using the same Windows-safe rules as the scratch directory.

Keep all temporary files (preview PNGs, PDFs, layout tests) inside `scratch/{Company-Name}+{JobNumber}/`.
All reusable tools and scripts remain in `scripts/`.

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


## OpenClaw application batches

Read `openclaw/application-answers.md` before every application. For job IDs Dave
explicitly asks to apply for, automatically submit complete, verified applications unless
he requests review first. A job needing Dave's attention must not block the rest
of the batch: preserve its draft and exact missing fields as pending, continue
immediately to the next ID, and collect the pending actions for Dave to resolve
when he returns. Use each job's matching tailored resume, never guess required
answers, and update Applied only after employer confirmation with tracker readback.
Resume pending jobs after answers arrive without repeating confirmed submissions.


## Permanent short resume filename rule

Resume filenames must use `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`, ending in a unique numeric identifier of at most five digits (Gecko uses five zero-padded digits). Never put a full posting ID, Indeed jk, UUID, hash, or long numeric job number in a resume filename. Keep filenames at most 150 characters, sanitizing Windows-invalid characters and shortening an excessively long title at a word boundary. Reserve identifiers through `job-scout/resume_naming.py`; do not truncate a source ID or guess uniqueness. Full posting IDs remain in the identity registry and DOCX metadata for job matching. Use the same rule for explicitly requested renames, verify tracker links after any rename, and preserve the existing Resume Created = X guard. Archived job descriptions and scratch folders continue to use full posting IDs.

Example: `Dave-Call+Array+Digital-Marketing-Manager+00001.docx`.


Full current rows and formulas: `job-scout/data/tracker-live.json`.
The SQLite `google_tracker_rows` table contains the same complete job mirror.
