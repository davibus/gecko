# Gecko Workflow

## Optional upstream Job Scout

Job Scout is separate from resume generation. Each morning, run `python job-scout/scout.py daily`. The Job Scout worksheet remains a cumulative history, but the daily path appends only genuinely new jobs and its review output contains only qualifying jobs first discovered in that run. Existing worksheet rows and manual `Applied` / `Contacted` fields are preserved. The command never creates a resume or starts a handoff.

To proceed with a listing, explicitly run `python job-scout/scout.py select <ID>`. Selection archives the description in `input/job-descriptions/`; it does not create a resume or application-tracker row. Continue with the unchanged workflow below only after choosing a job. Full setup and commands are in `job-scout/README.md`.

## New job

1. Read and extract the job details from the job URL or copied listing.
2. Save or paste the captured job description into `input/job-descriptions/{Company-Name}+{JobNumber}.md`.
3. Create a dedicated scratch subfolder for the job: `scratch/{Company-Name}+{JobNumber}/`
   - Sanitize the company name for Windows filenames by replacing spaces with hyphens and removing invalid filename characters (`\ / : * ? " < > |`).
   - All job-specific temporary files must live inside this subfolder (preview PNGs, test PDFs, layout verification images, intermediate files).
   - Do not place new job-specific temporary files directly in the root `scratch/` folder.
4. Verify all claims against the master resume (`input/master-resume/dcall-resume-3-15-26.pdf`).
5. Tailor the resume subtly and generate the two-page DOCX resume under `output/resumes/Dave-Call+{Company-Name}+{JobNumber}.docx` using the reusable generator in `scripts/`.
6. Generate the comprehensive Match Score report under `output/match-reports/Dave-Call+{Company-Name}+{JobNumber}.md`.
7. Verify page count and layout with `scripts/validate_word_native.ps1`; sandbox executions are handed automatically to the interactive Word bridge. Install the bridge once from the normal desktop with `scripts/Install-Gecko-Word-Bridge.cmd`. Keep Word/PDF validation artifacts inside the job's scratch subfolder (`scratch/{Company-Name}+{JobNumber}/`).
8. Only after the final resume and match report have both been created and validated, append the job to the persistent tracker:
   `python scripts/manage_job_tracker.py add --resume "output/resumes/Dave-Call+{Company-Name}+{JobNumber}.docx" --match-report "output/match-reports/Dave-Call+{Company-Name}+{JobNumber}.md" --job-description "input/job-descriptions/{Company-Name}+{JobNumber}.md"`
9. Run `python scripts/manage_job_tracker.py validate`. A Gecko job is not complete until the tracker update and validation succeed.

## Quality checklist

- Exactly two pages, including no trailing blank or near-blank page
- No invented experience
- Natural wording
- Strong job-specific emphasis
- Appropriate ATS terms
- Correct filename: `Dave-Call+{Company-Name}+{JobNumber}.docx`
- Match Score included in `output/match-reports/Dave-Call+{Company-Name}+{JobNumber}.md`
- Archived listing saved as `input/job-descriptions/{Company-Name}+{JobNumber}.md`
- No visible job-date text (preserve date spacing)
- No page overflow or excessive empty blocks
- All temporary artifacts contained within `scratch/{Company-Name}+{JobNumber}/`
- All reusable scripts maintained in `scripts/`
- Job recorded once in `output/job-tracker.xlsx`, after both final deliverables were successfully created
- Existing tracker rows and manual `Applied` / `Contacted` entries preserved
