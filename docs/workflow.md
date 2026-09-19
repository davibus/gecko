# Gecko Workflow

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
7. Verify page count and layout using Word/PDF rendering inside the job's scratch subfolder (`scratch/{Company-Name}+{JobNumber}/`).

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
