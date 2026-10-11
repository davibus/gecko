# Standard Gecko Prompt

Use Gecko for this job.

Job listing/source:
[PASTE JOB URL OR JOB DESCRIPTION HERE]

Instructions:
- Read `GECKO_SYSTEM.md` and `AGENTS.md` first.
- Execute the requested workflow live by default: generate the real resume, perform the necessary managed tracker writes, and verify the saved file and affected cells by reading them back. Use dry-run or preview modes only when I explicitly request read-only behavior; do not ask me to reconfirm writes already authorized here.
- Use only `input/master-resume/Dave-Call-Resume.txt` for resume facts and use `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as the required visual formatting/layout model. Stop if either file is missing; never fall back to an older or tailored resume.
- Run `python scripts/gecko_v2.py plan` on the archived listing before changing the resume. Review supported, review, and gap items and the source quotes in the plan.
- Read the matching live Job Scout row by stable identity before generation. If `Resume Created` is `X` after trimming and case normalization, stop resume generation and preserve its marker and link, even when the link is blank; report a blank link for manual review.
- Create a dedicated scratch subfolder: `scratch/{Company-Name}+{JobNumber}/` for all temporary files (previews, PNGs, PDFs, intermediate files). Sanitize company names for Windows filenames.
- Reusable tools and scripts reside in `scripts/`.
- Tailor the resume subtly and naturally to this role.
- Generate from the V2 plan with `python scripts/gecko_v2.py generate`; review the rendered resume and `v2-qa.json`. Resolve QA failures before finalizing.
- Keep it exactly two pages.
- Preserve Gecko formatting conventions.
- Require at least 8 master-supported, job-relevant Core Strengths in professional Title Case and at least 8 master-supported, job-relevant Tools & Platforms with official brand capitalization.
- Format every Professional Experience job on one physical line as `Job Title - Company Name - City, ST` at left and verified employment dates flush right, with a single space around each normal hyphen. Use verified master TXT fields and check every rendered line for wrapping or overlap.
- Run Gecko's structural cleanup/validation before final save and correct any section-count, capitalization, single-line employment-header, or lowercase-placeholder failure.
- Show verified employment dates at the right text margin on the same physical line as every job heading.
- Save the finished DOCX in `output/resumes/` using Gecko filename rules: `Dave-Call+<Company-Name>+<Job-Title>+<job-number>.docx`.
- Save the archived listing in `input/job-descriptions/` as `<Company-Name>+<job-number>.md`.
- Only after the final resume has been successfully created and validated, upsert the job in the canonical Google Sheet with `scripts/manage_job_tracker.py add`, then validate the tracker. Do not create or update a local Excel tracker. Preserve existing rows and manual Applied/Contacted values.
