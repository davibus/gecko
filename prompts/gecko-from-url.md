# Gecko from Job URL

Use Gecko for this job: https://www.indeed.com/viewjob?jk=b1e13fda0b6ba9cb&from=shareddesktop_copy

Read the listing, identify the job number, archive it, and create the V2 tailoring plan with `scripts/gecko_v2.py plan` before modifying the resume. Review its evidence and gaps, then generate the DOCX and run Word-native QA with `scripts/gecko_v2.py generate`. Generate:
1. The exactly two-page DOCX resume under `output/resumes/Dave-Call+<Company-Name>+<job-number>.docx` using `scripts/`.
2. The Match Score report under `output/match-reports/Dave-Call+<Company-Name>+<job-number>.md`.
3. The archived listing under `input/job-descriptions/<Company-Name>+<job-number>.md`.
4. After items 1-3 are successfully created and `v2-qa.json` reports a native Word QA pass, upsert the job in the canonical Google Sheet with `scripts/manage_job_tracker.py add` and validate the tracker. Do not create or update a local Excel tracker.

Ensure a dedicated scratch subfolder `scratch/{Company-Name}+{JobNumber}/` is created for all temporary files (preview PNGs, PDFs, layout verification images, intermediate files). Sanitize company names for Windows filenames. Reusable tools and scripts reside in `scripts/`.

Follow all rules in `GECKO_SYSTEM.md` and `AGENTS.md`.
