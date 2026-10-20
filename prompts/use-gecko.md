# Standard Gecko Prompt

Use Gecko for this job.

Job listing/source:
[PASTE JOB URL OR JOB DESCRIPTION HERE]

Instructions:
- Read `GECKO_SYSTEM.md` and `AGENTS.md` first.
- Execute the requested workflow live by default: generate the real resume, perform the necessary managed tracker writes, and verify the saved file and affected cells by reading them back. Use dry-run or preview modes only when I explicitly request read-only behavior; do not ask me to reconfirm writes already authorized here.
- Use only `input/master-resume/master-resume-v4.docx` for resume facts and use `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as the required visual formatting/layout model. Stop if either file is missing; never fall back to an older or tailored resume.
- Run `python scripts/gecko_v2.py plan` on the archived listing before changing the resume. Review supported, review, and gap items and the source quotes in the plan.
- Read the matching live Job Scout row by stable identity before generation. If `Resume Created` is `X` after trimming and case normalization, stop resume generation and preserve its marker and link, even when the link is blank; report a blank link for manual review.
- Create a dedicated scratch subfolder: `scratch/{Company-Name}+{JobNumber}/` for all temporary files (previews, PNGs, PDFs, intermediate files). Sanitize company names for Windows filenames.
- Reusable tools and scripts reside in `scripts/`.
- Tailor the resume subtly and naturally to this role.
- Generate from the V2 plan with `python scripts/gecko_v2.py generate`; review the rendered resume and `v2-qa.json`. Resolve QA failures before finalizing.
- Keep it exactly two pages.
- Preserve Gecko formatting conventions.
- Require at least 8 master-supported, job-relevant Core Strengths in professional Title Case and at least 8 master-supported, job-relevant Tools & Platforms with official brand capitalization.
- Format every Professional Experience job on one physical line as `Job Title - Company Name - City, ST` at left and verified employment dates flush right, with a single space around each normal hyphen. Use verified master DOCX fields and check every rendered line for wrapping or overlap.
- Run Gecko's structural cleanup/validation before final save and correct any section-count, capitalization, single-line employment-header, or lowercase-placeholder failure.
- Show verified employment dates at the right text margin on the same physical line as every job heading.
- Save the finished DOCX in `output/resumes/` using Gecko filename rules: `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`.
- Save the archived listing in `input/job-descriptions/` as `<Company-Name>+<job-number>.md`.
- Only after the final resume has been successfully created and validated, upsert the job in the canonical Google Sheet with `scripts/manage_job_tracker.py add`, then validate the tracker. Do not create or update a local Excel tracker. Preserve existing rows and manual Applied/Contacted values.


## Permanent short resume filename rule

Resume filenames must use `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`, ending in a unique numeric identifier of at most five digits (Gecko uses five zero-padded digits). Never put a full posting ID, Indeed jk, UUID, hash, or long numeric job number in a resume filename. Keep filenames at most 150 characters, sanitizing Windows-invalid characters and shortening an excessively long title at a word boundary. Reserve identifiers through `job-scout/resume_naming.py`; do not truncate a source ID or guess uniqueness. Full posting IDs remain in the identity registry and DOCX metadata for job matching. Use the same rule for explicitly requested renames, verify tracker links after any rename, and preserve the existing Resume Created = X guard. Archived job descriptions and scratch folders continue to use full posting IDs.

Example: `Dave-Call+Array+Digital-Marketing-Manager+00001.docx`.

For each job description, select only relevant, source-supported facts from the version 4 master. The master is a career archive, not content to include in full; keep the established two-page resume format.

Read the version 4 Word master directly for every resume, including paragraphs, tables, and list items. No text export, older master, or cover letter is an alternate factual source. Fill as much of both pages as practical with relevant, distinct, master-supported evidence; never add filler or inflate spacing to fill pages. The master cover letter is reserved for a later explicit request.

## Resume content density

Exactly two pages is necessary but not sufficient when useful, job-relevant evidence remains. Education & Certifications should finish within approximately 0.5 inch (36 points) above the normal bottom text boundary on page two. Use distinct, source-supported accomplishments and relevant project detail, prioritizing the most relevant roles; there is no fixed two- or three-bullet ceiling. Keep standard sections, readable model typography, and normal margins/spacing. Do not fill space with larger fonts, inflated spacing, blank paragraphs, repeated claims, unrelated material, or an education footer/text box. Inspect both rendered pages and measure the final section after native Word/PDF validation. If genuinely relevant evidence is exhausted, document the reviewed evidence and explain the remaining gap; page count alone is not completion.
