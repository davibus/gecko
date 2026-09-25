# Gecko Operating Specification

## Purpose

Gecko customizes Dave Call's resume for individual job postings while preserving factual accuracy, a natural voice, and the established resume format.

## Resume rules

- Exactly two pages, with no trailing blank or near-blank page.
- Pagination must be verified against the actual DOCX in Microsoft Word. Fallback HTML/PDF rendering is not authoritative because its line wrapping and pagination can differ from Word.
- The preferred validation requires both Microsoft Word's computed page count and its exported PDF to equal exactly 2.
- Always run native validation through `scripts/validate_word_native.ps1`. When Gecko is running under the isolated Codex account, this script automatically hands the request to the interactive-user Word validation bridge.
- The interactive bridge is installed once by running `scripts/Install-Gecko-Word-Bridge.cmd` from the normal Windows desktop session. Do not repeatedly retry Word COM from the sandbox when the bridge is unavailable.
- When Word automation is unavailable, keep a substantial page-bottom safety margin, report the validation limitation explicitly, and never call fallback-only pagination fully validated.
- Never trade pagination reliability for page fill. A safely underfilled second page is better than a third page.
- White background.
- 11 pt body font.
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

`input/master-resume/Dave-Call-resume-9-23-26.docx` is the single source of truth for work history, accomplishments, metrics, skills, tools, education, certifications, AI tools, and leadership. Re-read it for each job; never inherit facts from an older generated resume or from this specification. The older PDF is not a content source. `Dave_Call_Resume_5ec9726395344311.docx` may guide formatting only.

## Match report

Every Gecko job analysis should include:

- Match Score: X/100
- Strongest alignment areas
- Weaknesses or missing requirements
- ATS keyword alignment
- Recommended resume emphasis
- Interview/application considerations

The score should reflect the evidence in the resume and the job description, not optimism.

## Job tracker

Google Sheets is the canonical job tracker. Do not create or update a local Excel job tracker. Every successful Gecko resume generation must end by recording the job with `scripts/manage_job_tracker.py`.

- Add the tracker row only after the final DOCX and final match report both exist and have passed their required validation.
- Pass the final resume, match report, and archived job description to the script's `add` command.
- Let the script derive the next Resume #/Index from the live Sheet and upsert by unique Job Number.
- Preserve all existing rows and the user's manual `Applied` and `Contacted` values.
- Leave compensation or other unavailable listing fields blank; never infer or invent them.
- Treat the tracker update as required for completion. If it fails, report the failure and do not claim the Gecko job is fully complete.
- If Google Sheets is unavailable, report the error without falling back to a local tracker; keep the generated resume and match report.
- Job Scout searches, daily runs, selections, and completed-resume updates use the same Google Sheets integration.
- Preserve user formatting and manual fields. Update only specific managed cell values; never recreate tabs, reorder rows, clear populated ranges, reset filters or conditional formatting, or overwrite Applied/Contacted.

## Filename rules

Resume:
`Dave-Call+<Company-Name>+<Job-Title>+<job-number>.docx`

Match report:
`Dave-Call+<Company-Name>+<job-number>.md`

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

Use the current master DOCX as the sole factual source. Any resume designated as a formatting reference may guide visual layout only; its content is never evidence unless confirmed in the master DOCX.
