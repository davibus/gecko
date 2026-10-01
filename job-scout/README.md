# Gecko Job Scout

Job Scout discovers role-relevant openings and records them in the canonical Google Sheet.

## Daily workflow

```powershell
python job-scout/scout.py daily
```

The daily command:

1. validates known active links;
2. concurrently searches every enabled API, feed, ATS, and search-discovery source;
3. processes unassigned Indeed URLs manually pasted into Column R (`Job URL`);
4. rejects Jooble records;
5. applies configurable title, location, work-arrangement, employment-type, category, and compensation hard filters;
6. deduplicates by provider job ID, canonical URL, normalized company/title/location, then fuzzy evidence;
7. reuses persistent AI results when the normalized description and candidate profile are unchanged;
8. when AI models are configured, performs compact-profile triage and fully scores only `possible`/`strong` jobs;
9. appends automated discoveries and populates valid manual Indeed rows;
10. runs Gecko automatically for every eligible incomplete live row across all sources; qualifying Utah/remote rows are set to `Apply? = Yes`, short descriptions are accepted, failures are written specifically to Column I for later retry, and success writes X to G while clearing only Gecko's prior failure message;
11. checks Gmail read-only for substantive employer responses to applied jobs and updates `Response`.

`python job-scout/scout.py daily --dry-run` uses a temporary SQLite copy and does not write the Google Sheet, descriptions, resumes, or reports. A failure for one job is logged without stopping later jobs.

The standalone retry command remains:

```powershell
python scripts/generate_apply_queue.py
```

The normal command is `python job-scout/scout.py daily`. It automatically reuses the canonical queue after discovery, reads columns by header name, evaluates existing rows from every source, recognizes canonical `X` and prior `C` completion markers, and preserves unrelated cells.

## Manual Indeed workflow

1. Find a job manually on Indeed.
2. Copy the Indeed job URL (a `viewjob` URL containing `jk` is preferred).
3. Paste it into Column R (`Job URL`) of a new `Job Scout` row.
4. Run the normal `python job-scout/scout.py daily` command.
5. Gecko checks the complete Sheet and local datastore for the same Indeed `jk`, canonical URL, or exact normalized company/title/location identity.
6. If the job is new, Gecko retrieves the structured posting, populates the existing row, assigns the next never-used numeric Scout ID, and includes it in the normal review/resume queue. During `daily`, Gecko sets Apply? to `Yes` when Location is in Utah or Work Arrangement explicitly permits remote work, just as it does for every other source.
7. If it is a duplicate, Gecko leaves the pasted URL in Column R, writes `Duplicate — Scout ID ...` in `Notes`, and does not allocate an ID, retrieve it again, or create a resume.

Indeed can return a block page or omit usable structured posting data. A new row tries the pasted Indeed page once, then searches configured Web Careers backends by `jk` and canonical Indeed URL. If indexed Indeed evidence identifies the role, Gecko accepts an employer careers posting only when title, company, and available location evidence match strongly. The pasted Indeed URL remains in Column R and the confirmed employer URL is retained internally. Only after all configured fallbacks fail does Gecko allocate no Scout ID, write `Indeed retrieval failed — manual review required` with per-stage diagnostics in `Notes`, and continue with later rows.

Failed Indeed rows are retried automatically on later daily runs through fallback search first; Gecko does not repeat the previously blocked direct Indeed request. To retry `jk=3736ea0494f752a7`, leave its URL and failure note in place and run `python job-scout/scout.py daily` again. Duplicate notes remain terminal and are not retried.

Outside the all-source Utah/remote eligibility rule, Job Scout preserves the user-maintained `Apply?` decision. Manual Indeed jobs follow the same architecture. The daily column mapping is F = `Yes` for Utah or remote jobs, G = `X` after successful resume creation, and S = the absolute local DOCX path.

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

Copy `.env.example` to `.env.local` and configure the provider and Google Sheets credentials. Queries, deterministic filters, and AI payload limits live in `preferences/default.json`. A missing salary never causes Gecko to invent compensation; the configured salary floor applies only when a usable salary is present.

AI screening is optional and disabled when either screening model is blank. Configure it with `JOB_SCOUT_TRIAGE_MODEL` and `JOB_SCOUT_SCORING_MODEL`; `GECKO_RESUME_MODEL` independently reserves the strongest model choice for final tailoring. The API client uses `OPENAI_API_KEY` and optionally `OPENAI_BASE_URL`. Stage 1 returns only `relevance` and `reason`; Stage 2 returns `match_score`, `apply`, and `reason`. Results are cached in SQLite by normalized description hash, compact-profile hash, and model pair. The compact profile is in `preferences/candidate-profile.json` and is SHA-256-bound to the current master resume, so a changed master cannot silently use a stale profile. Final Gecko generation still rereads the full master resume and required model PDF.

Source concurrency and volume are bounded by `JOB_SCOUT_SOURCE_CONCURRENCY` and `JOB_SCOUT_MAX_RESULTS_PER_SOURCE`, or their checked-in equivalents in `preferences/job-sources.json`. Providers are fetched concurrently, but each provider retains its own HTTP retry/rate-limit behavior. Results are sorted newest-first before the per-source cap is applied.

AI decisions and scores stay in the persistent local evaluation cache because the live Sheet has no AI-owned columns. Job Scout never overwrites the manual `Apply?`, `Notes`, `Applied`, `Contacted`, or `Response` fields.

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

### Maintaining the ATS employer universe

The saved ATS employer universe is a curated watch list of direct-employer boards worth checking on every Job Scout run. Direct Greenhouse, Lever, Ashby, and Workable feeds provide stable employer-owned listings without relying on an aggregator copy. The list emphasizes U.S.-remote and Utah-accessible employers, agencies, SaaS, ad-tech/mar-tech, e-commerce, consumer brands, and other organizations that repeatedly hire senior digital, performance, analytics, operations, acquisition, lifecycle, or demand-generation marketers.

Employer discovery is a separate maintenance operation. It never runs as part of `python job-scout/scout.py daily`, avoiding daily Brave usage, excess ATS traffic, slow runs, and unstable configuration changes. Run it explicitly:

```powershell
# Discover and validate without changing job-sources.json
python job-scout/discover_ats_employers.py --dry-run

# Revalidate, rank, and merge validated employers
python job-scout/discover_ats_employers.py --apply

# Periodic revalidation plus discovery of newly indexed boards
python job-scout/discover_ats_employers.py --refresh --dry-run

# Bounded or platform-specific maintenance
python job-scout/discover_ats_employers.py --dry-run --platform ashby --limit 20
```

The utility extracts identifiers only from recognized public hosted URLs, validates the corresponding public provider endpoint, applies employer-relevance rules separately from Job Scout's role filtering, deduplicates by platform/identifier/name, and writes detailed diagnostics to the ignored generated file `data/ats-employer-discovery.json`. A completed dry-run is carried into a later apply and every board is revalidated. Search errors, malformed responses, redirects, duplicate candidates, open/relevant/U.S./remote job counts, examples, and repeated failure counts remain in the diagnostic output. Existing manually configured entries are preserved even when validation fails; a single temporary failure never deletes an employer.

Curated URLs in `preferences/ats-employer-seeds.json` supplement public search when an index or API quota is incomplete. They are not trusted blindly: the identifier is extracted from the stored hosted URL and the board must pass the same live endpoint validation before selection.

To add an employer manually, first open its actual hosted board and copy the first path segment after the provider domain. Do not derive it from the company name:

- Greenhouse: `https://job-boards.greenhouse.io/<token>` becomes `{"name": "Acme", "token": "<token>"}`.
- Lever: `https://jobs.lever.co/<site>` becomes `{"name": "Acme", "site": "<site>"}`.
- Ashby: `https://jobs.ashbyhq.com/<board>` becomes `{"name": "Acme", "board": "<board>"}`.
- Workable: `https://apply.workable.com/<account>` becomes `{"name": "Acme", "account": "<account>"}`.

Add the hosted URL to the seed file and run a dry-run followed by apply, or carefully add the object to the matching `companies` array and run `--refresh --dry-run`. Never add a board that requires login, presents a CAPTCHA, redirects to an unrelated employer, or cannot be confirmed through the public provider response.

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

Gecko evaluates the job description directly against the required master archive (`input/master-resume/Dave-Call-Resume.txt`) while building the tailoring plan. Resume generation uses `input/master-resume/MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf` as the required visual formatting/layout model. The V2 pipeline stops without fallback if either file is missing. It produces:

- an exactly two-page DOCX after native Microsoft Word validation.

The completed resume is recorded only after the DOCX exists directly under `output/resumes`, native QA passes, and its absolute local path is written to the canonical Sheet. The daily queue marks Column G with canonical `X`; prior `C` remains recognized. Fixed Column S contains the local DOCX path as plain text. A completed row with blank or invalid S is safely repaired from a uniquely identified existing DOCX or rebuilt through the same validated workflow without generating a duplicate resume. The Google Sheet remains the source of truth; no local Excel tracker or Google Drive resume copy is used.

## Data preservation

SQLite stores discovery evidence, source links, lifecycle state, enrichment text, and URL-resolution metadata. Schema migration keeps canonical columns while preserving job records and relationships.

Google Sheet operations update only managed cells by header name. Existing `Apply?`, `Applied`, `Contacted`, formatting, formulas, filters, conditional formatting, colors, hyperlinks, widths, frozen panes, and manual fields remain user-owned. Gmail tracking updates only `Response`, refuses ambiguous matches, and preserves a useful existing response unless a newer message is at the same or a later hiring stage.

## Tests

```powershell
python -m unittest discover -s job-scout/tests -p "test_*.py" -v
python -m unittest discover -s scripts -p "test_*.py" -v
```

The regression suite covers schema migration idempotence, header-based writes, discovery, daily orchestration, and resume creation.
