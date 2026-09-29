# Gecko — Job Discovery and Resume Workflow

Gecko discovers and imports relevant jobs, stores listing data, tailors and generates source-backed resumes, and tracks applications in Google Sheets.

The normal Daily Job Scout command runs the complete discovery-to-resume workflow. It searches enabled official APIs, public feeds, configured ATS boards, and compliant Brave discovery sources; rejects Jooble; filters to relevant role families; deduplicates results; synchronizes the existing Google Sheet; sends only newly discovered rows with `Apply? = Yes` and blank `Resume Created` cells through the canonical Gecko V2 generator; and then checks Gmail read-only for substantive employer responses to applied jobs.

```powershell
python job-scout/scout.py daily
```

Use `python job-scout/scout.py daily --dry-run` to perform network discovery against a temporary SQLite copy without changing the live tracker, creating descriptions, or generating resumes. See `job-scout/README.md` for source setup, duplicate behavior, failure recovery, and diagnostics.

For manual Indeed intake, paste an Indeed job URL into Column R (`Job URL`) of a new `Job Scout` row, then run the same daily command. Gecko extracts the `jk`, checks the full dataset for duplicates, retrieves structured posting data, and populates that row. Duplicates and blocked retrievals are recorded in `Notes` without assigning a Scout ID or stopping the run. See `job-scout/README.md` for the exact behavior and retry procedure.

To run it through the agent, use the reusable prompt in `prompts/scout-jobs.md`.

## How to use this project in AntiGravity

1. Open this folder as a project in AntiGravity.
2. Put a job description or copied job listing into `input/job-descriptions/`.
3. Use the prompt in `prompts/use-gecko.md`.
4. Gecko uses `input/master-resume/Dave-Call-Resume.txt` as the sole factual source and `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as the required visual formatting/layout model. Generation stops rather than falling back when either file is missing.
   For V2, create and review the evidence-backed plan with `python scripts/gecko_v2.py plan "input/job-descriptions/Company+JobNumber.md"`, then run `python scripts/gecko_v2.py generate "scratch/Company+JobNumber/tailoring-plan.json"`. Generation runs Word-native QA and records any remaining weaknesses. See `docs/workflow.md` for the full process.
5. Save tailored resumes to `output/resumes/`.
6. After the final resume is successfully created and validated, add or update the job in the canonical Google Sheet with `scripts/manage_job_tracker.py`.

## Core Gecko behavior

- Tailor the resume subtly to the job rather than rewriting it in an obviously AI-generated way.
- Keep the finished resume exactly two pages.
- Follow the required model PDF's white-background, two-page US Letter design: centered header, EB Garamond typography, compact margins, olive section headings and rules, clean spacing, and matching section hierarchy and density.
- Remove visible job-date text while preserving the right-side date space/cell for manual entry later.
- Name resumes `Dave-Call+<Company-Name>+<Job-Title>+<job-number>.docx` and archived job descriptions `<Company-Name>+<job-number>.md`. For Indeed, use the `jk` value as the job number.
- Use relevant AI/productivity tools naturally when helpful: Codex, ChatGPT, Claude, Perplexity, Cursor, AntiGravity.
- When relevant, include the senior-scale metric: managed $30 million per month with a team of 4.
- Avoid stuffing exact job-description phrases or repeatedly naming the target company.
- Keep the user's professional voice and only make claims supported by the source resume or explicit user-provided facts.

- Keep all temporary files, test scripts, and layout preview PNGs in dedicated subfolders: `scratch/{Company-Name}+{JobNumber}/`.
- Record every completed job in Google Sheets only after the final resume exists and passes validation. The tracker assigns sequential Resume #/Index values from the Sheet, prevents new duplicate Job Numbers, and preserves manual `Applied` and `Contacted` entries.

## Job tracker

Google Sheets is the canonical job tracker. Do not create or update a local Excel job tracker. Configure the spreadsheet ID, tab names, and service-account credentials in `.env.local` using `.env.example`, then check connectivity:

```powershell
python scripts/manage_job_tracker.py init
```

Add one newly completed Gecko job as the final workflow step:

```powershell
python scripts/manage_job_tracker.py add --resume "output/resumes/Dave-Call+Company+Job-Title+JobNumber.docx" --job-description "input/job-descriptions/Company+JobNumber.md"
```

Validate the live Sheet:

```powershell
python scripts/manage_job_tracker.py validate
```

The `add` command is idempotent by Job Number when the application tab exists. It reads company, title, pay, source URL, source name, and date found from the archived listing; unavailable optional fields remain blank. It also updates the matching Job Scout lifecycle and resume link while preserving user-maintained application/contact fields.

## Gmail response tracking

Daily Job Scout can update the `Response` column on the canonical `Job Scout` tab from employer and recruiter replies. It uses Google's installed-app OAuth flow and requests only `https://www.googleapis.com/auth/gmail.readonly`; it cannot send, delete, archive, label, or otherwise modify mail. Each run performs one Gmail search for the preceding seven days, downloads each unprocessed result at most once, and matches messages locally against all applied jobs. Generic job alerts, recommendations, newsletters, and application confirmations without a substantive next step are excluded. Matching message IDs and row-stage metadata are stored in the ignored `job-scout/data/gmail-response-state.json` file so repeated runs do not duplicate updates.

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

Gmail message downloads are paced by `GECKO_GMAIL_REQUEST_DELAY_SECONDS`, which defaults to `0.2` seconds. Rate-limit responses receive bounded exponential-backoff retries; authentication and permission failures are not retried.

Gecko's only job tracker is Google Sheets. Resume queues, link audits, and Gmail response tracking fail clearly if the Sheet is unavailable; none creates or reads a local spreadsheet fallback.

## Folder map

- `job-scout/` — upstream job discovery, role filtering, deduplication, and local status storage

- `AGENTS.md` — project instructions AntiGravity should follow
- `GECKO_SYSTEM.md` — full Gecko operating specification
- `scripts/` — reusable resume generation, PDF preview, and layout tuning scripts
- `input/master-resume/` — canonical content archive (`Dave-Call-Resume.txt`) and required visual model (`MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`)
- `input/job-descriptions/` — job listings to tailor against
- `output/resumes/` — generated resumes
- Google Sheets (`Job Tracker` and `Job Scout` tabs) — canonical application and discovery tracker
- `scratch/{Company-Name}+{JobNumber}/` — job-specific temporary files, previews, and layout tests
- `templates/` — notes about the preferred resume layout
- `prompts/` — reusable operating prompts
- `docs/` — project notes and workflow documentation

