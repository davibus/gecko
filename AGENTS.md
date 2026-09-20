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

### Mandatory pagination validation

- The final DOCX must be exactly two pages when opened or exported by Microsoft Word. A browser, HTML, PDF, or fallback renderer alone is not sufficient proof of DOCX pagination.
- Prefer Microsoft Word COM pagination and confirm both Word's computed page count and the exported PDF page count equal 2.
- If native Word pagination is unavailable, use a conservative layout with substantial bottom-page safety margin, clearly disclose that native validation is unavailable, and do not describe fallback-only pagination as equivalent to Word validation.
- Never add content merely to fill space when doing so risks a third page. An underfilled second page is preferable to a three-page resume.
- Do not claim the Gecko workflow is fully validated until the actual DOCX has been confirmed as exactly two pages in Microsoft Word.

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

Every successfully completed Gecko resume must be recorded through the tracker command as the final workflow step. During the Google Sheets migration, the command updates `output/job-tracker.xlsx` first and then synchronizes both `Job Tracker` and `Job Scout` to the configured Google Sheet. Run:

`python scripts/manage_job_tracker.py add --resume "output/resumes/<resume-file>.docx" --match-report "output/match-reports/<match-report-file>.md" --job-description "input/job-descriptions/<archived-listing-file>.md"`

The tracker script assigns the next Resume # and prevents duplicate Job Number entries. Do not directly rewrite existing tracker rows or clear the user-maintained `Applied` and `Contacted` columns.

When `TRACKER_BACKEND=google-sheets`, treat the Google Sheet as the primary live tracker and retain `output/job-tracker.xlsx` as the required backup. Never bypass `scripts/manage_job_tracker.py`, because it also marks the matching Scout row `Resume Created` and preserves manual fields across both backends.
