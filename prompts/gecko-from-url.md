# Gecko from Job URL

Use Gecko for this job: "put job URL here"

Execute this workflow live by default. Generate the real resume, make the necessary Gecko-managed tracker updates, and verify the saved file and affected cells by reading them back. Do not substitute a dry run or ask for redundant confirmation.

Read the listing, identify the job number, archive it, and create the V2 tailoring plan with `scripts/gecko_v2.py plan` before modifying the resume. Review its evidence and gaps, then generate the DOCX and run Word-native QA with `scripts/gecko_v2.py generate`. Generate:
Before generation, read the matching live Job Scout row by stable identity. A normalized `Resume Created = X` stops generation and preserves its marker and link, even when the link is blank; report a blank link for manual review.
1. The exactly two-page DOCX resume under `output/resumes/Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx` using `scripts/`.
2. The archived listing under `input/job-descriptions/<Company-Name>+<job-number>.md`.
3. After items 1-2 are successfully created and `v2-qa.json` reports a native Word QA pass, upsert the job in the canonical Google Sheet with `scripts/manage_job_tracker.py add` and validate the tracker. Do not create or update a local Excel tracker.

Ensure a dedicated scratch subfolder `scratch/{Company-Name}+{JobNumber}/` is created for all temporary files (preview PNGs, PDFs, layout verification images, intermediate files). Sanitize company names for Windows filenames. Reusable tools and scripts reside in `scripts/`.

Follow all rules in `GECKO_SYSTEM.md` and `AGENTS.md`.
This includes the permanent minimum of 8 professionally capitalized Core Strengths, 8 officially capitalized Tools & Platforms, and a complete one-physical-line `Job Title - Company Name - City, ST` heading for every Professional Experience entry. Verified employment dates must align flush right on that same physical line; Gecko V2 Word QA rejects wrapped or overlapping fields.


## Permanent short resume filename rule

Resume filenames must use `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`, ending in a unique numeric identifier of at most five digits (Gecko uses five zero-padded digits). Never put a full posting ID, Indeed jk, UUID, hash, or long numeric job number in a resume filename. Keep filenames at most 150 characters, sanitizing Windows-invalid characters and shortening an excessively long title at a word boundary. Reserve identifiers through `job-scout/resume_naming.py`; do not truncate a source ID or guess uniqueness. Full posting IDs remain in the identity registry and DOCX metadata for job matching. Use the same rule for explicitly requested renames, verify tracker links after any rename, and preserve the existing Resume Created = X guard. Archived job descriptions and scratch folders continue to use full posting IDs.

Example: `Dave-Call+Array+Digital-Marketing-Manager+00001.docx`.

## Resume content density

Exactly two pages is necessary but not sufficient when useful, job-relevant evidence remains. Education & Certifications should finish within approximately 0.5 inch (36 points) above the normal bottom text boundary on page two. Use distinct, source-supported accomplishments and relevant project detail, prioritizing the most relevant roles; there is no fixed two- or three-bullet ceiling. Keep standard sections, readable model typography, and normal margins/spacing. Do not fill space with larger fonts, inflated spacing, blank paragraphs, repeated claims, unrelated material, or an education footer/text box. Inspect both rendered pages and measure the final section after native Word/PDF validation. If genuinely relevant evidence is exhausted, document the reviewed evidence and explain the remaining gap; page count alone is not completion.
