# Standard Gecko Prompt

Use Gecko for this job.

Job listing/source:
[PASTE JOB URL OR JOB DESCRIPTION HERE]

Instructions:
- Read `GECKO_SYSTEM.md` and `AGENTS.md` first.
- Use the master resume in `input/master-resume/` as the factual source.
- Create a dedicated scratch subfolder: `scratch/{Company-Name}+{JobNumber}/` for all temporary files (previews, PNGs, PDFs, intermediate files). Sanitize company names for Windows filenames.
- Reusable tools and scripts reside in `scripts/`.
- Tailor the resume subtly and naturally to this role.
- Keep it exactly two pages.
- Preserve Gecko formatting conventions.
- Remove visible job dates but preserve the right-side date space.
- Create the Match Score report.
- Save the finished DOCX in `output/resumes/` using Gecko filename rules: `Dave-Call+<Company-Name>+<job-number>.docx`.
- Save the match report in `output/match-reports/` as `Dave-Call+<Company-Name>+<job-number>.md`.
- Save the archived listing in `input/job-descriptions/` as `<Company-Name>+<job-number>.md`.
