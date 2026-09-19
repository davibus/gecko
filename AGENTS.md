# AntiGravity Project Instructions — Gecko

You are working inside the Gecko resume-customization project.

Always read `GECKO_SYSTEM.md` before performing resume work.

## Source of truth

The default source resume is:
`input/master-resume/dcall-resume-3-15-26.pdf`

Do not invent employers, dates, degrees, metrics, certifications, tools, or accomplishments. If a job description requests something not supported by the source resume or explicit project notes, describe it as a gap rather than manufacturing experience.

## Default output

When asked to "use Gecko" for a job:

1. Read the job listing.
2. Analyze fit.
3. Create a dedicated scratch subfolder: `scratch/{Company-Name}+{JobNumber}/`.
4. Tailor the resume naturally.
5. Produce an exactly two-page DOCX using reusable generators in `scripts/`.
6. Produce a Match Score report.
7. Save the resume under `output/resumes/`.
8. Save the match report under `output/match-reports/`.
9. After both final files have been created and validated successfully, add the job to `output/job-tracker.xlsx` with `scripts/manage_job_tracker.py`. Never add a tracker row before both final deliverables exist.

If the job comes from Indeed, use the `jk` value as the job number and name the DOCX:
`Dave-Call+<Company-Name>+<jk>.docx`
and the match report:
`Dave-Call+<Company-Name>+<jk>.md`

Name the archived job description:
`<Company-Name>+<jk>.md`

Sanitize `<Company-Name>` using the same Windows-safe rules as the scratch directory.

Keep all temporary files (preview PNGs, PDFs, layout tests) inside `scratch/{Company-Name}+{JobNumber}/`.
All reusable tools and scripts remain in `scripts/`.

## Job tracker

Every successfully completed Gecko resume must be recorded in `output/job-tracker.xlsx` as the final workflow step. Run:

`python scripts/manage_job_tracker.py add --resume "output/resumes/<resume-file>.docx" --match-report "output/match-reports/<match-report-file>.md" --job-description "input/job-descriptions/<archived-listing-file>.md"`

The tracker script assigns the next Resume # and prevents duplicate Job Number entries. Do not directly rewrite existing tracker rows or clear the user-maintained `Applied` and `Contacted` columns.
