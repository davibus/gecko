# Resume generation, layout, validation, and naming

Read this guide and GECKO_SYSTEM.md before generating, tailoring, renaming, or
validating resumes. These detailed rules were moved from the root AGENTS.md;
their resume facts, style, layout, naming, and native Word requirements are retained.
The current tracker is SQLite: in the preserved workflow below, the final
completion step uses scripts/manage_job_tracker.py through its configured backend,
not a Google Sheet write. See tracker.md for completion guards and readback.

## Source of truth

The permanent Gecko authorities are:

- Content: `input/master-resume/master-resume-v4.docx`
- Visual format and layout: `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`

In this checkout the absolute content path is `C:\gecko_main\input\master-resume\master-resume-v4.docx`. Resolve the repository-relative path from the current `gecko_main` root for every generation, then read the DOCX anew. A same-named file elsewhere, cached profile, prior tailored DOCX, or PDF cannot supply resume facts. Missing, unreadable, or empty DOCX content stops generation.

The DOCX is the only default source for resume facts. The PDF is the only default visual model. Re-read the DOCX and verify both files before every generation. Never use an older or previously tailored resume as a content source or formatting starting point, and never silently fall back if either required file is missing. These rules override older source/template instructions unless the user explicitly makes a job-specific exception. The complete controlling text is in `GECKO_SYSTEM.md`.

Do not invent employers, dates, degrees, metrics, certifications, tools, or accomplishments. If a job description requests something not supported by the current master archive, describe it as a gap rather than manufacturing experience.
## Default output

The three-page AI review sample under `output/examples/` is an experiment only.
Never use it as a template or default for future resumes. Keep the standard
two-page section structure; do not add its separate AI & Automation Projects
section unless the user explicitly requests it again. Relevant AI experience
from the canonical master may still be tailored into the existing sections.

Professional Summaries must select job-relevant facts from the current master,
including newer AI, CRM, automation, and e-commerce work when relevant. Vary
the substantive emphasis across postings, even repeated titles. Never publish
the same resume twice: compare normalized visible content and summaries against
saved resumes before publication. Saved documents are duplicate-check inputs
only, never factual sources. Preserve the existing Resume Created = X guard.
Exact byte or text uniqueness alone does not establish meaningful tailoring.
Use a distinct role-relevant summary opening and business focus, select supporting
accomplishments, and reject near-identical visible document content before publication.

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
- Every **PROFESSIONAL EXPERIENCE** job must have one physical header line with `Job Title - Company Name - City, ST` on the left and verified employment dates flush with the right text margin. Use exactly one space around each normal hyphen. Preserve the verified title, company, location, and dates from the master DOCX. Use a borderless two-column table with zero cell padding, one bold paragraph/run for the complete left heading, and a right-aligned date paragraph. No manual alignment spaces, hard breaks, tabs, or separate company/location/date lines. Compact verified month names and recover width from indentation before minimal heading-only size adjustments. If both fields cannot fit legibly on one line without overlap, fail validation. Accomplishments follow below.
- Select distinct, relevant accomplishment bullets according to available evidence and measured page capacity, with no fixed per-role ceiling. Prioritize the most relevant roles and avoid repeating Selected Results.
- Before the final DOCX is saved, use Gecko's cleanup and validation logic to correct and verify both section counts, canonical capitalization, each complete one-line job header with right-aligned source dates, and removal of lowercase placeholder entries. Word-rendered headings and dates must share one line, with every date at the same right margin. A resume that fails these checks is not final.

### Mandatory pagination validation

- The final DOCX must be exactly two pages when opened or exported by Microsoft Word. A browser, HTML, PDF, or fallback renderer alone is not sufficient proof of DOCX pagination.
- Prefer Microsoft Word COM pagination and confirm both Word's computed page count and the exported PDF page count equal 2.
- Use `scripts/validate_word_native.ps1` as the single authoritative check in every environment. Sandboxed agents always submit requests through that entry point to the permanently available interactive-user bridge; they must never attempt direct Word COM, start or control the Scheduled Task, or ask the user to validate a resume manually. The bridge and its watchdog run hidden under the logged-in Windows user, start automatically at logon, and recover after process failure.
- Standard invocation: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_word_native.ps1 -DocxPath "output\resumes\<resume-file>.docx" -PdfPath "scratch\<Company-Name>+<JobNumber>\word-validation.pdf" -ResultPath "scratch\<Company-Name>+<JobNumber>\validation-status.json"`
- The one-time interactive-user installation command is `scripts\Install-Gecko-Word-Bridge.cmd`. Normal Gecko use must not require rerunning it. Health diagnostics are available through `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-Gecko-Word-Bridge.ps1`; exceptional user-side recovery is `scripts\Restart-Gecko-Word-Bridge.cmd`.
- If bridge validation fails, run/report the health diagnostics once and stop before the tracker update. Do not repeatedly retry Word COM from the sandbox, do not ask the user to perform manual pagination, and do not add a tracker row while validation is `native-pending`.
- If native Word pagination is unavailable, use a conservative layout with substantial bottom-page safety margin, clearly disclose that native validation is unavailable, and do not describe fallback-only pagination as equivalent to Word validation.
- Exactly two pages is necessary but not sufficient when useful, job-relevant evidence remains. Education & Certifications should finish within approximately 0.5 inch (36 points) above the normal bottom text boundary on page two. Use distinct, source-supported accomplishments and relevant project detail, prioritizing the most relevant roles; there is no fixed two- or three-bullet ceiling. Keep standard sections, readable model typography, and normal margins/spacing. Do not fill space with larger fonts, inflated spacing, blank paragraphs, repeated claims, unrelated material, or an education footer/text box. Inspect both rendered pages and measure the final section after native Word/PDF validation. If genuinely relevant evidence is exhausted, document the reviewed evidence and explain the remaining gap; page count alone is not completion.
- On overflow, remove the least relevant supporting detail, preserving core accomplishments, then revalidate. On underfill, add distinct relevant evidence and revalidate; do not stop simply because the document has two pages.
- Do not claim the Gecko workflow is fully validated until the actual DOCX has been confirmed as exactly two pages in Microsoft Word.

If the job comes from Indeed, retain the full `jk` as the internal job number and use a short resume identifier in the DOCX name:
`Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`
Name the archived job description:
`<Company-Name>+<jk>.md`

Sanitize `<Company-Name>` using the same Windows-safe rules as the scratch directory.

Keep all temporary files (preview PNGs, PDFs, layout tests) inside `scratch/{Company-Name}+{JobNumber}/`.
All reusable tools and scripts remain in `scripts/`.
## Permanent short resume filename rule

Resume filenames must use `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`, ending in a unique numeric identifier of at most five digits (Gecko uses five zero-padded digits). Never put a full posting ID, Indeed jk, UUID, hash, or long numeric job number in a resume filename. Keep filenames at most 150 characters, sanitizing Windows-invalid characters and shortening an excessively long title at a word boundary. Reserve identifiers through `job-scout/resume_naming.py`; do not truncate a source ID or guess uniqueness. Full posting IDs remain in the identity registry and DOCX metadata for job matching. Use the same rule for explicitly requested renames, verify tracker links after any rename, and preserve the existing Resume Created = X guard. Archived job descriptions and scratch folders continue to use full posting IDs.

Example: `Dave-Call+Array+Digital-Marketing-Manager+00001.docx`.

For each job description, select only relevant, source-supported facts from the version 4 master. The master is a career archive, not content to include in full; keep the established two-page resume format.

User-confirmed version 4 exception: if an employment title is omitted in the master, retain the verified company and location without inventing a title. The master archive itself has no one-line or page-limit requirement; apply layout rules only to the finished resume.

Read the version 4 Word master directly for every resume, including paragraphs, tables, and list items. No text export, older master, or cover letter is an alternate factual source. Fill as much of both pages as practical with relevant, distinct, master-supported evidence; never add filler or inflate spacing to fill pages. The master cover letter is reserved for a later explicit request.


## Missing job description — user rule (October 19, 2026)

Before automatic resume generation, verify that a usable job description exists
and belongs to the exact job. If the description is missing, empty, incomplete,
or mismatched, skip resume creation and record the job status as **No job description**
in the SQLite workspace/dashboard, with the specific reason in Notes. A company
name, title, search snippet, or another job's description is not sufficient.
Continue processing other eligible jobs. Never invent requirements or create a
generic resume to bypass the missing description. Preserve existing resumes,
Resume Created markers, links, manual decisions, Applied, and protected fields.
Only remove this blocker after a matching usable description has been obtained
and verified; all normal approval and completed-resume guards still apply.
