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

If the job comes from Indeed, use the `jk` value as the job number and name the DOCX:
`Dave-Call+<Company-Name>+<jk>.docx`
and the match report:
`Dave-Call+<Company-Name>+<jk>.md`

Name the archived job description:
`<Company-Name>+<jk>.md`

Sanitize `<Company-Name>` using the same Windows-safe rules as the scratch directory.

Keep all temporary files (preview PNGs, PDFs, layout tests) inside `scratch/{Company-Name}+{JobNumber}/`.
All reusable tools and scripts remain in `scripts/`.

