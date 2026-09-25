# Standard Gecko Prompt

Use Gecko for this job.

Job listing/source:
[PASTE JOB URL OR JOB DESCRIPTION HERE]

Instructions:
- Read `GECKO_SYSTEM.md` and `AGENTS.md` first.
- Use only `input/master-resume/Dave-Call-resume-9-23-26.docx` for resume facts. The older PDF is not a source, and `Dave_Call_Resume_5ec9726395344311.docx` is for formatting only.
- Run `python scripts/gecko_v2.py plan` on the archived listing before changing the resume. Review supported, review, and gap items and the source quotes in the plan.
- Create a dedicated scratch subfolder: `scratch/{Company-Name}+{JobNumber}/` for all temporary files (previews, PNGs, PDFs, intermediate files). Sanitize company names for Windows filenames.
- Reusable tools and scripts reside in `scripts/`.
- Tailor the resume subtly and naturally to this role.
- Generate from the V2 plan with `python scripts/gecko_v2.py generate`; review the rendered resume and `v2-qa.json`. Resolve QA failures before finalizing.
- Keep it exactly two pages.
- Preserve Gecko formatting conventions.
- Remove visible job dates but preserve the right-side date space.
- Create the Match Score report.
- Save the finished DOCX in `output/resumes/` using Gecko filename rules: `Dave-Call+<Company-Name>+<Job-Title>+<job-number>.docx`.
- Save the match report in `output/match-reports/` as `Dave-Call+<Company-Name>+<job-number>.md`.
- Save the archived listing in `input/job-descriptions/` as `<Company-Name>+<job-number>.md`.
- Only after the final resume and match report have both been successfully created and validated, upsert the job in the canonical Google Sheet with `scripts/manage_job_tracker.py add`, then validate the tracker. Do not create or update a local Excel tracker. Preserve existing rows and manual Applied/Contacted values.
