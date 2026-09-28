# Gecko Operating Specification

## Purpose

Gecko discovers and stores relevant jobs, customizes Dave Call's resume for selected postings, generates the finished document, and tracks the job and application while preserving factual accuracy, a natural voice, and the established resume format.

## Resume rules

- **Permanent content and format authorities:** Every tailored resume must use `input/master-resume/Dave-Call-Resume.txt` as its only factual content source and `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as its required visual formatting and layout model. These repository-relative paths are the defaults for every manual, queued, and Job Scout generation run.
- Re-read the master TXT for every generation or customization. Do not use a previously generated resume, project note, older DOCX/PDF, or job-specific generator as a source of claims, wording, accomplishments, metrics, skills, tools, education, or certifications. User-supplied facts may be used only when the user explicitly provides them for that specific resume.
- Follow the model PDF as closely as practical for its two-page US Letter layout, centered header structure, EB Garamond typography, font sizing, compact margins, olive section headings and rules, section spacing, section hierarchy, bullet treatment, alignment, density, and overall professional appearance. Content may be tailored and reordered, but the model PDF remains the visual authority.
- The required section hierarchy is: Professional Summary; Core Strengths; Selected Results; Professional Experience; Tools & Platforms; Education & Certifications. Omit a section only when the authoritative master has no supported content for it or two-page pagination requires a conservative reduction.
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
