# Gecko Job Scout

Job Scout discovers role-relevant openings and records them in the canonical Google Sheet. It does not calculate compatibility ratings or use an evaluation field to decide whether a resume may be created.

## Daily workflow

```powershell
python job-scout/scout.py daily
```

The daily command:

1. validates known active links;
2. concurrently searches every enabled API, feed, ATS, and search-discovery source;
3. processes unassigned Indeed URLs manually pasted into Column R (`Job URL`);
4. rejects Jooble records;
5. applies the existing role-family filter to automated discovery;
6. deduplicates by stable provider identity, URL, and deterministic company/title/location identity;
7. appends automated discoveries and populates valid manual Indeed rows;
8. runs Gecko for new rows where `Apply?` is `Yes` and `Resume Created` is blank;
9. checks Gmail read-only for substantive employer responses to applied jobs and updates `Response`.

`python job-scout/scout.py daily --dry-run` uses a temporary SQLite copy and does not write the Google Sheet, descriptions, resumes, or reports. A failure for one job is logged without stopping later jobs.

The standalone retry command remains:

```powershell
python scripts/generate_apply_queue.py
```

It reads columns by header name, requires `Apply? = Yes`, requires a blank `Resume Created`, and never depends on a compatibility rating.

## Manual Indeed workflow

1. Find a job manually on Indeed.
2. Copy the Indeed job URL (a `viewjob` URL containing `jk` is preferred).
3. Paste it into Column R (`Job URL`) of a new `Job Scout` row.
4. Run the normal `python job-scout/scout.py daily` command.
5. Gecko checks the complete Sheet and local datastore for the same Indeed `jk`, canonical URL, or exact normalized company/title/location identity.
6. If the job is new, Gecko retrieves the structured posting, populates the existing row, assigns the next never-used numeric Scout ID, and includes it in the normal review/resume queue. `Apply?` remains user-owned; set it to `Yes` if the row should produce a resume.
7. If it is a duplicate, Gecko leaves the pasted URL in Column R, writes `Duplicate — Scout ID ...` in `Notes`, and does not allocate an ID, retrieve it again, or create a resume.

Indeed can return a block page or omit usable structured posting data. In that case Gecko leaves the URL intact, allocates no Scout ID, writes `Indeed retrieval failed — manual review required` in `Notes`, and continues with later rows. Duplicate and failed rows are terminal/idempotent; after correcting a URL or when intentionally retrying a transient failure, clear Gecko's message from `Notes` before the next daily run.

Job Scout currently has no numerical match-score field or automatic apply recommendation. Manual Indeed jobs follow that same architecture: Gecko does not invent a score and does not overwrite `Apply?`.

## Google Sheet schema

The active `Job Scout` schema is:

1. Scout ID
2. Source
3. Company
4. Job Title
5. Gecko Status
6. Apply?
7. Resume Created
8. Applied
9. Notes
10. Response
11. Location
12. Work Arrangement
13. Employment Type
14. Salary
15. Date Posted
16. Date Found
17. Last Seen
18. Job URL
19. Resume Link

The schema migration deletes the retired original columns J, K, L, M, V, X, and Y in place. Future writes are restricted to the headers above and never recreate or repurpose those retired columns. User formatting, filters, manual values, checkboxes, hyperlinks, and row order remain in place because writes target specific cells and structural migration uses native column deletion.

## Configuration

Copy `.env.example` to `.env.local` and configure the provider and Google Sheets credentials. The default queries live in `preferences/default.json`; they contain search preferences only.

Provider enablement and ATS employers are configured in `preferences/job-sources.json`. Override the file with `JOB_SCOUT_SOURCES_CONFIG` or override one provider with `JOB_SCOUT_<PROVIDER>_ENABLED=true|false` (hyphens become underscores). The normal `core` source set contains every supported provider. Providers requiring credentials automatically report `missing credentials` until configured.

### Supported sources

| Source | Acquisition | Credentials/configuration |
|---|---|---|
| Adzuna | Official Jobs API | `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` |
| Remotive | Official category RSS | None |
| Web Careers / Brave | Brave Search plus public structured career pages | `BRAVE_SEARCH_API_KEY` |
| Jobicy | Public remote-jobs API | None |
| Remote OK | Public JSON feed | None |
| USAJOBS | Official Search API | `USAJOBS_API_KEY`, `USAJOBS_EMAIL` |
| Greenhouse | Public Job Board API | Employer board tokens in source config |
| Lever | Public Postings API | Employer site names in source config |
| Ashby | Public lightweight job-posting API | Employer board slugs in source config |
| Workable | Public published-jobs endpoint | Employer account subdomains in source config |
| We Work Remotely | Official Sales & Marketing RSS | None |
| Working Nomads | Unsupported/disabled safely | No supported public API/feed is documented |
| The Muse | Public Jobs API | `THE_MUSE_API_KEY` |
| Indeed | Authorized API when configured; otherwise Brave public-page discovery | Optional `INDEED_API_ENDPOINT` and `INDEED_API_TOKEN`, or Brave |
| LinkedIn | Brave discovery of public indexed job-detail pages | `BRAVE_SEARCH_API_KEY` |
| Glassdoor | Brave discovery of public indexed job-detail pages | `BRAVE_SEARCH_API_KEY` |
| ZipRecruiter | Brave discovery of public indexed job-detail pages | `BRAVE_SEARCH_API_KEY` |

Search-discovery providers never log in, reuse cookies, bypass CAPTCHAs, rotate proxies, or evade anti-bot controls. A discovered page is accepted only when it exposes usable public `JobPosting` structured data. Otherwise it is skipped and reported.

Jooble is intentionally absent from the provider registry and cannot be enabled. Configuration validation rejects `jooble.enabled=true`, and existing defensive checks continue rejecting Jooble URLs and attribution.

### Adding ATS employers

Edit only the `companies` arrays in `preferences/job-sources.json`; provider code does not need to change:

```json
{
  "providers": {
    "greenhouse": {"enabled": true, "companies": [{"name": "Acme", "token": "acme"}]},
    "lever": {"enabled": true, "companies": [{"name": "Acme", "site": "acme", "region": "global"}]},
    "ashby": {"enabled": true, "companies": [{"name": "Acme", "board": "Acme"}]},
    "workable": {"enabled": true, "companies": [{"name": "Acme", "account": "acme"}]}
  }
}
```

Use the identifier from the employer's public hosted career URL. Lever accepts `region: "eu"` for EU-hosted sites; omit it for the global endpoint. A failing employer board is logged without preventing other employers or providers from completing.

### Deduplication and source preference

Gecko removes tracking parameters and sorts remaining identity parameters before URL comparison. It checks canonical application URLs, provider IDs/source links, exact punctuation-insensitive company/title/location identity, posting dates, and conservative title/company/description similarity. Source links remain attached to the persistent job record so a later provider does not create another Sheet row.

When a duplicate arrives from a stronger source, the existing Scout ID is retained while the canonical record is promoted in this order: direct ATS/career page, official job-board API/feed, aggregator API, search-discovery copy. Previously seen jobs remain in SQLite with their stable IDs and are not re-added on later runs.

### Source health and verification

Every search prints per-provider counts and one of: `success`, `no results`, `disabled`, `missing credentials`, `rate limited`, `api error`, `unsupported`, or `search-discovery fallback`. It also reports duplicates, previously seen jobs, central role-filter rejections, and newly written jobs.

Run a read-only live source check without touching Google Sheets:

```powershell
python job-scout/scout.py verify-sources
```

Automated tests mock all network calls; the verification command is the optional live check. Public feeds are cached within a run, acquisition uses bounded concurrency, all HTTP requests use the shared timeout, and datastore/Sheet writes remain serialized.

Gmail response tracking requires a Desktop app OAuth client and only the `gmail.readonly` scope. Save the downloaded client JSON as `.secrets/gmail-oauth-client.json`, install `job-scout/requirements.txt`, and run `python job-scout/gmail_response_tracker.py authorize` once from an interactive terminal. The ignored refresh token and processing state are reused by later daily runs. Each run issues one seven-day Gmail search, locally matches its results against all applied jobs, and delays `0.2` seconds between message downloads by default. Configure that pacing with `GECKO_GMAIL_REQUEST_DELAY_SECONDS`. See the root `README.md` for the complete Google Cloud setup.

## Commands

```powershell
python job-scout/scout.py search --source core
python job-scout/scout.py list
python job-scout/scout.py list --status new
python job-scout/scout.py review --limit 20
python job-scout/scout.py review --json
python job-scout/scout.py show 123
python job-scout/scout.py select 123
python job-scout/scout.py status 123 applied
python job-scout/scout.py enrich 123
python job-scout/scout.py enrich --all
python job-scout/scout.py resolve-url 123
python job-scout/scout.py sync-sheets
python job-scout/scout.py verify-sources
python job-scout/gmail_response_tracker.py authorize
python job-scout/gmail_response_tracker.py check
```

`review` is newest-first and read-only. `select` archives the job description for Gecko. Enrichment retrieves a fuller legitimate description without reclassifying or rating the job.

## Resume handoff

Gecko evaluates the job description directly against the current master archive (`input/master-resume/Dave-Call-Resume.txt`) while building the tailoring plan. It produces:

- an exactly two-page DOCX after native Microsoft Word validation;
- a qualitative Match Analysis report with strengths, gaps, ATS terms, resume emphasis, and interview considerations.

No numerical compatibility value is required before generation. The completed resume is recorded only after both files exist and native QA passes.

## Data preservation

SQLite stores discovery evidence, source links, lifecycle state, enrichment text, and URL-resolution metadata. Schema migration removes obsolete evaluation columns from existing databases while preserving job records and relationships.

Google Sheet operations update only managed cells by header name. Existing `Apply?`, `Applied`, `Contacted`, formatting, formulas, filters, conditional formatting, colors, hyperlinks, widths, frozen panes, and manual fields remain user-owned. Gmail tracking updates only `Response`, refuses ambiguous matches, and preserves a useful existing response unless a newer message is at the same or a later hiring stage.

## Tests

```powershell
python -m unittest discover -s job-scout/tests -p "test_*.py" -v
python -m unittest discover -s scripts -p "test_*.py" -v
```

The regression suite covers schema migration idempotence, header-based writes, discovery without evaluation fields, daily orchestration, and resume creation without rating data.
