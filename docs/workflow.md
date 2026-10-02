# Gecko Workflow

## Execution default

Run the affected canonical workflow live after implementing requested changes. Normal commands create the real resume artifacts and perform only the necessary Gecko-managed Google Sheet writes; they must verify files and read affected cells back, including the Resume Link target, before reporting success. Do not substitute previews, mocks, instructions, or dry runs unless the user explicitly requests read-only behavior. This default preserves Cost `x`, eligibility, deduplication, protected fields, unrelated data, and all access and non-application boundaries.

## Automated Daily Job Scout

Each morning, run `python job-scout/scout.py daily`. This is the single discovery-to-resume entry point. It appends new records to the configured intake worksheet, then invokes the canonical Gecko queue across every source. Queue fields are resolved by exact unambiguous headers; the current mapping is F `Apply?`, G `Resume Created`, I `Cost`, and Q `Resume Link`. Cost `x` excludes a row. Approved rows with blank Resume Created are created; approved rows with X and blank or whitespace Resume Link are recreated from the current authorities; X with a valid nonblank link is skipped.

The queue archives available job context, creates the evidence-backed tailoring plan from the current master TXT, renders in the current model-PDF style, and runs Word-native two-page QA. The exact resume remains under `output/resumes`; an existing file is never overwritten during repair, and a versioned name keeps the job number last. Success atomically writes `Resume Created = X` and a clickable absolute file URI to `Resume Link`. A creation failure leaves G blank; a repair failure preserves the existing X and blank Q. Both record the retryable reason in `Notes`, never `Cost`, and continue to later rows.

Use `python job-scout/scout.py daily --dry-run` for discovery plus a read-only queue classification against a temporary database copy. It reports new eligible, repair eligible, completed, and Cost-excluded rows without tracker, archive, resume, or Gmail writes. The standalone `python scripts/generate_apply_queue.py --dry-run` reports the same queue-only snapshot.

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
4. Verify all claims against the current master archive (`input/master-resume/Dave-Call-Resume.txt`) and use `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as the required visual formatting/layout model. Stop if either authority is missing; do not fall back to an older or tailored resume.
5. Tailor the resume subtly and generate the two-page DOCX resume under `output/resumes/Dave-Call+{Company-Name}+{Job-Title}+{JobNumber}.docx` using the reusable generator in `scripts/`.
6. Verify page count and layout with `scripts/validate_word_native.ps1`, the only authoritative Word-pagination entry point. A sandboxed agent submits its request to the permanently running interactive-user bridge; it never automates Word directly and never asks the user to validate manually. Install the hidden bridge and watchdog once from the IDE terminal with `scripts\Install-Gecko-Word-Bridge.cmd`; both Scheduled Tasks start at user logon and self-recover. Keep Word/PDF validation artifacts inside the job's scratch subfolder (`scratch/{Company-Name}+{JobNumber}/`).
   Standard invocation: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\validate_word_native.ps1 -DocxPath "output\resumes\<resume-file>.docx" -PdfPath "scratch\<Company-Name>+<JobNumber>\word-validation.pdf" -ResultPath "scratch\<Company-Name>+<JobNumber>\validation-status.json"`
   Health check: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-Gecko-Word-Bridge.ps1`. Exceptional user-side restart: `scripts\Restart-Gecko-Word-Bridge.cmd`. If validation fails, report these diagnostics once instead of retrying sandbox Word COM.
7. Only after the final resume has been created and validated, upsert the job in the canonical Google Sheet:
   `python scripts/manage_job_tracker.py add --resume "output/resumes/Dave-Call+{Company-Name}+{Job-Title}+{JobNumber}.docx" --job-description "input/job-descriptions/{Company-Name}+{JobNumber}.md"`
8. Run `python scripts/manage_job_tracker.py validate`. A Gecko job is not complete until the tracker update and validation succeed.

## V2 tailoring and QA

To process the configured intake worksheet, run `python scripts/generate_apply_queue.py`. Matching ignores case and surrounding spaces. It creates approved rows with blank Resume Created, recreates approved X rows whose Resume Link is blank, skips Cost `x`, and skips completed rows with valid links. The runner processes jobs one at a time and continues after individual failures.

There is no description-length gate. If reliable listing and structured Sheet context are both unavailable, Gecko creates no resume and leaves completion unchanged. After Word-native QA passes, the canonical recorder verifies the DOCX is directly under `output/resumes`, creates the URL with `Path.resolve().as_uri()`, and writes that complete `file:///` URL directly as the visible Resume Link value. It never writes a `HYPERLINK` formula or `Open Resume` label. It updates only Resume Created, Resume Link, lifecycle status, and Gecko failure text in Notes. It re-finds the destination by stable ID before writing, so row movement cannot attach a resume to another job. Applied, Cost, formatting, formulas, and row order remain unchanged.

The complete command is `python job-scout/scout.py daily`. It evaluates existing rows across every source and uses only Location and Work Arrangement to set Apply? for Utah or explicitly remote jobs. It then applies the shared Cost exclusion and creation/repair rules. After the exact DOCX passes Word-native validation, it writes G = X and Q = the clickable local file URI. It never submits an application or marks Applied.

The resume workflow starts with a source-backed tailoring plan bound to the current master archive and required formatting-model hashes. Job Scout's discovery and selection workflow remains separate; its evidence reader uses the same current master archive. For an archived listing, run:

For new jobs, use `scripts/gecko_v2.py`. The older job-specific `generate_*_resume.py` scripts are historical artifacts and must not be used as factual sources or as the current generation path.

```powershell
python scripts/gecko_v2.py plan "input/job-descriptions/Company+JobNumber.md"
```

This creates `scratch/Company+JobNumber/tailoring-plan.json` before any resume is changed. Review its required and preferred skills, responsibilities, tools, seniority signals, industry terminology, ATS keywords, evidence links, and gaps. `supported` means a listed term and related master-resume passage were found; `review` is a possible connection that needs human judgment; `gap` means Gecko found no credible passage. The plan's selected bullet IDs can be reordered or removed, but evidence quotes and source hashes cannot be altered. Resume bullets use current master-archive passages with only fixed grammar cleanup. If the master changes, rebuild the plan; generation rejects stale source hashes. Do not promote a `review` or `gap` item into a resume claim without a master-archive update.

Generate and run the automatic QA gate:

```powershell
python scripts/gecko_v2.py generate "scratch/Company+JobNumber/tailoring-plan.json"
```

The generator writes `output/resumes/Dave-Call+Company+Job-Title+JobNumber.docx`. It calls `scripts/validate_word_native.ps1` and writes `scratch/Company+JobNumber/v2-qa.json`, `validation-status.json`, and a Word-exported PDF. QA fails when native Word and PDF counts do not both equal two, when text reaches page edges, when source-backed bullets or Gecko layout have changed, or when likely keyword repetition is excessive. It lists remaining unsupported or uncertain requirements. Automated text matching is deliberately conservative and does not replace reviewing the plan and rendered pages for natural language and semantic accuracy. The bridge is expected to be permanently available after its one-time installation. If it is unhealthy, capture `Test-Gecko-Word-Bridge.ps1` diagnostics, leave QA failed, and do not update the tracker; do not retry Word COM from the sandbox. After layout edits, rerun `python scripts/gecko_v2.py qa "scratch/Company+JobNumber/tailoring-plan.json"`.

Only after the final resume exists and V2 QA passes, run the tracker command in step 7. The V2 CLI never updates the tracker itself. Tests: `python -m unittest discover -s scripts -p test_gecko_v2.py -v`.

## Quality checklist

- Exactly two pages, including no trailing blank or near-blank page
- No invented experience
- Natural wording
- Strong job-specific emphasis
- Appropriate ATS terms
- Correct filename: `Dave-Call+{Company-Name}+{Job-Title}+{JobNumber}.docx`
- Archived listing saved as `input/job-descriptions/{Company-Name}+{JobNumber}.md`
- No visible job-date text (preserve date spacing)
- No page overflow or excessive empty blocks
- All temporary artifacts contained within `scratch/{Company-Name}+{JobNumber}/`
- All reusable scripts maintained in `scripts/`
- Job recorded once in the canonical Google Sheet, after the final resume was successfully created and validated
- Existing tracker rows and manual `Applied` / `Contacted` entries preserved
