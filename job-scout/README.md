# Gecko Job Scout

Job Scout is an upstream discovery module. It finds and evaluates openings, but it never creates a resume or adds an incomplete job to Gecko's application tracker.

## What it does

1. Queries configured, authorized providers.
2. Normalizes every result to the common `JobListing` contract in `models.py`.
3. Scores the role against the master resume and `preferences/default.json` across ten weighted dimensions.
4. Deduplicates cross-postings while preserving every source link.
5. Saves results and lifecycle statuses in the local SQLite database under `job-scout/data/`.
6. Shows jobs scoring 80 or higher by default, with short-source 80+ results labeled provisional.
7. On explicit selection, archives the full description in Gecko's existing `input/job-descriptions/` format and marks the job `reviewing`.

For retained Jooble results, Job Scout also resolves the discovery link before review. It keeps the original Jooble URL in source history, rejects known aggregators as application destinations, and promotes only high-confidence employer or ATS matches.

Weak matches are stored with `retained = 0` so later searches know they were seen, but `list` hides them unless `--all` is supplied.

## Configure sources

Copy the root example file to the ignored local credential file, then fill in the two Adzuna values. Job Scout loads `.env.local` automatically and never replaces values already supplied by the process environment.

```powershell
Copy-Item .env.example .env.local
notepad .env.local
```

Do not commit keys. Configure the official Adzuna and Jooble APIs with:

```dotenv
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
JOOBLE_API_KEY=
```

Remotive aggregates its official category RSS feeds and requires no API key.
Normal discovery does not use the small public API as a fallback or primary
source. The legacy API diagnostic remains available. Do not add a
`REMOTIVE_API_KEY`; neither RSS nor the legacy API requires one.

### Google Sheets tracker

Google Sheets is the canonical job tracker. Do not create or update a local Excel job tracker. Create a dedicated service account, enable the official Google Sheets API, share the spreadsheet with the service-account email as Editor, and keep its JSON key outside this repository.

Configure the ignored local environment file:

```dotenv
GOOGLE_SHEETS_SPREADSHEET_ID=your-spreadsheet-id
GOOGLE_SHEETS_CREDENTIALS_FILE=C:\path\outside\the\repository\service-account.json
GOOGLE_SHEETS_TRACKER_TAB=Job Tracker
GOOGLE_SHEETS_SCOUT_TAB=Job Scout
```

The explicit command below synchronizes Job Scout datastore values to the live Sheet:

```powershell
python job-scout/scout.py sync-sheets
```

Gecko's shared Sheets module maintains `Job Tracker` and `Job Scout` directly. It upserts applications by Job Number and Scout records by Scout ID or canonical URL, while preserving historical rows and manual `Apply?`, `Applied`, and `Contacted` entries. Routine operations write only changed Gecko-managed cells; existing row order, colors, dimensions, frozen rows, conditional formatting, and filters remain user-controlled.

Alternatively, set credentials in the current shell or a secret manager:

```powershell
# Adzuna Jobs API
$env:ADZUNA_APP_ID = "..."
$env:ADZUNA_APP_KEY = "..."

# Jooble Jobs API
$env:JOOBLE_API_KEY = "..."

# Career-page discovery; included in the normal daily run
$env:BRAVE_SEARCH_API_KEY = "..."

# Optional legacy Google Custom Search discovery; disabled by default
$env:GOOGLE_CSE_ENABLED = "false"
$env:GOOGLE_CSE_API_KEY = "..."
$env:GOOGLE_CSE_ID = "..."

# Indeed only when an authorized integration is available
$env:INDEED_API_ENDPOINT = "https://your-authorized-integration.example/jobs"
$env:INDEED_API_TOKEN = "..."
```

The default `search` source remains Adzuna. Jooble uses its official POST API and can be selected with `--provider jooble`. Remotive aggregates official feeds under `https://remotive.com/remote-jobs/feed/{category}` and can be selected with `--provider remotive`. The broken `https://remotive.com/feed` all-jobs URL is not queried. `daily` queries the core Adzuna, Jooble, Remotive, and Web Careers providers, with Brave as the primary Web Careers backend. Google CSE is an optional legacy backend and is never called unless `GOOGLE_CSE_ENABLED=true` and both Google credentials are configured. When explicitly enabled, results from both APIs use the same career-page query, are combined by URL before pages are fetched, and then enter the same `JobPosting` extraction, normalization, scoring, and deduplication pipeline. The Indeed adapter calls only the configured authorized endpoint; it does not scrape Indeed. Google Custom Search support is available only for existing customers; Google has closed it to new customers and announced discontinuation on January 1, 2027.

Remotive uses only marketing-adjacent category feeds: Marketing, Data and Analytics, Product Management, Business Development, Strategy, Communications, Account Management, Operations, and All Others. Clearly irrelevant feeds such as Software Development, DevOps, QA, Customer Service, IT, Engineering, and Artificial Intelligence are not requested by the normal RSS workflow. Every record from an adjacent or catch-all feed must also pass the title-family filter. One failed category does not abort the run. Remotive does not publish a separate E-Commerce feed, so Marketing supplies the closest official coverage.

Category records are combined and deduplicated by Remotive job ID, canonical Remotive URL, then normalized company plus title. Every encountered feed category associated with a job is retained. Relevant titles are filtered before normalization and Gecko scoring; the remaining candidates are ranked with the existing match-scoring model, and the requested number with the highest scores and background-relevance signals are imported. A relevant role does not need an exact configured target-title match.

Remotive discovery location is always `Remote`; `--location` and Utah discovery filters never apply to it. RSS `location`/candidate eligibility is preserved on the job. Worldwide, USA, North America, Northern America, Americas, and similar eligibility can enter scoring, and US-only eligibility is not required. An explicitly incompatible restriction can lower the location/work-arrangement score or flag the job for review, but does not prevent discovery.

Remotive attribution is retained throughout the pipeline: `source` is exactly `remotive`, the Remotive job ID (or a stable RSS-derived ID) and original job URL are saved, and cross-provider deduplicated records keep that provenance in their source links. Title, company, description, candidate restriction, publication date, salary, employment type, category, and tags are normalized when supplied by the feed. Job Scout never substitutes the retrieval date for Remotive's publication date. Remotive discovery never uses the generic web-search provider.

Provider references: [Remotive official RSS category list](https://remotive.com/remote-jobs/rss-feed), [Remotive public API and attribution terms](https://github.com/remotive-com/remote-jobs-api), [Brave Web Search API](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started), [Google Custom Search JSON API](https://developers.google.com/custom-search/v1/overview), and [Adzuna API overview](https://developer.adzuna.com/overview).

## Run a search

From the Gecko project root:

```powershell
python job-scout/scout.py search
python job-scout/scout.py daily
python job-scout/scout.py list
python job-scout/scout.py show 12
```

`search` uses Adzuna only by default and does not require `BRAVE_SEARCH_API_KEY`.

`daily` runs the complete Adzuna, Jooble, Remotive, and Web Careers workflow. Web Careers automatically calls Brave when `BRAVE_SEARCH_API_KEY` is configured. Google CSE is skipped unless the explicit legacy-access switch `GOOGLE_CSE_ENABLED=true` is set alongside both Google credentials. Web Careers then fetches discovered pages and extracts schema.org `JobPosting` data. The workflow also performs pre-score role filtering, link availability checks, cross-provider deduplication, scoring, Adzuna enrichment for newly discovered provisional 80+ results, tracker synchronization, and a current-run review queue. It never creates a resume or starts a Gecko handoff.

At the start of each daily run, Job Scout checks existing active jobs, then validates each new listing URL before scoring or insertion. It follows redirects and favors known employer/ATS links; Greenhouse and Lever job-specific APIs provide additional authoritative absence checks. A final 404/410 or an explicit loaded-page closure notice confirms expiry. HTTP 403, 429, 5xx, bot protection, DNS/connection errors, and timeouts are temporary and leave the job in place for the next run. Confirmed-dead unselected jobs are cleared from their Scout row in place and removed from SQLite only after sheet synchronization succeeds. Selected, resume-created, and applied/contacted jobs and all `Job Tracker` application records remain intact. The command prints checked, valid, removed-dead, temporary-failure, and protected-dead counts plus details for every removed job.

Duplicate discoveries are reported under `existing_job_ids` and are not merged into, rescored, or rewritten in the daily path. New records are reported under `new_job_ids`. Only those new records are eligible for worksheet insertion and the daily review. The daily run colors the `Scout ID` cells light green for rows whose `Date Found` is that day, including rows added earlier the same day; earlier highlights remain in place. Aside from confirmed-dead unprotected rows and this requested ID color, existing Google `Job Scout` values and manual `Apply?`, `Applied`, and `Contacted` entries stay intact. If no new jobs qualify, the command prints `DAILY REVIEW: No new qualifying jobs were discovered in this run.`

The pre-score title filter also excludes roles whose titles explicitly require fluent Spanish, even when the rest of the title matches a target marketing role.

The standalone `search` command keeps its general upsert behavior. Both `search` and `daily` write directly to Google Sheets and fail clearly if it is unavailable.

Narrow a search or query a single provider:

```powershell
python job-scout/scout.py search --query "Paid Search Manager" --query "Marketing Analytics Manager" --location "Utah" --results 20
python job-scout/scout.py search --provider jooble
python job-scout/scout.py search --provider remotive --limit 100
python job-scout/scout.py diagnose-remotive
python job-scout/scout.py diagnose-remotive-feeds --limit 100
python job-scout/scout.py diagnose-remotive-rss
```

Every `search`/`daily` run includes a `source_counts` object in its JSON summary, including zeroes for skipped or failed selected sources. The summary also includes `filtered_before_scoring`, `newly_discovered`, `already_existed`, `new_job_ids`, and `existing_job_ids`, making the current run's state explicit. For Web Careers, `source_diagnostics.web-careers` reports configured/used backends, the exact generated queries, per-backend result and page counts, valid `JobPosting` extraction counts, jobs added, and credential-safe API/page errors. The top-level `google_cse` object reports `enabled`, `active`, `used`, `skipped`, `skip_reason`, `results_fetched`, `qualifying`, `added`, and `errors`. With the default `GOOGLE_CSE_ENABLED=false`, Google is reported as skipped with reason `disabled` and no API call or repeated 403 errors occur. Failures raised outside backend-isolated Web Careers acquisition remain visible in `source_errors`.

`diagnose-remotive` is read-only and calls only `https://remotive.com/api/remote-jobs`; it does not invoke Indeed, LinkedIn, ZipRecruiter, any other provider, or generic web search. By default it checks digital marketing, paid search, PPC, and marketing analytics, then reports raw API records, unique query matches, jobs passing Gecko's score threshold, jobs surviving comparison with saved non-Remotive sources, and example Remotive URLs. Override the threshold with `--minimum-score` or repeat `--query` for a narrower check.

`diagnose-remotive-feeds --limit 100` is read-only. It dry-runs the same marketing-adjacent RSS loading, deduplication, title-family filtering, local scoring, and relevance ranking used by search. It reports feeds attempted/successful/failed, raw RSS records, duplicates removed, relevant unique jobs available, the number that would be imported, and the 80+/70-79/below-70 score bands. It does not call the public API. `diagnose-remotive-rss` remains as a backward-compatible alias. Neither command saves jobs or synchronizes tracker worksheets.

The default search runs every target title in `preferences/default.json` for both Utah and Remote against Adzuna. Use explicit `--query` or repeated `--location` values to reduce or customize those calls. `daily` uses that request set for Adzuna, Jooble, and Web Careers, while Remotive ignores title/location requests and uses its Remote RSS workflow with a 100-unique-job import limit. Indeed remains an explicit opt-in through `--source` or `--provider`.

Useful review commands:

```powershell
python job-scout/scout.py list --status new
python job-scout/scout.py list --minimum-score 90
python job-scout/scout.py list --all --minimum-score 0
python job-scout/scout.py status 12 ignored
```

## Review queue

Use the read-only review queue to see which jobs are worth considering before selecting one:

```powershell
python job-scout/scout.py review
python job-scout/scout.py review --confirmed-only
python job-scout/scout.py review --minimum-score 75
python job-scout/scout.py review --limit 20
python job-scout/scout.py review --json
```

The queue shows confirmed strong matches first, provisional 80+ matches second, and near matches from the requested minimum through 79 last. Within each section, jobs sort by Match Score, Evidence Confidence, and newest posting date. The limit applies across the whole prioritized queue and defaults to 20.

Every review entry shows URL Status independently from Match Score and Evidence Confidence. A high-fit job can therefore remain highly scored while being labeled `Jooble redirect only`, `Stale / authoritative posting not found`, or `Stale / unavailable`.

## Authoritative application URLs

URL resolution follows provider redirects safely, classifies the destination, checks the page against the normalized company/title/location, and searches configured career-page discovery when an intermediary or dead link cannot be used. Verified links are prioritized in this order: employer careers page, official ATS, direct employer listing, enriched source, then the original provider URL. Candidate selection requires a high confidence score and rejects ambiguous ties.

The configurable host patterns are in `preferences/url_resolution.json`. The intermediary list includes Fitly, Jooble, Adzuna, Indeed, LinkedIn, ZipRecruiter, and other known aggregators. ATS patterns include Greenhouse, Lever, Workday, Ashby, SmartRecruiters, iCIMS, Jobvite, BambooHR, ClearCompany/HRMDirect, and other supported systems.

Resolution metadata is stored separately from fit scoring: URL verification status, authoritative URL, confidence, destination type, redirect URL, resolution timestamp, and error detail. Existing databases migrate additively. The `Job Scout` worksheet includes managed `URL Status` and `Authoritative URL` columns while continuing to preserve reordered/custom columns, formulas, and manual lifecycle fields.

Resolve one saved job or a bounded batch of unresolved Jooble jobs:

```powershell
python job-scout/scout.py resolve-url 329
python job-scout/scout.py resolve-url --jooble --limit 20
```

Authoritative search uses the existing Brave Search or legacy Google CSE configuration. Redirect verification and authoritative links already present in cross-provider source history work without a search key.

Jobs marked `applied`, `rejected`, or `ignored` are excluded by default. Use `--include-closed` when an explicit review of those statuses is needed. Reviewing is read-only: it never selects a job, creates a resume, or changes the application tracker. Continue to use `python job-scout/scout.py select <ID>` for an explicit Gecko handoff.

## Job Scout worksheet

The `Job Scout` worksheet contains active discovery and scoring records separately from the `Job Tracker` application worksheet in the same Google spreadsheet. The daily run appends only identities first discovered in that run and clears only confirmed-dead, unprotected Scout rows. Other explicit workflows can still upsert managed fields by Scout ID or canonical URL. `Apply? = Yes` is a user-maintained selection and is protected from dead-link cleanup, along with marked `Applied` and `Contacted` entries; unchecked checkboxes do not count as marks.

Job Scout does not delete/recreate worksheets, delete/rebuild existing data rows, sort physical rows, or reapply default formatting. Confirmed-dead unprotected rows have only managed values cleared in place, leaving row positions and formatting intact. Existing colors, dimensions, panes, filters, conditional formatting, data validation, hyperlinks on surviving rows, formulas, and user-defined columns are retained.

Review output is ranked by Match Score, Evidence Confidence, and newest posting date without physically reordering persistent worksheet rows. User-created conditional formatting remains authoritative. Selecting a job changes its Scout lifecycle to `Selected`; the existing completed-resume tracker command later marks the same Scout row `Resume Created` when the archived description contains its Scout ID.

## Enrich provisional matches

When an Adzuna result scores 80 or higher from an abbreviated description, Job Scout attempts to enrich it before counting it as confirmed. Enrichment follows the existing provider URL and prefers an official company career page with schema.org `JobPosting` JSON-LD. It can also use semantic `main`, `article`, or `itemprop="description"` content when structured data is unavailable. It does not use browser automation or visual-page selectors.

Enrich one eligible job or retry all provisional 80+ jobs:

```powershell
python job-scout/scout.py enrich 62
python job-scout/scout.py enrich --provisional
```

The original Adzuna description, URL, Match Score, and Evidence Confidence are preserved. Job Scout separately stores the enriched description, source URL, timestamp, status/error, enriched score, and enriched confidence. Failed enrichment leaves the listing provisional and retained for review.

An enriched listing is a confirmed strong match only when its final Match Score is at least 80 and its Evidence Confidence is at least 65%. Otherwise an 80+ listing remains labeled `80+ provisional — full description recommended`.

## Select a job for Gecko

```powershell
python job-scout/scout.py select 12
```

This creates `input/job-descriptions/<Company>+<JobNumber>.md`, creates the required job-specific scratch directory, synchronizes the worksheet, and changes the Scout status to `selected`. It does not generate a resume. Tell the agent:

> Use Gecko for the saved Job Scout description at `input/job-descriptions/<file>.md`.

The normal Gecko workflow then creates and validates the two final deliverables. Its existing final tracker command adds the completed job. The tracker now appends `Source`, `Date Found`, and `Status` columns to its established schema; legacy workbooks are migrated without changing existing rows or the manual `Applied` and `Contacted` values.

## Scoring

The 100 points are allocated to role/domain relevance (15), responsibilities/required skills (15), paid media/performance marketing (14), analytics/measurement (11), e-commerce/SEO/transferable digital marketing (10), martech/automation/AI (10), years/seniority/scope (8), leadership/management (10), location/work arrangement (4), and education/certifications (3).

Each dimension is classified as a direct match, related/transferable match, unknown because the source is incomplete, weak match, or true mismatch. Missing evidence in abbreviated Adzuna snippets receives neutral credit rather than being treated as a mismatch. Job Scout also stores a separate evidence-confidence score. Any 80+ result based on abbreviated or low-confidence source text is labeled `provisional` with the recommendation to review the full description; it is not counted as a confirmed strong match.

Recalculate saved jobs after a scoring-model update without calling a provider:

```powershell
python job-scout/scout.py rescore
```

The candidate evidence in `preferences/default.json` is grounded only in `input/master-resume/Dave-Call-resume-9-23-26.docx`. The current DOCX is read during every search and rescore. Update candidate preferences only when the current master DOCX supports the change; the older PDF and formatting reference are not evidence.

## Add another provider

Implement `sources.base.JobSource`, return `RawListing` records, export the provider from `sources/__init__.py`, and register it in `scout.py`. Normalization, scoring, deduplication, storage, and selection then work unchanged. Prefer an official API, approved integration, feed, or structured career-page data.

## Test

```powershell
python -m unittest discover -s job-scout/tests -v
python -m unittest discover -s job-scout/tests -p "test_remotive.py" -v
python scripts/manage_job_tracker.py init
python scripts/verify_google_tracker.py --job-number <known-job-number>
```
