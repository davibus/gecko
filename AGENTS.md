# AntiGravity Project Instructions — Gecko

You are working inside the Gecko resume-customization project.

Always read `GECKO_SYSTEM.md` before performing resume work.

## Source of truth

The single authoritative source for all resume content is:
`input/master-resume/Dave-Call-Resume.txt`

This file is a comprehensive career archive, not a page-limited resume. Never use `Dave-Call-resume-9-23-26.docx` or `dcall-resume-3-15-26.pdf` for resume content. `Dave_Call_Resume_5ec9726395344311.docx` is a format reference only; no claim from it may appear unless the same information is supported by the current master archive. Re-read the master TXT for every generation, evaluation, or customization. Previously generated resumes and project notes are not independent factual sources.

Do not invent employers, dates, degrees, metrics, certifications, tools, or accomplishments. If a job description requests something not supported by the current master archive, describe it as a gap rather than manufacturing experience.

## Default output

When asked to "use Gecko" for a job:

1. Read the job listing.
2. Analyze fit.
3. Create a dedicated scratch subfolder: `scratch/{Company-Name}+{JobNumber}/`.
4. Tailor the resume naturally.
5. Produce an exactly two-page DOCX using reusable generators in `scripts/`.
6. Produce a qualitative Match Analysis report with evidence-backed strengths and gaps.
7. Save the resume under `output/resumes/`.
8. Save the match report under `output/match-reports/`.
9. After both final files have been created and validated successfully, add or update the job in the canonical Google Sheet with `scripts/manage_job_tracker.py`. Never add a tracker row before both final deliverables exist.

### Mandatory pagination validation

- The final DOCX must be exactly two pages when opened or exported by Microsoft Word. A browser, HTML, PDF, or fallback renderer alone is not sufficient proof of DOCX pagination.
- Prefer Microsoft Word COM pagination and confirm both Word's computed page count and the exported PDF page count equal 2.
- Use `scripts/validate_word_native.ps1` as the single authoritative check in every environment. Sandboxed agents always submit requests through that entry point to the permanently available interactive-user bridge; they must never attempt direct Word COM, start or control the Scheduled Task, or ask the user to validate a resume manually. The bridge and its watchdog run hidden under the logged-in Windows user, start automatically at logon, and recover after process failure.
- Standard invocation: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_word_native.ps1 -DocxPath "output\resumes\<resume-file>.docx" -PdfPath "scratch\<Company-Name>+<JobNumber>\word-validation.pdf" -ResultPath "scratch\<Company-Name>+<JobNumber>\validation-status.json"`
- The one-time interactive-user installation command is `scripts\Install-Gecko-Word-Bridge.cmd`. Normal Gecko use must not require rerunning it. Health diagnostics are available through `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-Gecko-Word-Bridge.ps1`; exceptional user-side recovery is `scripts\Restart-Gecko-Word-Bridge.cmd`.
- If bridge validation fails, run/report the health diagnostics once and stop before the tracker update. Do not repeatedly retry Word COM from the sandbox, do not ask the user to perform manual pagination, and do not add a tracker row while validation is `native-pending`.
- If native Word pagination is unavailable, use a conservative layout with substantial bottom-page safety margin, clearly disclose that native validation is unavailable, and do not describe fallback-only pagination as equivalent to Word validation.
- Never add content merely to fill space when doing so risks a third page. An underfilled second page is preferable to a three-page resume.
- Do not claim the Gecko workflow is fully validated until the actual DOCX has been confirmed as exactly two pages in Microsoft Word.

If the job comes from Indeed, use the `jk` value as the job number and name the DOCX:
`Dave-Call+<Company-Name>+<Job-Title>+<jk>.docx`
and the match report:
`Dave-Call+<Company-Name>+<jk>.md`

Name the archived job description:
`<Company-Name>+<jk>.md`

Sanitize `<Company-Name>` using the same Windows-safe rules as the scratch directory.

Keep all temporary files (preview PNGs, PDFs, layout tests) inside `scratch/{Company-Name}+{JobNumber}/`.
All reusable tools and scripts remain in `scripts/`.

## Job tracker

Google Sheets is the canonical job tracker. Do not create or update a local Excel job tracker. Every successfully completed Gecko resume must be recorded through the tracker command as the final workflow step. Run:

`python scripts/manage_job_tracker.py add --resume "output/resumes/<resume-file>.docx" --match-report "output/match-reports/<match-report-file>.md" --job-description "input/job-descriptions/<archived-listing-file>.md"`

The tracker script finds existing rows by Job Number, updates only Gecko-managed cells, and assigns the next Resume #/Index from the Google Sheet for new jobs. Do not directly rewrite existing tracker rows or clear the user-maintained `Applied` and `Contacted` columns.

Daily Job Scout also runs the reusable read-only Gmail response checker after the resume queue. It may update only the `Response` cell for a conservatively matched applied job. OAuth must use only `gmail.readonly`; Gmail messages and labels must never be modified. Gmail failures are nonfatal to discovery and resume creation.

Never bypass `scripts/manage_job_tracker.py`, because it also marks the matching Scout row `Resume Created`. If Google Sheets is unavailable, report the error; do not create a local tracker or silently fall back.

## Persistent Google Sheets formatting

Preserve user colors, filters, checkbox values, frozen rows, column widths, conditional formatting, formulas, hyperlinks, and manual fields on the live `Job Tracker` and `Job Scout` tabs. Routine operations update only Gecko-managed cell values in place. Never recreate tabs, rewrite entire ranges, change physical row order, or reset formatting or filter criteria. Initialize native Applied/Contacted checkboxes only on newly created rows; never overwrite existing manual values. Outside the Gmail response checker, preserve `Response` as a user-owned field.
