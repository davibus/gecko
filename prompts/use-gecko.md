# Standard Gecko Prompt

Use Gecko for this job.

Job listing/source:
[PASTE JOB URL OR JOB DESCRIPTION HERE]

Instructions:
- Read `GECKO_SYSTEM.md` and `AGENTS.md` first.
- Execute the requested workflow live by default: generate the real resume, perform the necessary managed tracker writes, and verify the saved file and affected cells by reading them back. Use dry-run or preview modes only when I explicitly request read-only behavior; do not ask me to reconfirm writes already authorized here.
- Use only `input/master-resume/Dave-Call-Resume.txt` for resume facts and use `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as the required visual formatting/layout model. Stop if either file is missing; never fall back to an older or tailored resume.
- Run `python scripts/gecko_v2.py plan` on the archived listing before changing the resume. Review supported, review, and gap items and the source quotes in the plan.
- Create a dedicated scratch subfolder: `scratch/{Company-Name}+{JobNumber}/` for all temporary files (previews, PNGs, PDFs, intermediate files). Sanitize company names for Windows filenames.
- Reusable tools and scripts reside in `scripts/`.
- Tailor the resume subtly and naturally to this role.
- Generate from the V2 plan with `python scripts/gecko_v2.py generate`; review the rendered resume and `v2-qa.json`. Resolve QA failures before finalizing.
- Keep it exactly two pages.
- Preserve Gecko formatting conventions.
- Require at least 8 master-supported, job-relevant Core Strengths in professional Title Case and at least 8 master-supported, job-relevant Tools & Platforms with official brand capitalization.
- Format every Professional Experience job with the title alone on line 1 and `Company Name  City, State` on line 2; never use `Job Title | Company`.
- Run Gecko's structural cleanup/validation before final save and correct any section-count, capitalization, job-hierarchy, combined-header, or lowercase-placeholder failure.
- Remove visible job dates but preserve the right-side date space.
- Save the finished DOCX in `output/resumes/` using Gecko filename rules: `Dave-Call+<Company-Name>+<Job-Title>+<job-number>.docx`.
- Save the archived listing in `input/job-descriptions/` as `<Company-Name>+<job-number>.md`.
- Only after the final resume has been successfully created and validated, upsert the job in the canonical Google Sheet with `scripts/manage_job_tracker.py add`, then validate the tracker. Do not create or update a local Excel tracker. Preserve existing rows and manual Applied/Contacted values.
