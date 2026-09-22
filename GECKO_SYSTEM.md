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

## Relevant tools to include when appropriate

- Codex
- ChatGPT
- Claude
- Perplexity
- Cursor
- AntiGravity

These are especially appropriate for marketing operations, analytics, automation, code-assisted workflows, content development, reporting, and technical troubleshooting.

## Senior responsibility metric

When relevant and natural, include:
- Managed $30 million per month with a team of 4.

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

Every successful Gecko resume generation must end by recording the job with `scripts/manage_job_tracker.py`. When `TRACKER_BACKEND=google-sheets`, Google Sheets is the primary live tracker and `output/job-tracker.xlsx` remains a required migration backup.

- Add the tracker row only after the final DOCX and final match report both exist and have passed their required validation.
- Pass the final resume, match report, and archived job description to the script's `add` command.
- Let the script assign the next sequential Resume # and reject duplicate Job Number entries.
- Preserve all existing rows and the user's manual `Applied` and `Contacted` values.
- Leave compensation or other unavailable listing fields blank; never infer or invent them.
- Treat the tracker update as required for completion. If it fails, report the failure and do not claim the Gecko job is fully complete.
- During dual-write migration, a tracker update is complete only after both the XLSX backup and Google Sheets synchronization succeed.
- Preserve user-maintained `Applied` and `Contacted` values from Google Sheets and mirror them into the XLSX backup during synchronization.
- Job Scout searches, daily runs, selections, and completed-resume updates must synchronize Google Sheets when the Google backend is enabled.
- Treat `output/job-tracker.xlsx` as a persistent user-managed workbook: load and modify it in place, never delete/recreate worksheets or rebuild existing rows, and never blanket-restyle existing cells.
- Preserve user formatting and workbook features, including fills, fonts, borders, number formats, alignment, row heights, column widths, frozen panes, filters/sort state where possible, Excel Tables, conditional formatting, data validation, hyperlinks, and formulas. Append new rows by copying the previous data row's formatting and expanding existing table/filter/validation ranges.
- Treat the live Google worksheets the same way during routine synchronization: update values in place, never clear and rebuild a populated sheet, never blanket-apply Gecko's default formatting, and never replace an existing filter without carrying forward its criteria. Preserve physical row order so row-specific formatting stays attached to the same job.

## Filename rules

Resume:
`Dave-Call+<Company-Name>+<job-number>.docx`

Match report:
`Dave-Call+<Company-Name>+<job-number>.md`

Archived job description:
`<Company-Name>+<job-number>.md`

Indeed:
Use the job listing's `jk` value as `<job-number>`.

Sanitize `<Company-Name>` for Windows filenames by replacing spaces with hyphens and removing invalid characters (`\ / : * ? " < > |`).

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

Use the master resume as the factual baseline. If another resume/template is added to the project and explicitly designated as the formatting reference, use it for visual layout only unless instructed otherwise.
