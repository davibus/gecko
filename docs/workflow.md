# Gecko Workflow

## Optional upstream Job Scout

Job Scout is separate from resume generation. Each morning, run `python job-scout/scout.py daily`. The daily path validates existing active links and newly discovered links before scoring. Confirmed-dead unprotected jobs are cleared from the active Scout worksheet and removed from SQLite; temporary HTTP/network failures are retained for a later check. The review output contains only qualifying jobs first discovered in that run. Selected/application history and manual `Applied` / `Contacted` fields are preserved. The command never creates a resume or starts a handoff.

To proceed with a listing, explicitly run `python job-scout/scout.py select <ID>`. Selection archives the description in `input/job-descriptions/`; it does not create a resume or application-tracker row. Continue with the unchanged workflow below only after choosing a job. Full setup and commands are in `job-scout/README.md`.

## New job

1. Read and extract the job details from the job URL or copied listing.
2. Save or paste the captured job description into `input/job-descriptions/{Company-Name}+{JobNumber}.md`.
3. Create a dedicated scratch subfolder for the job: `scratch/{Company-Name}+{JobNumber}/`
   - Sanitize the company name for Windows filenames by replacing spaces with hyphens and removing invalid filename characters (`\ / : * ? " < > |`).
   - All job-specific temporary files must live inside this subfolder (preview PNGs, test PDFs, layout verification images, intermediate files).
   - Do not place new job-specific temporary files directly in the root `scratch/` folder.
4. Verify all claims against the current master DOCX (`input/master-resume/Dave-Call-resume-9-23-26.docx`). The older PDF and `Dave_Call_Resume_5ec9726395344311.docx` are not content sources; the latter is for formatting only.
5. Tailor the resume subtly and generate the two-page DOCX resume under `output/resumes/Dave-Call+{Company-Name}+{JobNumber}.docx` using the reusable generator in `scripts/`.
6. Generate the comprehensive Match Score report under `output/match-reports/Dave-Call+{Company-Name}+{JobNumber}.md`.
7. Verify page count and layout with `scripts/validate_word_native.ps1`; sandbox executions are handed automatically to the interactive Word bridge. Install the bridge once from the normal desktop with `scripts/Install-Gecko-Word-Bridge.cmd`. Keep Word/PDF validation artifacts inside the job's scratch subfolder (`scratch/{Company-Name}+{JobNumber}/`).
8. Only after the final resume and match report have both been created and validated, append the job to the persistent tracker:
   `python scripts/manage_job_tracker.py add --resume "output/resumes/Dave-Call+{Company-Name}+{JobNumber}.docx" --match-report "output/match-reports/Dave-Call+{Company-Name}+{JobNumber}.md" --job-description "input/job-descriptions/{Company-Name}+{JobNumber}.md"`
9. Run `python scripts/manage_job_tracker.py validate`. A Gecko job is not complete until the tracker update and validation succeed.

## V2 tailoring and QA

The resume workflow now starts with a source-backed tailoring plan. Job Scout's discovery and selection workflow remains separate; its evidence reader now uses the same current master DOCX. For an archived listing, run:

For new jobs, use `scripts/gecko_v2.py`. The older job-specific `generate_*_resume.py` scripts are historical artifacts and must not be used as factual sources or as the current generation path.

```powershell
python scripts/gecko_v2.py plan "input/job-descriptions/Company+JobNumber.md"
```

This creates `scratch/Company+JobNumber/tailoring-plan.json` before any resume is changed. Review its required and preferred skills, responsibilities, tools, seniority signals, industry terminology, ATS keywords, evidence links, and gaps. `supported` means a listed term and related master-resume passage were found; `review` is a possible connection that needs human judgment; `gap` means Gecko found no credible passage. The plan's selected bullet IDs can be reordered or removed, but evidence quotes and source hashes cannot be altered. Resume bullets use current master-DOCX passages with only fixed grammar cleanup. If the master changes, rebuild the plan; generation rejects stale source hashes. Do not promote a `review` or `gap` item into a resume claim without a master-DOCX update.

Generate and run the automatic QA gate:

```powershell
python scripts/gecko_v2.py generate "scratch/Company+JobNumber/tailoring-plan.json"
```

The generator writes `output/resumes/Dave-Call+Company+JobNumber.docx`. It calls `scripts/validate_word_native.ps1` and writes `scratch/Company+JobNumber/v2-qa.json`, `validation-status.json`, and a Word-exported PDF. QA fails when native Word and PDF counts do not both equal two, when text reaches page edges, when source-backed bullets or Gecko layout have changed, or when likely keyword repetition is excessive. It lists remaining unsupported or uncertain requirements. On a QA pass, the CLI also writes the Match Score report to `output/match-reports/`. Automated text matching is deliberately conservative and does not replace reviewing the plan, score, and rendered pages for natural language and semantic accuracy. If the Word bridge is unavailable, install it with `scripts/Install-Gecko-Word-Bridge.cmd`; QA remains failed and the tracker must not be updated. After layout edits, rerun `python scripts/gecko_v2.py qa "scratch/Company+JobNumber/tailoring-plan.json"`.

Review the generated Match Score report's evidence-backed strengths, gaps, ATS alignment, recommended emphasis, and interview considerations. Only after both final files exist and V2 QA passes, run the tracker command in step 8. The V2 CLI never updates the tracker itself. Tests: `python -m unittest discover -s scripts -p test_gecko_v2.py -v`.

## Quality checklist

- Exactly two pages, including no trailing blank or near-blank page
- No invented experience
- Natural wording
- Strong job-specific emphasis
- Appropriate ATS terms
- Correct filename: `Dave-Call+{Company-Name}+{JobNumber}.docx`
- Match Score included in `output/match-reports/Dave-Call+{Company-Name}+{JobNumber}.md`
- Archived listing saved as `input/job-descriptions/{Company-Name}+{JobNumber}.md`
- No visible job-date text (preserve date spacing)
- No page overflow or excessive empty blocks
- All temporary artifacts contained within `scratch/{Company-Name}+{JobNumber}/`
- All reusable scripts maintained in `scripts/`
- Job recorded once in `output/job-tracker.xlsx`, after both final deliverables were successfully created
- Existing tracker rows and manual `Applied` / `Contacted` entries preserved
