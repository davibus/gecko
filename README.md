# Gecko — Resume Customization Project

Gecko is Dave Call's resume-tailoring workflow for turning a job listing into a targeted, natural-sounding, ATS-friendly resume and match analysis.

Job discovery is available as a separate upstream module under `job-scout/`. It scores and stores openings without generating resumes. See `job-scout/README.md` for provider setup, search, review, and selection commands.

To run it through the agent, use the reusable prompt in `prompts/scout-jobs.md`.

## How to use this project in AntiGravity

1. Open this folder as a project in AntiGravity.
2. Put a job description or copied job listing into `input/job-descriptions/`.
3. Use the prompt in `prompts/use-gecko.md`.
4. Gecko uses `input/master-resume/Dave-Call-resume-9-23-26.docx` as the sole factual source. `Dave_Call_Resume_5ec9726395344311.docx` is for formatting only.
   For V2, create and review the evidence-backed plan with `python scripts/gecko_v2.py plan "input/job-descriptions/Company+JobNumber.md"`, then run `python scripts/gecko_v2.py generate "scratch/Company+JobNumber/tailoring-plan.json"`. Generation runs Word-native QA and records any remaining weaknesses. See `docs/workflow.md` for the full process.
5. Save tailored resumes to `output/resumes/` and match reports to `output/match-reports/`.
6. After both final deliverables are successfully created and validated, add the job to `output/job-tracker.xlsx` with `scripts/manage_job_tracker.py`.

## Core Gecko behavior

- Tailor the resume subtly to the job rather than rewriting it in an obviously AI-generated way.
- Keep the finished resume exactly two pages.
- Preserve the established white-background professional layout, 11 pt font, 1.15 line spacing, and clean spacing.
- Remove visible job-date text while preserving the right-side date space/cell for manual entry later.
- Use company-inclusive filenames: `Dave-Call+<Company-Name>+<job-number>.docx` for resumes, `Dave-Call+<Company-Name>+<job-number>.md` for match reports, and `<Company-Name>+<job-number>.md` for archived job descriptions. For Indeed, use the `jk` value as the job number.
- Include a Match Score by default, with strengths, weaknesses/gaps, ATS alignment, and recommendations.
- Use relevant AI/productivity tools naturally when helpful: Codex, ChatGPT, Claude, Perplexity, Cursor, AntiGravity.
- When relevant, include the senior-scale metric: managed $30 million per month with a team of 4.
- Avoid stuffing exact job-description phrases or repeatedly naming the target company.
- Keep the user's professional voice and only make claims supported by the source resume or explicit user-provided facts.

- Keep all temporary files, test scripts, and layout preview PNGs in dedicated subfolders: `scratch/{Company-Name}+{JobNumber}/`.
- Record every completed job in the persistent Excel tracker only after the final resume and match report exist. The tracker assigns sequential Resume # values, prevents duplicate Job Numbers, and preserves manual `Applied` and `Contacted` entries.

## Job tracker

Create or backfill the tracker:

```powershell
python scripts/manage_job_tracker.py import-history
```

Add one newly completed Gecko job as the final workflow step:

```powershell
python scripts/manage_job_tracker.py add --resume "output/resumes/Dave-Call+Company+JobNumber.docx" --match-report "output/match-reports/Dave-Call+Company+JobNumber.md" --job-description "input/job-descriptions/Company+JobNumber.md"
```

Validate the workbook:

```powershell
python scripts/manage_job_tracker.py validate
```

The `add` command is idempotent by Job Number. It reads company, title, pay, source URL, source name, date found, and Match Score from the archived listing and match report; unavailable optional fields remain blank. The extended tracker also records lifecycle status while preserving the user-maintained `Applied` and `Contacted` columns.

## Folder map

- `job-scout/` — upstream job discovery, scoring, deduplication, and local status storage

- `AGENTS.md` — project instructions AntiGravity should follow
- `GECKO_SYSTEM.md` — full Gecko operating specification
- `scripts/` — reusable resume generation, PDF preview, and layout tuning scripts
- `input/master-resume/` — canonical source resume
- `input/job-descriptions/` — job listings to tailor against
- `output/resumes/` — generated resumes
- `output/match-reports/` — job-fit reports
- `output/job-tracker.xlsx` — persistent application tracker
- `scratch/{Company-Name}+{JobNumber}/` — job-specific temporary files, previews, and layout tests
- `templates/` — notes about the preferred resume layout
- `prompts/` — reusable operating prompts
- `docs/` — project notes and workflow documentation

