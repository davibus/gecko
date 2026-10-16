# Gecko Operating Specification

The canonical project name is **Gecko Main** and the canonical directory is `gecko_main`. Use this name and directory in all new scripts, documentation, commands, paths, and configuration. See `AGENTS.md` for the deprecated-name rule.

## Purpose

Gecko discovers and stores relevant jobs, customizes Dave Call's resume for selected postings, generates the finished document, and tracks the job and application while preserving factual accuracy, a natural voice, and the established resume format.

## Execution policy

Requested Gecko work uses the live write path by default. Implement the change, run the affected canonical workflow, and expose the actual generated files and configured Google Sheet results. Do not replace authorized execution with a dry run, preview, simulation, mock, or a list of instructions, and do not stop after code edits when a live run is needed for completion. Keep explicit `--dry-run`, validation, audit, and other intentionally read-only commands available for users who request them.

The request authorizes only its necessary in-scope writes, including resume generation and Gecko-managed tracker updates. It never authorizes applying to jobs, marking `Applied`, sending messages, purchases, unrelated changes, destructive operations, or bypassing access controls. Preserve every eligibility rule, exclusion (including Cost `x`), duplicate safeguard, protected field, and unrelated value. Verify generated artifacts on disk and read every affected tracker cell back after a live write, including resolving the Resume Link to the generated file. Report exact blockers and partial changes; never report live success without read-back verification or ask for redundant confirmation.

## Resume rules

- The three-page AI sample under `output/examples/` is experiment-only and must not guide future resume layout or section structure. Continue using the standard two-page format without a separate AI & Automation Projects section unless explicitly requested again. Tailor relevant master-supported AI experience within the existing sections.

- Tailor the Professional Summary using job-relevant, source-checked facts from the current master, including newer AI, CRM, automation, and e-commerce experience when relevant. Select different substantive evidence across repeated postings rather than reusing a fixed paragraph. Check normalized summary and full visible document content against saved resumes before publication; reject duplicates. Saved resumes supply no facts. Existing Resume Created = X rows remain protected.

- **Permanent content and format authorities:** Every tailored resume must use `input/master-resume/master-resume-v2.txt` as its only factual content source and `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as its required visual formatting and layout model. These repository-relative paths are the defaults for every manual, queued, and Job Scout generation run.
- In this checkout, the factual authority resolves to `C:\gecko_main\input\master-resume\master-resume-v2.txt`. Resolve it from the current project root and read it for each new generation. A matching filename outside this path, compact screening profile, prior DOCX, or PDF is not an alternate content source. Stop with a clear error if the TXT is missing, unreadable, or empty.
- Re-read the master TXT for every generation or customization. Do not use a previously generated resume, project note, older DOCX/PDF, or job-specific generator as a source of claims, wording, accomplishments, metrics, skills, tools, education, or certifications. User-supplied facts may be used only when the user explicitly provides them for that specific resume.
- Follow the model PDF as closely as practical for its two-page US Letter layout, centered header structure, EB Garamond typography, font sizing, compact margins, olive section headings and rules, section spacing, section hierarchy, bullet treatment, alignment, density, and overall professional appearance. Content may be tailored and reordered, but the model PDF remains the visual authority.
- The required section hierarchy is: Professional Summary; Core Strengths; Selected Results; Professional Experience; Tools & Platforms; Education & Certifications. **Core Strengths and Tools & Platforms are mandatory and may never be omitted.** Another section may be omitted only when the authoritative master has no supported content for it or two-page pagination requires a conservative reduction.
- **Core Strengths standard:** Every resume must contain at least 8 job-relevant, master-supported Core Strengths; include more when useful. Every entry must use professional Title Case with significant words capitalized. Do not use lowercase placeholders or move product/platform names into this capability section merely to reach the minimum.
- **Professional Experience hierarchy:** Every job has one physical header line with `Job Title - Company Name - City, ST` on the left and verified employment dates flush with the right text margin. Use one normal hyphen and one space on each side between fields. Preserve the unchanged verified title, company, location, and dates from the master TXT. Use a borderless two-column table with zero cell padding, a single bold left-heading paragraph/run, and a right-aligned date paragraph; never align dates with manual spaces. Compact verified month names and recover usable width before minimal heading-only size adjustments. Fail validation if either field wraps or overlaps. Accomplishment bullets follow below. This employment-header instruction supersedes the model PDF wherever its header treatment differs.
- **Professional Experience bullet count:** Target 3 concise, master-supported accomplishment bullets per job, ranked for relevance to the target job description. Use 2 when a third distinct, useful bullet is not warranted or when native Microsoft Word pagination requires the reduction. Never retain a third bullet at the cost of exceeding exactly two pages; the two-page limit has priority.
- **Tools & Platforms standard:** Every resume must contain at least 8 job-relevant, master-supported tools or platforms; include more when useful. Use professional capitalization and official brand capitalization (for example, Google Ads, Google Analytics 4, Looker Studio, ChatGPT). Do not use generic lowercase capabilities such as `automation`, `e-commerce`, `forecasting`, `crm`, or `ai` as tool entries; place supported broader capabilities under Core Strengths instead.
- Before a candidate DOCX can replace or become the final resume, auto-normalize its Core Strengths and Tools & Platforms from the master-supported canonical catalogs, then validate: both mandatory sections exist and contain at least 8 entries; their capitalization is canonical; every job has the complete one-line title/company/location heading and right-aligned source dates on that same physical line; and no lowercase placeholder-style entries remain. Correct failures before final save and check rendered lines again during Word-native QA.
- These two authorities override every older Gecko instruction that names another master resume, formatting PDF, DOCX template, or tailored resume as a starting point. Deviate only when the user explicitly instructs Gecko to do so for one specific resume.
- Before planning or generation, verify that both required files exist. If either is missing, stop with a clear error identifying the missing required Gecko master resume or formatting model. Never fall back to another resume or template.
- Exactly two pages, with no trailing blank or near-blank page.
- Pagination must be verified against the actual DOCX in Microsoft Word. Fallback HTML/PDF rendering is not authoritative because its line wrapping and pagination can differ from Word.
- The preferred validation requires both Microsoft Word's computed page count and its exported PDF to equal exactly 2.
- Always run native validation through `scripts/validate_word_native.ps1`, the sole Word-pagination implementation and authoritative entry point. Sandboxed agents submit validation requests to the hidden interactive-user bridge and must never automate Word directly or ask the user to validate a resume manually.
- The interactive bridge is installed once with `scripts\Install-Gecko-Word-Bridge.cmd`. Its Windows Scheduled Task and hidden watchdog start at interactive-user logon, survive reboots, restart after failure, maintain a tolerant heartbeat, and continuously process sequential requests. Normal Gecko use must not require manually starting the bridge.
- If validation cannot reach the bridge, report `scripts\Test-Gecko-Word-Bridge.ps1` diagnostics rather than repeatedly retrying Word COM from the sandbox. `scripts\Restart-Gecko-Word-Bridge.cmd` is the exceptional user-side recovery command; neither command opens another terminal window when run from the IDE terminal.
- When Word automation is unavailable, keep a substantial page-bottom safety margin, report the validation limitation explicitly, and never call fallback-only pagination fully validated.
- Never trade pagination reliability for page fill. A safely underfilled second page is better than a third page.
- When a three-bullet draft exceeds two pages in native Word, remove the least job-relevant third bullets first, never reducing a displayed job below two bullets solely for page fit, and re-run native validation after each adjustment until Word and the exported PDF both report exactly two pages.
- White background.
- Use 11 pt EB Garamond main text; only make conservative heading-specific size and job-specific spacing adjustments that preserve the model's hierarchy and Word-native two-page requirement.
- 1.15 line spacing.
- Maintain clean spacing after the header and before sections/jobs.
- Display verified employment dates in the right-aligned date cell on the same physical line as each job heading.
- Remove table borders from final output.
- Avoid excessive white space on page 2.
- Use as much of the two pages as reasonably possible with relevant content.
- Keep the header identity and contact information consistent with the current approved resume/template.
- End the header contact line with `linkedin.com/in/mdavidcall`; never include `Spanish: Fluent` or any other language-proficiency text in the header.
- Keep language concise, professional, and human.

## Tailoring rules

- Exact duplicate checks alone are insufficient. A small summary edit must not hide an otherwise identical resume. Use a distinct, source-supported summary opening and business focus, select accomplishments that support that focus, and reject near-identical visible document content. Keep verified work history and the required visual layout consistent.

- Prioritize experience and tools that map to the target role.
- Reorder or tighten bullets when necessary.
- Do not copy the job description verbatim.
- Do not repeatedly mention the employer being applied to.
- Avoid buzzword stuffing.
- Preserve Dave's voice.
- Make tailoring subtle enough that the resume does not look machine-generated.
- Do not create unsupported achievements.

## Factual source

`input/master-resume/master-resume-v2.txt` is the single source of truth for work history, accomplishments, metrics, skills, tools, education, certifications, AI tools, and leadership. It is a comprehensive career archive, not a page-limited resume; tailor from it down to exactly two pages. The required formatting authority is `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`; its content is never evidence unless independently supported by the master TXT.

## Job tracker

Exception for expired Indeed jobs: if `Apply or on Company Website (If Indeed)` equals `This job has expired on Indeed` or `Expired`, ignoring case and surrounding whitespace, normalize the full message to `Expired` and set `Apply?` (or the live `Apply` header) to `No`. Expiration overrides Utah/remote auto-approval and excludes the row from every resume queue. Resolve headers from the current sheet, update only affected non-formula cells, report skips, and verify by readback. Preserve existing resume files, links, and `Resume Created = X`.

The live Gecko Job Tracker tabs, header aliases, protected cells, and report commands are specified in `docs/tracker-schema.md`; `job-scout/tracker_schema.py` is the runtime map. Read live headers by name before tracker work. The current workbook has a five-date vertical dashboard in `Daily Tasks`, run history in `Daily Run`, and an unassigned `Scratch` tab, but no `Daily Reports`, `List of Job Sources`, `Indeed`, or `Job Tracker` tab. `scripts/daily_report.py --dry-run` writes the `Daily Tasks` dashboard and inserts `Daily Run` history at row 3. Do not create or rename tabs implicitly.

All tracker write paths use the current unambiguous header mapping and write only explicitly managed cells. Preserve every custom column, existing formula, and ARRAYFORMULA anchor/output range. Re-read formula state before each write, skip formula-protected cells, and report skipped updates. Do not replace entire rows or clear ranges containing unmanaged cells. Stop sorting, cleanup, deletion, and row movement when formulas cannot be guaranteed to stay with their original jobs. Continue to enforce durable rejection history, raw resume file-URI links, and the Resume Created = X no-recreation rule.

For Source = Indeed, the 'Apply or on Company Website (If Indeed)' field stores the exact visible text of the primary application/status control on the Indeed job page. Examples include 'Apply Now', 'Apply on Company Website', 'Already applied', and 'Job no longer available'. Do not normalize the text. If it cannot be reliably resolved, leave the current value unchanged and continue.

Use the main blue application button first. If it is absent, use the primary visible application-status message in the Indeed job header. URLs, API labels, descriptions, and surrounding page text are not evidence for this field. Resolve the spreadsheet column by its current header name.



Google Sheets is the canonical job tracker. Do not create or update a local Excel job tracker. Every successful Gecko resume generation must end by recording the job with `scripts/manage_job_tracker.py`.

- Add the tracker row only after the final DOCX exists and has passed its required validation.
- Pass the final resume and archived job description to the script's `add` command.
- In the current workbook, match exactly one existing `Job List` row by `ID`, canonical `Job URL`, or Indeed `jk`. Stop without writing if the row cannot be identified uniquely. The legacy Resume #/Index path applies only if its separate application tab exists.
- Preserve all existing rows and the user's manual `Applied` and `Contacted` values.
- Leave compensation or other unavailable listing fields blank; never infer or invent them.
- Treat the tracker update as required for completion. If it fails, report the failure and do not claim the Gecko job is fully complete.
- If Google Sheets is unavailable, report the error without falling back to a local tracker; keep the generated resume.
- Job Scout searches, daily runs, selections, and completed-resume updates use the same Google Sheets integration.
- Preserve user formatting and manual fields. Update only specific managed cell values; never recreate tabs, reorder rows, clear populated ranges, reset filters or conditional formatting, or overwrite Applied/Contacted.
- After the resume queue, Daily Job Scout uses the separate reusable Gmail checker with only `gmail.readonly` access. It may write only conservative employer-response summaries to the matching `Job List` `Response` cell. Gmail failures are reported and logged without failing discovery or resume creation.
- The hidden `Rejected Jobs` support tab is the durable permanent-rejection authority and survives visible-row deletion. Every Job Scout and Indeed Scout insertion or resume-queue path checks it as an additional guard. A source-qualified stable Job ID is the primary key (Indeed uses `jk`); normalized canonical job URL is the fallback. Company + Job Title alone is never a permanent-rejection key.
- Permanently remove a job by setting `Apply?` to `Reject` (or `Delete / Reject`) and running `python job-scout/scout.py reject-jobs`. Daily and Sheet-sync operations also process these markers. Gecko archives and reads back Source, Job ID when available, original and normalized URLs, Company, Job Title, Date Rejected, and Reason or Status before deleting the visible row. A support-write or verification failure leaves the visible row untouched. Ordinary row disappearance is never treated as rejection without a durable prior record.

### Daily all-source apply and resume behavior

`python job-scout/scout.py daily` is the complete workflow and automatically invokes the canonical queue implementation after discovery and Sheet synchronization. It evaluates all existing `Job List` rows across every source. `Apply?` is set to `Yes` when `Location`/`Work Arrangement` proves Utah or explicit remote work and all other eligibility safeguards pass. Blank or unknown Cost does not block approval; `Cost = x` means a confirmed required application fee, forces `Apply? = No`, and excludes resume generation. Unknown location never grants approval. Resolve Cost and approval by their current headers; there is no `Status` column.

The queue resolves exact, unambiguous headers on the configured intake worksheet. Before creating or queuing a resume from any scout, read the existing tracker row by stable identity. If `Resume Created` is `X` after trimming and case normalization, skip generation, preserve the marker and existing link exactly, even when the link is blank, and report a missing link for manual review. A nonblank link with a blank marker also stops generation for manual review. Rediscovery must not reset either state. Cost `x`, including an effective `x` from a protected formula, excludes creation. A qualifying `Apply? = yes` row may create a resume only when both completion fields are blank.

After the exact DOCX under `output/resumes` passes structural and Word-native two-page validation, write `Resume Created = X` and a clickable absolute file-URI link to that DOCX in Resume Link. The shared writer must verify the saved DOCX, create the URL with `Path.resolve().as_uri()`, and store the complete `file:///` URL directly as the `Resume Link` cell value; `HYPERLINK` formulas and `Open Resume` display text are prohibited. If generation, validation, or link creation fails, a new row remains unmarked and the retryable failure is written to `Notes` rather than `Cost`. Never upload resumes to Google Drive, mark Applied, or submit an application.



## Filename rules

Resume:
`Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`

Archived job description:
`<Company-Name>+<job-number>.md`

Indeed:
Use the job listing's `jk` value as `<job-number>`.

Sanitize `<Company-Name>` for Windows filenames by replacing spaces with hyphens and removing invalid characters (`\ / : * ? " < > |`).
Sanitize `<Job-Title>` the same way. Keep the short numeric `<Resume-ID>` last; resolve the full posting ID from the registry or embedded DOCX metadata for tracker matching.

## Scratch directory rules

For each job processed, create a dedicated subfolder:
`scratch/{Company-Name}+{JobNumber}/`

- Sanitize `{Company-Name}` for Windows filenames (replace spaces with hyphens, remove invalid characters like `\ / : * ? " < > |`).
- Store all temporary, intermediate, and validation files inside this folder, including:
  - Resume preview PNGs
  - Generated PDF previews
  - Intermediate DOCX/PDF files
  - Layout-test images
  - Temporary job-specific scratch files
- Do not place new job-specific temporary files directly in the root `scratch/` folder.

## Reusable scripts

All reusable generation, layout optimization, and pagination verification scripts reside in the dedicated root folder:
`scripts/`

- `scripts/` houses reusable Python tools for DOCX building, PDF rendering, layout tuning, and Word COM pagination verification.
- Reusable utilities must never be stored in `scratch/`.

## Source integrity

Use the current master archive (`input/master-resume/master-resume-v2.txt`) as the sole factual source and the required model PDF (`input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`) as the sole default visual authority. The model's content is never evidence unless confirmed in the master archive. No older or generated resume may substitute for either required file.
# Tracker column update — 2026-10-13

In the live Job List, column I is `Last Updated`, the last actual Firecrawl
or Gecko run for that job; column J is `Notes`. Resolve fields by current
unique headers. Preserve existing research and manual notes. Record actual
run date/time in America/Denver with the tool name; never stamp a local pull
or instruction sync as a job run. See AGENTS.md and docs/tracker-schema.md.
The user's Scratch proposals are synced in docs/scratch-column-ideas.md.


## Permanent short resume filename rule

Resume filenames must use `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`, ending in a unique numeric identifier of at most five digits (Gecko uses five zero-padded digits). Never put a full posting ID, Indeed jk, UUID, hash, or long numeric job number in a resume filename. Keep filenames at most 150 characters, sanitizing Windows-invalid characters and shortening an excessively long title at a word boundary. Reserve identifiers through `job-scout/resume_naming.py`; do not truncate a source ID or guess uniqueness. Full posting IDs remain in the identity registry and DOCX metadata for job matching. Use the same rule for explicitly requested renames, verify tracker links after any rename, and preserve the existing Resume Created = X guard. Archived job descriptions and scratch folders continue to use full posting IDs.

Example: `Dave-Call+Array+Digital-Marketing-Manager+00001.docx`.
# Tracker authority update — October 16, 2026

The user has requested SQLite authority for the local dashboard. When
`job-scout/preferences/tracker-backend.json` selects `sqlite`, all ordinary
tracker, queue, resume-completion, and daily-report work uses
`job-scout/data/jobs.sqlite3`. Do not sync the preserved Google Sheet over the
local database. This overrides older Google-Sheets-authoritative statements
in this file. All resume factual, approval, identity, existing-X, and native
Word validation safeguards remain in effect. See `docs/sqlite-workspace.md`.

