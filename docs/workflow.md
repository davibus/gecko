See [tracker-schema.md](tracker-schema.md) for the live workbook tabs, verified `Job List` headers, aliases, write rules, and daily report command. Runtime mapping lives in `job-scout/tracker_schema.py` and always resolves live headers by name.

## Columns follow names, not positions

Users may move whole columns freely without asking for code or instruction updates.
Read live headers on every sync; use unique header names for fields and stable IDs
for jobs. Never restore a saved order or treat column letters/counts in documentation
as requirements. Automatic idle sync adopts the current order and preserves custom
columns, resume links and Sheet formulas. Moving columns is different from renaming
or deleting a field: missing or ambiguous names must be resolved without guessing.
Keep row 1 frozen. Historical layout tables are reference snapshots only.


## Current column layout — October 20, 2026

See `docs/current-tracker-columns.md` (repository-relative) for the verified 36-column layout and field behavior. This supersedes historical letters and schemas below. Resolve unique live headers by name and jobs by ID; never sort or move only part of a job row. Qualifies to Apply? is the eligibility field (legacy internal alias Apply?). Applied Date is primary; Previous Applied Date is preserved history, wherever those named columns are moved. Cover Letter, CV Created Date, Cover Letter Link, and Cover Letter Created Date remain user-managed. Create Resume is a preserved Sheet formula showing Yes only when Enough Data is Yes; it does not start generation. Enough Data is a saved review, not an automatic AI assessment. Preserve Job Description, Notes, Previous Notes, word-count formulas, all jobs and resumes, and frozen row 1. The removed Cursor Instructions tab must not be recreated automatically.

For Source = Indeed, the 'Apply or on Company Website (If Indeed)' field stores the exact visible text of the primary application/status control on the Indeed job page. Examples include 'Apply Now', 'Apply on Company Website', 'Already applied', and 'Job no longer available'. Do not normalize the text. If it cannot be reliably resolved, leave the current value unchanged and continue.

# Gecko Workflow

## Execution default

Run the affected canonical workflow live after implementing requested changes. Normal commands create the real resume artifacts and perform only the necessary Gecko-managed Google Sheet writes; they must verify files and read affected cells back, including the Resume Link target, before reporting success. Do not substitute previews, mocks, instructions, or dry runs unless the user explicitly requests read-only behavior. This default preserves Cost `x`, eligibility, deduplication, protected fields, unrelated data, and all access and non-application boundaries.

## Automated Daily Job Scout

Each morning, run `python job-scout/scout.py daily`. This is the single discovery-to-resume entry point. It appends new records to the configured intake worksheet, then invokes the canonical Gecko queue across every source. Queue fields are resolved by exact unambiguous headers; every scout and the queue inspect the existing row by stable identity. An X in Resume Created, ignoring case and surrounding spaces, always skips resume generation and preserves the marker and link. A blank link on an X row is reported for manual review. A nonblank link with a blank marker also requires manual review. Cost `x` excludes a row. Approved rows with both completion fields blank may be created.

The queue archives available job context, creates the evidence-backed tailoring plan from the current master DOCX, renders in the current model-PDF style, and runs Word-native two-page QA. The exact resume remains under `output/resumes`. Success atomically writes `Resume Created = X` and a clickable absolute file URI to `Resume Link`. A creation failure leaves the named `Resume Created` field blank, records the retryable reason in `Notes`, never `Cost`, and continues to later rows. A nonblank existing link with a blank marker requires manual review and stops generation.

Use `python scripts/inspect_tracker_schema.py` to validate live tab names, IDs, and named headers without changing Sheets. Use `python job-scout/scout.py daily --dry-run` for discovery plus read-only queue classification against a temporary database copy. It does not write tracker cells, archive jobs, create resumes, or update Gmail responses. `python scripts/daily_report.py --dry-run` writes managed vertical dashboard cells in `Daily Tasks`, inserts a `Daily Run` history block at row 3, and saves local audit files from a live Sheet snapshot. `Daily Tasks` keeps the newest five distinct dates in descending order; older `Daily Run` history remains below new blocks. See [daily-report.md](daily-report.md). The older `python job-scout/scout.py daily-report --dry-run` prints a console-only snapshot. The standalone `python scripts/generate_apply_queue.py --dry-run` reports the queue-only snapshot.

Gmail setup and authorization are documented in `README.md`. Live runs report emails checked, responses matched, and exact tracker rows updated. Gmail failures remain nonfatal and are appended to `output/gmail-response-tracking.log`.

### Google Sheets link audit

Run the conservative link audit directly against the canonical Google Sheet:

```powershell
python scripts/check_job_links.py
```

Test a small read-only sample first with `python scripts/check_job_links.py --limit 5 --dry-run`. The checker locates `Job URL` and `Notes` by header and appends confirmed removals only to `Notes`. It treats blocks, rate limits, bot challenges, timeouts, and temporary network errors as unknown and leaves the related cell unchanged. If Google Sheets is unavailable, the command fails clearly and does not create a local fallback.

To proceed with a listing, explicitly run `python job-scout/scout.py select <ID>`. Selection archives the description in `input/job-descriptions/`; it does not create a resume or application-tracker row. Continue with the unchanged workflow below only after choosing a job. Full setup and commands are in `job-scout/README.md`.

## New job

1. Read and extract the job details from the job URL or copied listing.
2. Save or paste the captured job description into `input/job-descriptions/{Company-Name}+{JobNumber}.md`.
3. Create a dedicated scratch subfolder for the job: `scratch/{Company-Name}+{JobNumber}/`
   - Sanitize the company name for Windows filenames by replacing spaces with hyphens and removing invalid filename characters (`\ / : * ? " < > |`).
   - All job-specific temporary files must live inside this subfolder (preview PNGs, test PDFs, layout verification images, intermediate files).
   - Do not place new job-specific temporary files directly in the root `scratch/` folder.
4. Verify all claims against the current master archive (`input/master-resume/master-resume-v4.docx`) and use `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as the required visual formatting/layout model. Stop if either authority is missing; do not fall back to an older or tailored resume.
5. Tailor the resume subtly and generate the two-page DOCX resume under `output/resumes/Dave-Call+{Company-Name}+{Job-Title}+{Resume-ID}.docx` using the reusable generator in `scripts/`.
6. Verify page count and layout with `scripts/validate_word_native.ps1`, the only authoritative Word-pagination entry point. A sandboxed agent submits its request to the permanently running interactive-user bridge; it never automates Word directly and never asks the user to validate manually. Install the hidden bridge and watchdog once from the IDE terminal with `scripts\Install-Gecko-Word-Bridge.cmd`; both Scheduled Tasks start at user logon and self-recover. Keep Word/PDF validation artifacts inside the job's scratch subfolder (`scratch/{Company-Name}+{JobNumber}/`).
   Standard invocation: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_word_native.ps1 -DocxPath "output\resumes\<resume-file>.docx" -PdfPath "scratch\<Company-Name>+<JobNumber>\word-validation.pdf" -ResultPath "scratch\<Company-Name>+<JobNumber>\validation-status.json"`
   Health check: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-Gecko-Word-Bridge.ps1`. Exceptional user-side restart: `scripts\Restart-Gecko-Word-Bridge.cmd`. If validation fails, report these diagnostics once instead of retrying sandbox Word COM.
7. Only after the final resume has been created and validated, upsert the job in the canonical Google Sheet:
   `python scripts/manage_job_tracker.py add --resume "output/resumes/Dave-Call+{Company-Name}+{Job-Title}+{Resume-ID}.docx" --job-description "input/job-descriptions/{Company-Name}+{JobNumber}.md"`
8. Run `python scripts/manage_job_tracker.py validate`. A Gecko job is not complete until the tracker update and validation succeed.

## V2 tailoring and QA

To process the configured intake worksheet, run `python scripts/generate_apply_queue.py`. Matching ignores case and surrounding spaces. It creates approved rows only when both `Resume Created` and `Resume Link` are blank, skips every X row regardless of link, reports blank links on X rows for manual review, and skips Cost `x`. The runner processes jobs one at a time and continues after individual failures.

There is no description-length gate. If reliable listing and structured Sheet context are both unavailable, Gecko creates no resume and leaves completion unchanged. After Word-native QA passes, the canonical recorder verifies the DOCX is directly under `output/resumes`, creates the URL with `Path.resolve().as_uri()`, and writes that complete `file:///` URL directly as the visible Resume Link value. It never writes a `HYPERLINK` formula or `Open Resume` label. It updates only Resume Created, Resume Link, lifecycle status, and Gecko failure text in Notes. It re-finds the destination by stable ID before writing, so row movement cannot attach a resume to another job. Applied, Cost, formatting, formulas, and row order remain unchanged.

The complete command is `python job-scout/scout.py daily`. It evaluates existing rows across every source and sets the named Apply? field to Yes for Utah or explicitly remote jobs that pass the other safeguards. Blank or unknown Cost does not block approval; a confirmed required application fee is `Cost = x` and forces No. Unknown location does not approve a job. It then applies the shared exclusion and creation rules. After the exact DOCX passes Word-native validation, it writes `Resume Created` = X and `Resume Link` = the clickable local file URI. It never submits an application or marks Applied.

The resume workflow starts with a source-backed tailoring plan bound to the current master archive and required formatting-model hashes. Job Scout's discovery and selection workflow remains separate; its evidence reader uses the same current master archive. For an archived listing, run:

For new jobs, use `scripts/gecko_v2.py`. Resume Creator, Indeed Scout, Job Scout, and the apply queue share this generator and its employment-heading formatter. Each Professional Experience entry has one physical line: `Job Title - Company Name - City, ST` at left and compact, verified master DOCX employment dates flush with the right text margin. A borderless two-column Word table uses zero cell padding and right-aligned dates. The generator keeps the existing margins and 11-point main text; only heading text may receive a minimal size adjustment. Word-native QA must show both fields unwrapped, nonoverlapping, and the document at exactly two pages. A line that cannot fit legibly fails QA. The older job-specific `generate_*_resume.py` scripts are historical artifacts and must not be used as factual sources or as the current generation path.

```powershell
python scripts/gecko_v2.py plan "input/job-descriptions/Company+JobNumber.md"
```

This creates `scratch/Company+JobNumber/tailoring-plan.json` before any resume is changed. Review its required and preferred skills, responsibilities, tools, seniority signals, industry terminology, ATS keywords, evidence links, and gaps. `supported` means a listed term and related master-resume passage were found; `review` is a possible connection that needs human judgment; `gap` means Gecko found no credible passage. The plan's selected bullet IDs can be reordered or removed, but evidence quotes and source hashes cannot be altered. Resume bullets use current master-archive passages with only fixed grammar cleanup. If the master changes, rebuild the plan; generation rejects stale source hashes. Do not promote a `review` or `gap` item into a resume claim without a master-archive update.

The canonical DOCX is `C:\gecko_main\input\master-resume\master-resume-v4.docx`.
The V2 reader accepts its mixed narrative and pipe-delimited employment blocks,
merges repeated employer blocks, and keeps each accomplishment with its stated
employer. Conflicting employment dates or locations stop planning and generation
with the conflicting source facts listed. Resolve them with Dave; never guess,
silently choose a version, or fall back to an older master. Existing plans naming
the previous source must be rebuilt. The compact AI screening profile must also
be reviewed against this DOCX before its raw-byte fingerprint is refreshed.

Generate and run the automatic QA gate:

```powershell
python scripts/gecko_v2.py generate "scratch/Company+JobNumber/tailoring-plan.json"
```

The generator first checks the matching live Job List row and refuses generation when normalized Resume Created is X. It also refuses to overwrite an existing output DOCX. For a new resume, it writes `output/resumes/Dave-Call+Company+Job-Title+00001.docx`. It calls `scripts/validate_word_native.ps1` and writes `scratch/Company+JobNumber/v2-qa.json`, `validation-status.json`, and a Word-exported PDF. QA fails when native Word and PDF counts do not both equal two, when text reaches page edges, when source-backed bullets or Gecko layout have changed, or when likely keyword repetition is excessive. It lists remaining unsupported or uncertain requirements. Automated text matching is deliberately conservative and does not replace reviewing the plan and rendered pages for natural language and semantic accuracy. The bridge is expected to be permanently available after its one-time installation. If it is unhealthy, capture `Test-Gecko-Word-Bridge.ps1` diagnostics, leave QA failed, and do not update the tracker; do not retry Word COM from the sandbox. After layout edits, rerun `python scripts/gecko_v2.py qa "scratch/Company+JobNumber/tailoring-plan.json"`.

Only after the final resume exists and V2 QA passes, run the tracker command in step 7. The V2 CLI never updates the tracker itself. Tests: `python -m unittest discover -s scripts -p test_gecko_v2.py -v`.

## Quality checklist

- Exactly two pages, including no trailing blank or near-blank page
- No invented experience
- Natural wording
- Strong job-specific emphasis
- Appropriate ATS terms
- Correct filename: `Dave-Call+{Company-Name}+{Job-Title}+{Resume-ID}.docx`
- Archived listing saved as `input/job-descriptions/{Company-Name}+{JobNumber}.md`
- Verified job dates flush right on the same physical line as every job heading
- No page overflow or excessive empty blocks
- All temporary artifacts contained within `scratch/{Company-Name}+{JobNumber}/`
- All reusable scripts maintained in `scripts/`
- Job recorded once in the canonical Google Sheet, after the final resume was successfully created and validated
- Existing tracker rows and manual `Applied` / `Contacted` entries preserved


## Permanent short resume filename rule

Resume filenames must use `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`, ending in a unique numeric identifier of at most five digits (Gecko uses five zero-padded digits). Never put a full posting ID, Indeed jk, UUID, hash, or long numeric job number in a resume filename. Keep filenames at most 150 characters, sanitizing Windows-invalid characters and shortening an excessively long title at a word boundary. Reserve identifiers through `job-scout/resume_naming.py`; do not truncate a source ID or guess uniqueness. Full posting IDs remain in the identity registry and DOCX metadata for job matching. Use the same rule for explicitly requested renames, verify tracker links after any rename, and preserve the existing Resume Created = X guard. Archived job descriptions and scratch folders continue to use full posting IDs.

Example: `Dave-Call+Array+Digital-Marketing-Manager+00001.docx`.

## Resume content density

Exactly two pages is necessary but not sufficient when useful, job-relevant evidence remains. Education & Certifications should finish within approximately 0.5 inch (36 points) above the normal bottom text boundary on page two. Use distinct, source-supported accomplishments and relevant project detail, prioritizing the most relevant roles; there is no fixed two- or three-bullet ceiling. Keep standard sections, readable model typography, and normal margins/spacing. Do not fill space with larger fonts, inflated spacing, blank paragraphs, repeated claims, unrelated material, or an education footer/text box. Inspect both rendered pages and measure the final section after native Word/PDF validation. If genuinely relevant evidence is exhausted, document the reviewed evidence and explain the remaining gap; page count alone is not completion.
