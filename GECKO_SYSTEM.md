# Gecko Operating Specification

## Purpose

Gecko discovers and stores relevant jobs, customizes Dave Call's resume for selected postings, generates the finished document, and tracks the job and application while preserving factual accuracy, a natural voice, and the established resume format.

## Execution policy

Requested Gecko work uses the live write path by default. Implement the change, run the affected canonical workflow, and expose the actual generated files and configured Google Sheet results. Do not replace authorized execution with a dry run, preview, simulation, mock, or a list of instructions, and do not stop after code edits when a live run is needed for completion. Keep explicit `--dry-run`, validation, audit, and other intentionally read-only commands available for users who request them.

The request authorizes only its necessary in-scope writes, including resume generation and Gecko-managed tracker updates. It never authorizes applying to jobs, marking `Applied`, sending messages, purchases, unrelated changes, destructive operations, or bypassing access controls. Preserve every eligibility rule, exclusion (including Cost `x`), duplicate safeguard, protected field, and unrelated value. Verify generated artifacts on disk and read every affected tracker cell back after a live write, including resolving the Resume Link to the generated file. Report exact blockers and partial changes; never report live success without read-back verification or ask for redundant confirmation.

## Resume rules

- **Permanent content and format authorities:** Every tailored resume must use `input/master-resume/Dave-Call-Resume.txt` as its only factual content source and `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as its required visual formatting and layout model. These repository-relative paths are the defaults for every manual, queued, and Job Scout generation run.
- Re-read the master TXT for every generation or customization. Do not use a previously generated resume, project note, older DOCX/PDF, or job-specific generator as a source of claims, wording, accomplishments, metrics, skills, tools, education, or certifications. User-supplied facts may be used only when the user explicitly provides them for that specific resume.
- Follow the model PDF as closely as practical for its two-page US Letter layout, centered header structure, EB Garamond typography, font sizing, compact margins, olive section headings and rules, section spacing, section hierarchy, bullet treatment, alignment, density, and overall professional appearance. Content may be tailored and reordered, but the model PDF remains the visual authority.
- The required section hierarchy is: Professional Summary; Core Strengths; Selected Results; Professional Experience; Tools & Platforms; Education & Certifications. **Core Strengths and Tools & Platforms are mandatory and may never be omitted.** Another section may be omitted only when the authoritative master has no supported content for it or two-page pagination requires a conservative reduction.
- **Core Strengths standard:** Every resume must contain at least 8 job-relevant, master-supported Core Strengths; include more when useful. Every entry must use professional Title Case with significant words capitalized. Do not use lowercase placeholders or move product/platform names into this capability section merely to reach the minimum.
- **Professional Experience hierarchy:** Every job must use three levels in this exact order: line 1 is the job title alone; line 2 is `Company Name  City, State` (two spaces between company and location); line 3 and below contain the description/accomplishment bullets. Never use the legacy `Job Title | Company  City` combination. Apply this to every job while preserving the separate blank right-side date cell/area required by the model.
- **Tools & Platforms standard:** Every resume must contain at least 8 job-relevant, master-supported tools or platforms; include more when useful. Use professional capitalization and official brand capitalization (for example, Google Ads, Google Analytics 4, Looker Studio, ChatGPT). Do not use generic lowercase capabilities such as `automation`, `e-commerce`, `forecasting`, `crm`, or `ai` as tool entries; place supported broader capabilities under Core Strengths instead.
- Before a candidate DOCX can replace or become the final resume, auto-normalize its Core Strengths and Tools & Platforms from the master-supported canonical catalogs, then validate: both mandatory sections exist and contain at least 8 entries; their capitalization is canonical; every job uses the required two-line title/company-location hierarchy; no `Job Title | Company` header remains; and no lowercase placeholder-style entries remain. Correct failures before final save and run the same structural checks again during QA.
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
- White background.
- Use the model's 10.5 pt EB Garamond body typography by default; only make conservative job-specific spacing adjustments that preserve the model's hierarchy and Word-native two-page requirement.
- 1.15 line spacing.
- Maintain clean spacing after the header and before sections/jobs.
- Preserve the right-side date cell/space while removing visible date text from job entries.
- Remove table borders from final output.
- Avoid excessive white space on page 2.
- Use as much of the two pages as reasonably possible with relevant content.
- Keep the header identity and contact information consistent with the current approved resume/template.
- End the header contact line with `linkedin.com/in/mdavidcall`; never include `Spanish: Fluent` or any other language-proficiency text in the header.
- Keep language concise, professional, and human.

## Tailoring rules

- Prioritize experience and tools that map to the target role.
- Reorder or tighten bullets when necessary.
- Do not copy the job description verbatim.
- Do not repeatedly mention the employer being applied to.
- Avoid buzzword stuffing.
- Preserve Dave's voice.
- Make tailoring subtle enough that the resume does not look machine-generated.
- Do not create unsupported achievements.

## Factual source

`input/master-resume/Dave-Call-Resume.txt` is the single source of truth for work history, accomplishments, metrics, skills, tools, education, certifications, AI tools, and leadership. It is a comprehensive career archive, not a page-limited resume; tailor from it down to exactly two pages. The required formatting authority is `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`; its content is never evidence unless independently supported by the master TXT.

## Job tracker

Google Sheets is the canonical job tracker. Do not create or update a local Excel job tracker. Every successful Gecko resume generation must end by recording the job with `scripts/manage_job_tracker.py`.

- Add the tracker row only after the final DOCX exists and has passed its required validation.
- Pass the final resume and archived job description to the script's `add` command.
- Let the script derive the next Resume #/Index from the live Sheet and upsert by unique Job Number.
- Preserve all existing rows and the user's manual `Applied` and `Contacted` values.
- Leave compensation or other unavailable listing fields blank; never infer or invent them.
- Treat the tracker update as required for completion. If it fails, report the failure and do not claim the Gecko job is fully complete.
- If Google Sheets is unavailable, report the error without falling back to a local tracker; keep the generated resume.
- Job Scout searches, daily runs, selections, and completed-resume updates use the same Google Sheets integration.
- Preserve user formatting and manual fields. Update only specific managed cell values; never recreate tabs, reorder rows, clear populated ranges, reset filters or conditional formatting, or overwrite Applied/Contacted.
- After the resume queue, Daily Job Scout uses the separate reusable Gmail checker with only `gmail.readonly` access. It may write only conservative employer-response summaries to the matching `Job Scout` `Response` cell. Gmail failures are reported and logged without failing discovery or resume creation.

### Daily all-source apply and resume behavior

`python job-scout/scout.py daily` is the complete workflow and automatically invokes the canonical queue implementation after discovery and Sheet synchronization. It evaluates all existing `Job Scout` rows across every source. Based only on `Location` and `Work Arrangement`, Column F (`Apply?`) is set to `Yes` for every Utah job (on-site, hybrid, or remote) and every job that explicitly allows remote work. Blank or unspecified work arrangements are not remote. Apply? values on all other jobs remain unchanged.

The queue resolves exact, unambiguous headers on the configured intake worksheet. Its current mapping is F `Apply?`, G `Resume Created`, I `Cost`, and Q `Resume Link`; future column movement is safe because reads and writes use headers. A row whose Cost is `x` after trimming and case normalization is excluded from both creation and recreation. `Apply? = yes` with blank Resume Created creates a resume. `Apply? = yes`, `Resume Created = X`, and blank or whitespace Resume Link recreates the resume from the current master TXT and current model PDF; the existing X does not block repair. `Resume Created = X` with a nonblank valid link is idempotently skipped.

After the exact DOCX under `output/resumes` passes structural and Word-native two-page validation, write `Resume Created = X`, a clickable absolute file-URI link to that DOCX in Resume Link, and the normal `Resume Created` Gecko Status without downgrading later application statuses. The shared writer must verify the saved DOCX, create the URL with `Path.resolve().as_uri()`, and store the complete `file:///` URL directly as Column Q's visible value; `HYPERLINK` formulas and `Open Resume` display text are prohibited. Preserve existing resume files; when replacement is necessary, create a versioned filename with the job number still last. If generation, validation, or link creation fails, a new row remains unmarked, a repair row keeps its existing X, Resume Link stays blank, and the retryable failure is written to `Notes` rather than `Cost`. Never upload resumes to Google Drive, mark Applied, or submit an application.

Daily column mapping: F = `Apply?`; G = `Resume Created`; I = `Cost` (`x` excludes); Q = `Resume Link` (clickable absolute file URI under `output/resumes`).

## Filename rules

Resume:
`Dave-Call+<Company-Name>+<Job-Title>+<job-number>.docx`

Archived job description:
`<Company-Name>+<job-number>.md`

Indeed:
Use the job listing's `jk` value as `<job-number>`.

Sanitize `<Company-Name>` for Windows filenames by replacing spaces with hyphens and removing invalid characters (`\ / : * ? " < > |`).
Sanitize `<Job-Title>` the same way. Keep `<job-number>` last so tracker matching remains stable.

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

Use the current master archive (`input/master-resume/Dave-Call-Resume.txt`) as the sole factual source and the required model PDF (`input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`) as the sole default visual authority. The model's content is never evidence unless confirmed in the master archive. No older or generated resume may substitute for either required file.
