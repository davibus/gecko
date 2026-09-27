# Gecko — Resume Customization Project

Gecko is Dave Call's resume-tailoring workflow for turning a job listing into a targeted, natural-sounding, ATS-friendly resume and qualitative match analysis.

The normal Daily Job Scout command runs the complete discovery-to-resume workflow. It searches Adzuna, Remotive, and configured Web Careers backends, rejects Jooble, filters to relevant role families, deduplicates results, synchronizes the existing Google Sheet, sends only newly discovered rows with `Apply? = Yes` and blank `Resume Created` cells through the canonical Gecko V2 generator, and then checks Gmail read-only for substantive employer responses to applied jobs.

```powershell
python job-scout/scout.py daily
```

Use `python job-scout/scout.py daily --dry-run` to perform network discovery against a temporary SQLite copy without changing the live tracker, creating descriptions, or generating resumes. See `job-scout/README.md` for source setup, duplicate behavior, failure recovery, and diagnostics.

To run it through the agent, use the reusable prompt in `prompts/scout-jobs.md`.

## How to use this project in AntiGravity

1. Open this folder as a project in AntiGravity.
2. Put a job description or copied job listing into `input/job-descriptions/`.
3. Use the prompt in `prompts/use-gecko.md`.
4. Gecko uses `input/master-resume/Dave-Call-Resume.txt` as the sole factual source. `Dave_Call_Resume_5ec9726395344311.docx` is for formatting only.
   For V2, create and review the evidence-backed plan with `python scripts/gecko_v2.py plan "input/job-descriptions/Company+JobNumber.md"`, then run `python scripts/gecko_v2.py generate "scratch/Company+JobNumber/tailoring-plan.json"`. Generation runs Word-native QA and records any remaining weaknesses. See `docs/workflow.md` for the full process.
5. Save tailored resumes to `output/resumes/` and match reports to `output/match-reports/`.
6. After both final deliverables are successfully created and validated, add or update the job in the canonical Google Sheet with `scripts/manage_job_tracker.py`.

## Core Gecko behavior

- Tailor the resume subtly to the job rather than rewriting it in an obviously AI-generated way.
- Keep the finished resume exactly two pages.
- Preserve the established white-background professional layout, 11 pt font, 1.15 line spacing, and clean spacing.
- Remove visible job-date text while preserving the right-side date space/cell for manual entry later.
- Name resumes `Dave-Call+<Company-Name>+<Job-Title>+<job-number>.docx`, match reports `Dave-Call+<Company-Name>+<job-number>.md`, and archived job descriptions `<Company-Name>+<job-number>.md`. For Indeed, use the `jk` value as the job number.
- Include evidence-backed strengths, weaknesses/gaps, ATS alignment, and recommendations without a numerical compatibility rating.
- Use relevant AI/productivity tools naturally when helpful: Codex, ChatGPT, Claude, Perplexity, Cursor, AntiGravity.
- When relevant, include the senior-scale metric: managed $30 million per month with a team of 4.
- Avoid stuffing exact job-description phrases or repeatedly naming the target company.
- Keep the user's professional voice and only make claims supported by the source resume or explicit user-provided facts.

- Keep all temporary files, test scripts, and layout preview PNGs in dedicated subfolders: `scratch/{Company-Name}+{JobNumber}/`.
- Record every completed job in Google Sheets only after the final resume and match report exist. The tracker assigns sequential Resume #/Index values from the Sheet, prevents new duplicate Job Numbers, and preserves manual `Applied` and `Contacted` entries.

## Job tracker

Google Sheets is the canonical job tracker. Do not create or update a local Excel job tracker. Configure the spreadsheet ID, tab names, and service-account credentials in `.env.local` using `.env.example`, then check connectivity:

```powershell
python scripts/manage_job_tracker.py init
```

Add one newly completed Gecko job as the final workflow step:

```powershell
python scripts/manage_job_tracker.py add --resume "output/resumes/Dave-Call+Company+Job-Title+JobNumber.docx" --match-report "output/match-reports/Dave-Call+Company+JobNumber.md" --job-description "input/job-descriptions/Company+JobNumber.md"
```

Validate the live Sheet:

```powershell
python scripts/manage_job_tracker.py validate
```

The `add` command is idempotent by Job Number when the application tab exists. It reads company, title, pay, source URL, source name, and date found from the archived listing and report; unavailable optional fields remain blank. It also updates the matching Job Scout lifecycle and resume link while preserving user-maintained application/contact fields.

## Gmail response tracking

Daily Job Scout can update the `Response` column on the canonical `Job Scout` tab from employer and recruiter replies. It uses Google's installed-app OAuth flow and requests only `https://www.googleapis.com/auth/gmail.readonly`; it cannot send, delete, archive, label, or otherwise modify mail. Generic job alerts, recommendations, newsletters, and application confirmations without a substantive next step are excluded. Matching message IDs and row-stage metadata are stored in the ignored `job-scout/data/gmail-response-state.json` file so repeated runs do not duplicate updates.

One-time setup:

1. In Google Cloud Console, create or select a project and enable the Gmail API.
2. Open Google Auth Platform. Configure Branding and Audience. For a personal Gmail account, choose `External`, keep the app in Testing, and add your Gmail address as a test user. For an eligible Workspace-only deployment, `Internal` may be used.
3. Under Data Access, add only `https://www.googleapis.com/auth/gmail.readonly`.
4. Under Clients, create an OAuth client with application type `Desktop app`.
5. Download its JSON file to `.secrets/gmail-oauth-client.json`. Do not commit it.
6. Install dependencies: `python -m pip install -r job-scout/requirements.txt`.
7. Authorize once from an interactive terminal: `python job-scout/gmail_response_tracker.py authorize`.
8. Confirm the read-only check: `python job-scout/gmail_response_tracker.py check`.

The authorization command opens Google's consent page and saves the refresh token to `.secrets/gmail-oauth-token.json`, which is also ignored. The normal `python job-scout/scout.py daily` command then runs Gmail tracking automatically. A Gmail authentication or API error is logged to `output/gmail-response-tracking.log` and reported in the daily summary without failing discovery or resume creation.

Gecko's production tracker is Google Sheets. `output/job-tracker.xlsx` is supported only as an explicitly supplied offline link-audit artifact and is not read or modified by Gmail response tracking.

## Folder map

- `job-scout/` — upstream job discovery, scoring, deduplication, and local status storage

- `AGENTS.md` — project instructions AntiGravity should follow
- `GECKO_SYSTEM.md` — full Gecko operating specification
- `scripts/` — reusable resume generation, PDF preview, and layout tuning scripts
- `input/master-resume/` — canonical source archive (`Dave-Call-Resume.txt`)
- `input/job-descriptions/` — job listings to tailor against
- `output/resumes/` — generated resumes
- `output/match-reports/` — job-fit reports
- Google Sheets (`Job Tracker` and `Job Scout` tabs) — canonical application and discovery tracker
- `scratch/{Company-Name}+{JobNumber}/` — job-specific temporary files, previews, and layout tests
- `templates/` — notes about the preferred resume layout
- `prompts/` — reusable operating prompts
- `docs/` — project notes and workflow documentation

