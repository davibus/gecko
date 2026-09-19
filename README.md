# Gecko — Resume Customization Project

Gecko is Dave Call's resume-tailoring workflow for turning a job listing into a targeted, natural-sounding, ATS-friendly resume and match analysis.

## How to use this project in AntiGravity

1. Open this folder as a project in AntiGravity.
2. Put a job description or copied job listing into `input/job-descriptions/`.
3. Use the prompt in `prompts/use-gecko.md`.
4. Gecko should use `input/master-resume/dcall-resume-3-15-26.pdf` as the source resume unless another source is explicitly supplied.
5. Save tailored resumes to `output/resumes/` and match reports to `output/match-reports/`.

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

## Folder map

- `AGENTS.md` — project instructions AntiGravity should follow
- `GECKO_SYSTEM.md` — full Gecko operating specification
- `scripts/` — reusable resume generation, PDF preview, and layout tuning scripts
- `input/master-resume/` — canonical source resume
- `input/job-descriptions/` — job listings to tailor against
- `output/resumes/` — generated resumes
- `output/match-reports/` — job-fit reports
- `scratch/{Company-Name}+{JobNumber}/` — job-specific temporary files, previews, and layout tests
- `templates/` — notes about the preferred resume layout
- `prompts/` — reusable operating prompts
- `docs/` — project notes and workflow documentation

