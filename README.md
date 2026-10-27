The live Gecko Job Tracker tabs, sheet IDs, named headers, aliases, and workflow rules are in [docs/tracker-schema.md](docs/tracker-schema.md). `job-scout/tracker_schema.py` is the central runtime schema; job tracker code resolves current Sheet headers by name. The verified workbook has `Daily Run` history, `Daily Tasks` five-date vertical dashboard, `Job List`, empty `Deleted Jobs`, empty unassigned `Scratch`, and hidden `Rejected Jobs`. It has no `Daily Reports` or `List of Job Sources` tab. Missing tabs are reported, never created implicitly.

For Source = Indeed, the 'Apply or on Company Website (If Indeed)' field stores the exact visible text of the primary application/status control on the Indeed job page. Examples include 'Apply Now', 'Apply on Company Website', 'Already applied', and 'Job no longer available'. Do not normalize the text. If it cannot be reliably resolved, leave the current value unchanged and continue.

# Gecko — Job Discovery and Resume Workflow

The canonical project name is **Gecko Main**. Open the project from the `gecko_main` directory and use that name in new scripts, documentation, commands, paths, and configuration. `AGENTS.md` records the deprecated directory name.

Gecko discovers and imports relevant jobs, stores listing data, tailors and generates source-backed resumes, and tracks applications in Google Sheets.

Gecko commands use their live write path by default when the requested work includes writes. Normal invocations produce the real artifacts and managed Google Sheet updates, then read affected cells back for verification. Use an explicit `--dry-run` or a documented diagnostic command only when a read-only result is wanted. Live authorization remains limited to the requested workflow and never includes applying to a job, sending messages, purchases, destructive work, or bypassing access restrictions.

The normal Daily Job Scout command runs the complete discovery-to-resume workflow. It searches enabled official APIs, public feeds, configured ATS boards, and compliant Brave discovery sources; rejects Jooble; filters to relevant role families; deduplicates results; synchronizes the existing Google Sheet; sets Apply? to Yes for Utah or explicitly remote rows from every source; sends eligible incomplete rows through the canonical Gecko V2 generator; writes X and the persistent resume link only after validation; and then checks Gmail read-only for substantive employer responses to applied jobs.

```powershell
python job-scout/scout.py daily
```

Use `python job-scout/scout.py daily --dry-run` to perform network discovery against a temporary SQLite copy without changing the live tracker, creating descriptions, or generating resumes. See `job-scout/README.md` for source setup, duplicate behavior, failure recovery, and diagnostics.

Use `python scripts/inspect_tracker_schema.py` for read-only live tab, ID, and header validation. Use `python scripts/daily_report.py --dry-run` to write the five-date vertical dashboard in `Daily Tasks`, insert history in `Daily Run`, and save local JSON/JSONL audit files. Each block shows named metrics in A/B and existing tracker source counts in E/F. `Daily Tasks` keeps the five newest distinct Denver reporting dates; same-date reruns replace that date's block. `Daily Run` inserts new blocks at row 3, preserving older history. It reads the tracker and canonical queue without modifying jobs or resumes. Discovery, Indeed page verification, and Gmail checks that cannot safely run are marked `Unavailable` except for the specified numeric-zero display metrics in `Daily Run`. See [docs/daily-report.md](docs/daily-report.md). The older `python job-scout/scout.py daily-report --dry-run` remains a console-only snapshot.

For manual Indeed intake, paste an Indeed job URL into the `Job URL` field of a new `Job List` row, then run the same daily command. Gecko extracts the `jk`, checks the full dataset for duplicates, retrieves structured posting data, and populates that row. Duplicates and blocked retrievals are recorded in `Notes` without assigning an ID or stopping the run. See `job-scout/README.md` for the exact behavior and retry procedure.

To run it through the agent, use the reusable prompt in `prompts/scout-jobs.md`.

## How to use this project in AntiGravity

1. Open this folder as a project in AntiGravity.
2. Put a job description or copied job listing into `input/job-descriptions/`.
3. Use the prompt in `prompts/use-gecko.md`.
4. Gecko uses `input/master-resume/master-resume-v4.docx` as the sole factual source and `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as the required visual formatting/layout model. Generation stops rather than falling back when either file is missing.
   For V2, create and review the evidence-backed plan with `python scripts/gecko_v2.py plan "input/job-descriptions/Company+JobNumber.md"`, then run `python scripts/gecko_v2.py generate "scratch/Company+JobNumber/tailoring-plan.json"`. Generation runs Word-native QA and records any remaining weaknesses. Every new resume uses a one-physical-line `Job Title - Company Name - City, ST` heading at left with verified employment dates aligned to the right text margin. See `docs/workflow.md` for the full process.
5. Save tailored resumes to `output/resumes/`.
6. After the final resume is successfully created and validated, add or update the job in the canonical Google Sheet with `scripts/manage_job_tracker.py`.

## Core Gecko behavior

- Tailor the resume subtly to the job rather than rewriting it in an obviously AI-generated way.
- Keep the finished resume exactly two pages.
- Follow the required model PDF's white-background, two-page US Letter design: centered header, EB Garamond typography, compact margins, olive section headings and rules, clean spacing, and matching section hierarchy and density.
- Show verified employment dates flush right on the same physical line as each job heading.
- Name resumes `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx` and archived job descriptions `<Company-Name>+<job-number>.md`. For Indeed, use the `jk` value as the job number.
- Use relevant AI/productivity tools naturally when helpful: Codex, ChatGPT, Claude, Perplexity, Cursor, AntiGravity.
- When relevant, include the senior-scale metric: managed $30 million per month with a team of 4.
- Avoid stuffing exact job-description phrases or repeatedly naming the target company.
- Keep the user's professional voice and only make claims supported by the source resume or explicit user-provided facts.

- Keep all temporary files, test scripts, and layout preview PNGs in dedicated subfolders: `scratch/{Company-Name}+{JobNumber}/`.
- Record every completed job in Google Sheets only after the final resume exists and passes validation. The current workbook records completion on a uniquely matched `Job List` row and preserves manual fields. A separate legacy application tab, if configured, retains its Resume #/Index behavior.

## Job tracker

Google Sheets is the canonical job tracker. Do not create or update a local Excel job tracker. Configure the spreadsheet ID, tab names, and service-account credentials in `.env.local` using `.env.example`, then check connectivity. Enable the Google Sheets API and share the tracker with the service account. Completed DOCX files remain only under `output/resumes`:

```powershell
python scripts/manage_job_tracker.py init
```

Add one newly completed Gecko job as the final workflow step:

```powershell
python scripts/manage_job_tracker.py add --resume "output/resumes/Dave-Call+Company+Job-Title+00001.docx" --job-description "input/job-descriptions/Company+JobNumber.md"
```

Validate the live Sheet:

```powershell
python scripts/manage_job_tracker.py validate
```

The `add` command is idempotent by Job Number when a legacy application tab is explicitly configured. It verifies the DOCX under `output/resumes`, then updates the matching Job List lifecycle while preserving user-maintained application/contact fields. Queue fields are resolved by unambiguous header on the configured intake tab. Every scout and the queue read the existing row before generation. An `X` in Resume Created, ignoring case and spaces, always skips regeneration and preserves the existing marker and link; a blank link is reported for manual review. A nonblank link with a blank marker also stops generation for manual review. Cost `x` excludes creation. Successful new rows receive `X` and the complete `file:///` URL created by `Path.resolve().as_uri()` directly in `Resume Link`; the writer verifies the DOCX exists and never substitutes `Open Resume` display text.

Run the complete all-source workflow with one command:

`python scripts/gecko_daily.py --apply`

Preview it with `python scripts/gecko_daily.py --dry-run`. The orchestrator
preflights the live tracker and existing `Daily Run` tab, then records the
daily outcome there and in a local audit. It stops before live changes when
the report destination is missing. See [docs/daily-orchestrator.md](docs/daily-orchestrator.md).

The underlying workflow remains available as:

`python job-scout/scout.py daily`

The daily command reuses `scripts/generate_apply_queue.py`; there is no duplicate resume workflow. For every source, it sets `Apply?` to `Yes` for Utah or explicitly remote jobs, respects `Cost` = `x`, writes `Resume Created` = `X` only after successful generation and validation, and writes the verified local file link to `Resume Link`. Nonqualifying Apply? values and unrelated cells are preserved; the workflow never applies to jobs or marks `Applied`.

## Gmail response tracking

Daily Job Scout can update the `Response` column on the canonical `Job List` tab from employer and recruiter replies. It uses Google's installed-app OAuth flow and requests only `https://www.googleapis.com/auth/gmail.readonly`; it cannot send, delete, archive, label, or otherwise modify mail. Each run performs one Gmail search for the preceding seven days, downloads each unprocessed result at most once, and matches messages locally against all applied jobs. Generic job alerts, recommendations, newsletters, and application confirmations without a substantive next step are excluded. Matching message IDs and row-stage metadata are stored in the ignored `job-scout/data/gmail-response-state.json` file so repeated runs do not duplicate updates.

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
- `input/master-resume/` — canonical content archive (`master-resume-v4.docx`) and required visual model (`MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf`)
- `input/job-descriptions/` — job listings to tailor against
- `output/resumes/` — generated resumes
- Google Sheets (`Job List` tab) — current canonical job tracker; `Rejected Jobs` stores durable rejection history
- `scratch/{Company-Name}+{JobNumber}/` — job-specific temporary files, previews, and layout tests
- `templates/` — notes about the preferred resume layout
- `prompts/` — reusable operating prompts
- `docs/` — project notes and workflow documentation



## Permanent short resume filename rule

Resume filenames must use `Dave-Call+<Company-Name>+<Job-Title>+<Resume-ID>.docx`, ending in a unique numeric identifier of at most five digits (Gecko uses five zero-padded digits). Never put a full posting ID, Indeed jk, UUID, hash, or long numeric job number in a resume filename. Keep filenames at most 150 characters, sanitizing Windows-invalid characters and shortening an excessively long title at a word boundary. Reserve identifiers through `job-scout/resume_naming.py`; do not truncate a source ID or guess uniqueness. Full posting IDs remain in the identity registry and DOCX metadata for job matching. Use the same rule for explicitly requested renames, verify tracker links after any rename, and preserve the existing Resume Created = X guard. Archived job descriptions and scratch folders continue to use full posting IDs.

Example: `Dave-Call+Array+Digital-Marketing-Manager+00001.docx`.

## Resume content density

Exactly two pages is necessary but not sufficient when useful, job-relevant evidence remains. Education & Certifications should finish within approximately 0.5 inch (36 points) above the normal bottom text boundary on page two. Use distinct, source-supported accomplishments and relevant project detail, prioritizing the most relevant roles; there is no fixed two- or three-bullet ceiling. Keep standard sections, readable model typography, and normal margins/spacing. Do not fill space with larger fonts, inflated spacing, blank paragraphs, repeated claims, unrelated material, or an education footer/text box. Inspect both rendered pages and measure the final section after native Word/PDF validation. If genuinely relevant evidence is exhausted, document the reviewed evidence and explain the remaining gap; page count alone is not completion.

## Job-specific resume headline - user instruction October 26, 2026

For EVERY resume, customize the specialization/main title directly below Dave's
name to the exact job's responsibilities, priorities, and required skills. Read
`Variations of Specialization/Main Titles` in the current
`input/master-resume/master-resume-v4.docx`. These are examples, not a closed list:
select, combine, or create the best concise, natural headline supported by Dave's
actual master-resume experience. Lead with the most relevant specialization; omit
unrelated areas and unsupported expertise, seniority, credentials, or claims.
Never automatically reuse `Marketing Technology/AI | Paid Media | E-Commerce |
Analytics | Digital Marketing` across jobs. It is acceptable only when its full
emphasis is genuinely the best fit after reviewing that specific posting.

Review the headline together with the summary and supporting accomplishments,
then inspect its rendered fit in the established header and two-page layout.
The generator ranks master examples as an initial suggestion; the agent must
review suitability and may create better wording. For a custom headline, call
`scripts/gecko_v2.py`'s `set_reviewed_headline(plan, headline, rationale)` before
generation, recording why its claims are supported and relevant. Never bypass
headline validation or copy the master default into every plan. This headline is
professional positioning; preserve verified employment titles and filename/job
identity rules. Existing completed resumes are not regenerated without a request.

## Usable Google Sheets resume links - October 26, 2026

Dave explicitly selected PRIVATE GOOGLE DRIVE LINKS, usable across devices.
Every new resume's Resume Link must be a clickable HTTPS link to the exact
completed DOCX in his private Drive. Keep the validated local DOCX for job
applications. A raw local path or `file:///` URI is not usable in Google Sheets;
HYPERLINK cannot fix that unsupported protocol. This instruction supersedes all
earlier no-upload and raw-file-URI requirements for resume delivery only. Never
make resumes public, convert the validated DOCX, or share them with others.

After native Word and visual QA, upload the exact final DOCX with the connected
Google Drive `upload_file` tool, preserving its filename and DOCX MIME type. Use
the private folder configured in `job-scout/preferences/resume-delivery.json`:
`https://drive.google.com/drive/folders/1Noy8XUqlL5ufqA4aU9jZWdwpMYeCVmol`.
Reuse a verified unchanged upload instead of creating duplicates. Read back the
Drive metadata (ID, observed URL, filename, MIME type, size, parents and private
owner-only permissions), download its raw bytes and compare SHA-256 with the
local DOCX. Save a receipt JSON containing `path`, `metadata` from that readback,
and `download: {"sha256": "<actual downloaded SHA-256>"}`. Register it using
`scripts/register_resume_drive_link.py --receipt <receipt.json>`.

The canonical publisher resolves that verified receipt to its observed HTTPS
URL. Write Resume Link as a clickable Google Sheets hyperlink, verify the cell's
actual hyperlink target, and preserve completion dates, job identity, formulas,
formatting and unrelated fields. Resume Created still requires all existing QA
and completion safeguards. If the connector is unavailable, retain the finished
local file and report Private Drive publication pending; do not silently fall
back to file:/// or claim a working tracker link. Unattended queue runs without
a registered delivery receipt stop at this publication gate and need a connected
agent to perform the upload. Dashboard and applications resolve registered Drive
URLs back to the unchanged local file through `job-scout/resume_delivery.py`.

## Canadian remote jobs allowed - user instruction October 26, 2026

Dave explicitly instructed: If it is Canada, allow it. Treat Canadian remote
jobs, including Canada-only postings and country codes CA/CAN, as geographically
eligible for Gecko discovery, qualification, resume queues and tracker review.
Do not set Qualifies to Apply? to No solely because the country is Canada or the
ATS applicant country is Canadian. This supersedes earlier U.S./Utah-only remote
country restrictions for Canada. Marketbridge ID 2983 is the confirmed example.

Keep other safeguards: fees, permanent rejections, completed-resume protection,
match thresholds, usable job descriptions, and genuine additional location or
residency restrictions. Required Eastern working hours alone are not an Eastern
residency restriction. This does not authorize inventing Canadian citizenship,
work authorization, residency or willingness to relocate; answer application
questions truthfully and surface any unsupported mandatory requirement. The
exception permits remote Canada jobs; it does not make Canadian onsite/hybrid
jobs local Utah jobs or permit every other foreign-country requisition.
