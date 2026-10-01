# AntiGravity Project Instructions — Gecko

You are working inside the Gecko resume-customization project.

Always read `GECKO_SYSTEM.md` before performing resume work.

## Source of truth

The permanent Gecko authorities are:

- Content: `input/master-resume/Dave-Call-Resume.txt`
- Visual format and layout: `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`

The TXT is the only default source for resume facts. The PDF is the only default visual model. Re-read the TXT and verify both files before every generation. Never use an older or previously tailored resume as a content source or formatting starting point, and never silently fall back if either required file is missing. These rules override older source/template instructions unless the user explicitly makes a job-specific exception. The complete controlling text is in `GECKO_SYSTEM.md`.

Do not invent employers, dates, degrees, metrics, certifications, tools, or accomplishments. If a job description requests something not supported by the current master archive, describe it as a gap rather than manufacturing experience.

## Default output

When asked to "use Gecko" for a job:

1. Read the job listing.
2. Analyze the job requirements against the master archive.
3. Create a dedicated scratch subfolder: `scratch/{Company-Name}+{JobNumber}/`.
4. Tailor the resume naturally.
5. Produce an exactly two-page DOCX using reusable generators in `scripts/`.
6. Save the resume under `output/resumes/`.
7. After the final resume has been created and validated successfully, add or update the job in the canonical Google Sheet with `scripts/manage_job_tracker.py`.

### Permanent resume content structure

- Every generated resume must include **CORE STRENGTHS** with at least 8 job-relevant, master-supported entries. Use professional Title Case for every entry and include more than 8 when useful.
- Every generated resume must include **TOOLS & PLATFORMS** with at least 8 job-relevant, master-supported products or platforms. Preserve official brand capitalization and never use generic lowercase capabilities as tool entries.
- Every **PROFESSIONAL EXPERIENCE** job must render as: job title alone on line 1; `Company Name  City, State` on line 2; accomplishments on line 3 and below. The legacy `Job Title | Company` format is prohibited. Preserve the blank right-side date cell/area.
- Before the final DOCX is saved, use Gecko's cleanup and validation logic to correct and verify both section counts, canonical capitalization, the two-line job hierarchy, removal of combined headers, and removal of lowercase placeholder entries. A resume that fails these checks is not final.

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
Name the archived job description:
`<Company-Name>+<jk>.md`

Sanitize `<Company-Name>` using the same Windows-safe rules as the scratch directory.

Keep all temporary files (preview PNGs, PDFs, layout tests) inside `scratch/{Company-Name}+{JobNumber}/`.
All reusable tools and scripts remain in `scripts/`.

## Job tracker

Google Sheets is the canonical job tracker. Do not create or update a local Excel job tracker. Every successfully completed Gecko resume must be recorded through the tracker command as the final workflow step. Run:

`python scripts/manage_job_tracker.py add --resume "output/resumes/<resume-file>.docx" --job-description "input/job-descriptions/<archived-listing-file>.md"`

The tracker script finds existing rows by Job Number, updates only Gecko-managed cells, and assigns the next Resume #/Index from the Google Sheet for new jobs. Do not directly rewrite existing tracker rows or clear the user-maintained `Applied` and `Contacted` columns.

Daily Job Scout also runs the reusable read-only Gmail response checker after the resume queue. It may update only the `Response` cell for a conservatively matched applied job. OAuth must use only `gmail.readonly`; Gmail messages and labels must never be modified. Gmail failures are nonfatal to discovery and resume creation.

Never bypass `scripts/manage_job_tracker.py`, because it also marks the matching Scout row `Resume Created`. If Google Sheets is unavailable, report the error; do not create a local tracker or silently fall back.

## Persistent Google Sheets formatting

Preserve user colors, filters, checkbox values, frozen rows, column widths, conditional formatting, formulas, hyperlinks, and manual fields on the live `Job Tracker` and `Job Scout` tabs. Routine operations update only Gecko-managed cell values in place. Never recreate tabs, rewrite entire ranges, change physical row order, or reset formatting or filter criteria. Initialize native Applied/Contacted checkboxes only on newly created rows; never overwrite existing manual values. Outside the Gmail response checker, preserve `Response` as a user-owned field.
