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

Weak matches are stored with `retained = 0` so later searches know they were seen, but `list` hides them unless `--all` is supplied.

## Configure sources

Copy the root example file to the ignored local credential file, then fill in the two Adzuna values. Job Scout loads `.env.local` automatically and never replaces values already supplied by the process environment.

```powershell
Copy-Item .env.example .env.local
notepad .env.local
```

Do not commit keys. The only required entries for normal Adzuna operation are:

```dotenv
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
```

Alternatively, set credentials in the current shell or a secret manager:

```powershell
# Adzuna Jobs API
$env:ADZUNA_APP_ID = "..."
$env:ADZUNA_APP_KEY = "..."

# Optional career-page discovery; not used by the default search
$env:BRAVE_SEARCH_API_KEY = "..."

# Legacy alternative for existing Google Custom Search customers
$env:GOOGLE_CSE_API_KEY = "..."
$env:GOOGLE_CSE_ID = "..."

# Indeed only when an authorized integration is available
$env:INDEED_API_ENDPOINT = "https://your-authorized-integration.example/jobs"
$env:INDEED_API_TOKEN = "..."
```

The default search source is Adzuna. Brave is optional and is never queried unless `--source web-careers` or `--source all` is explicitly requested. The Indeed adapter calls only the configured authorized endpoint; it does not scrape Indeed. The optional web provider uses Brave Search to discover career URLs, then reads public schema.org `JobPosting` JSON-LD from those pages instead of depending on visual page selectors. Legacy Google Custom Search support is available only for existing customers; Google has closed it to new customers and announced discontinuation on January 1, 2027.

Provider references: [Brave Web Search API](https://api-dashboard.search.brave.com/app/documentation/web-search/get-started), [Google Custom Search JSON API](https://developers.google.com/custom-search/v1/overview), and [Adzuna API overview](https://developer.adzuna.com/overview).

## Run a search

From the Gecko project root:

```powershell
python job-scout/scout.py search
python job-scout/scout.py daily
python job-scout/scout.py list
python job-scout/scout.py show 12
```

`search` uses Adzuna only by default and does not require `BRAVE_SEARCH_API_KEY`.

`daily` runs the complete Adzuna workflow: search, deduplicate, score, enrich provisional 80+ results, synchronize the `Job Scout` worksheet in `output/job-tracker.xlsx`, and display the review queue. It never creates a resume. The `search` command also synchronizes the worksheet after a successful run.

Narrow a search or query a single provider:

```powershell
python job-scout/scout.py search --query "Paid Search Manager" --query "Marketing Analytics Manager" --location "Utah" --results 20
```

The default search runs every target title in `preferences/default.json` for both Utah and Remote against Adzuna. API usage therefore equals target titles × two locations. Use explicit `--query` or repeated `--location` values to reduce or customize calls. Other providers remain explicit opt-ins through `--source`.

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

Jobs marked `applied`, `rejected`, or `ignored` are excluded by default. Use `--include-closed` when an explicit review of those statuses is needed. Reviewing is read-only: it never selects a job, creates a resume, or changes the application tracker. Continue to use `python job-scout/scout.py select <ID>` for an explicit Gecko handoff.

## Job Scout worksheet

The `Job Scout` worksheet in `output/job-tracker.xlsx` contains discovery and scoring history separately from the existing `Job Tracker` application worksheet. Syncing upserts jobs by Scout ID and canonical URL, updates changing score/evidence fields, preserves older jobs that no longer appear in search results, and never clears manual `Applied` or `Contacted` entries.

The worksheet is sorted by Match Score, Evidence Confidence, and newest posting date. Confirmed strong matches, near matches, and closed lifecycle states use distinct conditional formatting. Selecting a job changes its Scout lifecycle to `Selected`; the existing completed-resume tracker command later marks the same Scout row `Resume Created` when the archived description contains its Scout ID.

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

The candidate evidence in `preferences/default.json` is grounded in `input/master-resume/dcall-resume-3-15-26.pdf`. The PDF itself is also read during every search. Update preferences only when the master resume or explicit Gecko notes support the change.

## Add another provider

Implement `sources.base.JobSource`, return `RawListing` records, export the provider from `sources/__init__.py`, and register it in `scout.py`. Normalization, scoring, deduplication, storage, and selection then work unchanged. Prefer an official API, approved integration, feed, or structured career-page data.

## Test

```powershell
python -m unittest discover -s job-scout/tests -v
python scripts/manage_job_tracker.py --tracker scratch/job-scout-tracker-test.xlsx init
python scripts/manage_job_tracker.py --tracker scratch/job-scout-tracker-test.xlsx validate
```
