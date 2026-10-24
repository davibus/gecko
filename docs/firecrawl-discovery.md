# Firecrawl smart discovery

Updated October 22, 2026: paid usage and daily discovery are **enabled** at Dave's
request. All callers share the existing 200-credit daily admission limit and
durable ledger; enabling discovery does not create a clock-based schedule.

Search targets employer/ATS postings and rejects generic search pages, talent
pools and obviously old dated URLs before paid extraction. Exact public ATS
endpoints supply full descriptions and original posting dates without Firecrawl
scrape charges where available. Greenhouse `updated_at` is never an original
posting date in this path. Paid checks rotate after two pages per query round,
preserving admission capacity for all remaining groups. Explicit website-specific
restrictions skip that website without retry/bypass; unexplained 403s and account,
payment or rate failures still stop paid work. Failed-request reservations remain.

## Read-only audit

The existing integration used REST through `sources/firecrawl.py`, not an installed
Firecrawl SDK. It called `/v2/scrape` for supplied URLs; it did not use Firecrawl
web search or full-site crawling. Brave supplied LinkedIn, Glassdoor, ZipRecruiter
and fallback search URLs. Indeed used Firecrawl to read public result/detail pages.
Remote's employer page and WebCareerProvider could also use Firecrawl retrieval.
The dashboard's company-website helper uses the same client and is budgeted too.

All 18 configured providers were inspected: Adzuna, Remotive, web-careers,
remote-careers, Jobicy, RemoteOK, USAJobs, Greenhouse, Lever, Ashby, Workable,
We Work Remotely, Working Nomads, The Muse, Indeed, LinkedIn, Glassdoor and
ZipRecruiter. Existing role preferences, provider settings and employer seeds
were preserved. Jooble remains excluded. Sixteen configured marketing role titles
cover the requested job families; queries are grouped from those preferences.

Existing safeguards include `normalize.posting_identity`, canonical URLs,
source-qualified IDs, `source_links`, content-based deduplication, permanent
rejections, eligibility/Cost/expiration checks and stable tracker IDs. The discovery
database contained 1,147 jobs and 1,224 source links at audit time; the workspace
also contained archived records, applied/manual jobs, attachments and run history.
Existing Firecrawl response caches were process-local, with no shared credit ledger.
Request-count/pacing diagnostics existed, but not durable bill reconciliation.

The current path is `Gecko` task -> `scripts/run_gecko.py` ->
`scripts/gecko_daily.py --apply --sync-local` -> `job-scout/scout.py daily`.
The parent acquires `run_lock`; smart discovery also has an OS-backed lock that
releases after a crash. The existing Gecko task had no clock trigger. The Word
bridge tasks have separate logon triggers and were not changed.

The live primary spreadsheet remains the existing Gecko Job Tracker, Job List ID
1274044170. Latest read-only inspection found 39 named columns and 1,144 jobs (the
user added Company Website). Found Using
was F; all 1,144 values were blank. The runtime uses headers, not that position.
The Sheet contains the separate Source, Qualifies to Apply?, Ready to Apply?,
completion/date/link fields, description/review fields and word-count formulas.

The existing native Python environment is `.tools/dashboard-python/Scripts/python.exe`.
`job-scout/requirements.txt` lists PyMuPDF and the Google API/auth libraries.
The implementation adds no Python dependencies: it uses SQLite, urllib and the
existing REST/Sheets code. Existing mock-based provider, tracker, sync, daily and
rejection tests were inspected and reused.

What was added: shared transactional credit reservations, a durable response cache,
Firecrawl web search, bounded verification, retained crawl identities, resumable
candidate/job delivery and Firecrawl metrics in the existing Daily Run report.

## Configuration and credit behavior

`job-scout/preferences/firecrawl.json` is the single policy file:

| Setting | Installed value |
| --- | --- |
| `enabled` | true; gates **all** Gecko Firecrawl paid calls |
| `daily_enabled` | true; gates the smart daily stage |
| Allocation | 5,000 credits, cumulative for this ledger |
| Daily soft target | 200 credits |
| Daily hard admission limit | 200 credits |
| Budget day | America/Denver, based on request start time |
| Reservation headroom | 2 extra credits per request |
| Base query coverage | 16 configured Utah/remote categories; additional configured categories remain eligible |
| Results per query | Target 50, reduced when needed to preserve category coverage and verification budget |
| Adaptive expansion | Up to 100 results, then temporary domain exclusions, only after qualified yield is demonstrated |
| Extraction limit | 100 pages/day across the shared request ledger; a ceiling, not a target |
| Paid unknown-date verification limit | 60 requests/day; a ceiling, not a target |
| Paid checks per query round | 2, then rotate to another search group |
| Planning reserve | 20 credits for verification; shared transactional reservations remain authoritative |
| Local response-cache TTL | 24 hours |
| Posting window | Rolling 96 hours |
| Priority exceptions | Disabled |
| Account balance | Required, at most 5 minutes old before new paid work |

Current documented basic estimates, verified October 21: search is 2 credits per
10 results rounded up; basic scraping is 1 credit/page. They are configurable in
`pricing`. Requests save their pricing snapshot so later changes do not rewrite
history. Sources: [search pricing](https://docs.firecrawl.dev/features/search),
[scrape pricing](https://docs.firecrawl.dev/features/scrape).

Before paid work, the client reads the documented GET
[`/v2/team/credit-usage`](https://docs.firecrawl.dev/api-reference/endpoint/credit-usage).
The allocation is an allowance, **not a claim that the account has 5,000 credits**.
Admission uses the lower available allocation/account headroom. Missing/invalid
balance information stops paid requests. This reconciliation was not called during
implementation; the present account balance is unverified.

All workers reserve against the same SQLite ledger under `BEGIN IMMEDIATE` before
sending. Reservations count toward both daily limits and the allocation. The soft
target stops new calls, including prospective headroom, so spending may stop below
100. No unused budget is spent just to reach the target. No priority calls are
generated by the installed pipeline.

An explicit top-level `creditsUsed` is provider-confirmed; absent totals retain the
full reservation as estimated/uncertain. A timeout, crash or failed request never
automatically releases credit or repeats that request. Pending/unknown reservations
remain in the lifetime allowance across restarts and midnight. Completed responses
are reused locally; Firecrawl's own remote cache is not treated as free.

Provider routing, late charges, external account usage and price changes can prevent
an exact pre-request charge guarantee. Unexpected totals or routing costs beyond
reserved headroom stop additional paid requests for review. The 200-credit limit
is a conservative **admission limit**, not a promise that provider billing can
never exceed it. Unresolved reservations require evidence-based review; there is
no automatic stale-reservation reset or silent billing reconciliation.

Only plain web search and basic HTML/markdown scraping are allowed. Initial searches
omit `scrapeOptions`; scrape requests explicitly use basic proxy and `parsers: []`.
AI JSON extraction, premium formats/proxies, PDF/document parsing, browser actions
and full-site crawling are rejected. No access-control/CAPTCHA bypass was added.
Legacy Firecrawl-backed retrieval remains available when paid usage is enabled;
while disabled, existing free discovery paths remain in place.

## Pipeline, history and recovery

`job-scout/data/firecrawl_discovery.sqlite` is created lazily on the first enabled
run. It is local and ignored by Git. No discovery-history database was created
live during implementation. Tests use isolated temporary databases.

| Table | Purpose |
| --- | --- |
| `requests` | Shared reservations, request identity, pricing, response/cache, provider totals and unresolved bills |
| `balances` | Timestamped provider balance snapshots and conservative debit baselines |
| `runs` | One resumable checkpoint per Denver day, with the original run cutoff |
| `queries` | Completed/retrieved query results, coverage and efficiency statistics |
| `identities` | Canonical/ATS/employer identities retained independently of visible Sheet rows |
| `candidates` | URLs/redirects, employer/ATS IDs, dates/evidence, content fingerprints, cache/retry state, credits, Gecko IDs and tracker associations |
| `report_outbox` | Delivery/retry state for existing Daily Run report blocks |

The previous Found Using feature adds `jobs.found_using` lazily when JobStore opens
an older database. It preserves unknown historical provenance as blank. This work
does not replace or rebuild the live jobs database, Sheet tabs or historical IDs.
One expanded sync test initially opened the live JobStore for its normal schema
check; the fixture was corrected. Read-only verification matched the audit counts:
1,147 jobs, 1,224 source links, 1,207 workspace records, seven archives and nine run
records. The additive `found_using` field is present, with no historical values
backfilled. Final validation isolates the store and blocks network connections.

Smart discovery runs before ordinary paid retrieval in the existing daily workflow.
It seeds retained identities from jobs, source links, current/archived/manual
workspace data, and live jobs/rejections when available. Missing Sheet rows do not
make those identities new. ATS identifiers and identity-bearing query parameters
are preserved. Distinct requisitions follow Gecko's existing identity-conflict rules.

Queries are grouped only from configured target roles, scoped to Utah and remote
work. Previously uncovered/least-recently-covered queries rotate into the bounded
daily selection; qualified-yield/credit history breaks ties. Coverage is retained
rather than deleting low-yield sources. Known URLs/IDs, irrelevant titles, explicit
nonqualifying location hints and structured old-date hints are checked before
paid extraction. Search/index dates are never proof that a job is recent.

Full public listing data must establish a relevant role and Utah/remote eligibility
under Gecko's existing rules. Original posting dates use JobPosting `datePosted`,
then explicit original dates on a recognizable employer/ATS listing. An offset-free
timestamp is unproven; date-only values spanning the cutoff remain in review using
conservative timezone bounds. Neither `dateModified` nor indexing/crawl timestamps
qualify a listing. Missing schema/date evidence, blocked/expired pages and unresolved
dates are retained for review. They do not become confirmed recent tracker rows.
Unknown-date checks are capped; failed paid requests are not automatically retried.

Qualified new jobs are saved durably with their reserved Gecko ID. The publisher
uses the existing GoogleTracker managed-cell writer and independent readback for
ID, URL, Found Using and description. It preserves manual values, formulas, resume
links, existing completion guards, eligibility/Cost checks, validations and formatting.
Existing freeze enforcement preserves row 1 and any larger frozen region.

Sheet outages leave validated jobs in the outbox. Existing `sheet_sync.sync()` calls,
including idle retries, drain it before reconciling the working cache. Retry delivery
never invokes a Firecrawl client. Ambiguous/conflicting tracker identities stop for
review. No manual importing is required.

The existing daily summary prints a `Firecrawl efficiency` JSON line. Gecko's
existing daily wrapper folds it into its current run fields; local run storage also
queues that same block for the existing live Daily Run writer. Final summary costs
include ordinary Firecrawl retrieval too. Report delivery retries are idempotent
and preserve existing history. Reports distinguish confirmed/uncertain costs,
balance observation time, queries/results/candidates/skips, age/role exclusions,
unknown dates, scrape outcomes, qualified jobs, per-query/source performance and
credits per qualified job. Zero qualifying jobs produce no invented cost-per-job.

## Commands and activation

Safe local plan, callable now; **no API calls, ledger creation, or Sheet writes**:

```powershell
& C:\gecko_main\.tools\dashboard-python\Scripts\python.exe C:\gecko_main\scripts\firecrawl_discovery.py --dry-run
```

After Dave approves a live test, change `enabled` and `daily_enabled` to `true`
in the policy file. An isolated smart-discovery run, with no resume/application work:

```powershell
& C:\gecko_main\.tools\dashboard-python\Scripts\python.exe C:\gecko_main\scripts\firecrawl_discovery.py --apply
```

The regular daily command remains `Gecko` (or `scripts/Start-Gecko.ps1`); it retains
the existing broader daily/resume workflow. Do not use its legacy `--dry-run` as a
credit-free discovery test: that older workflow can still query providers. Use the
dedicated local plan command above for a no-network preview.

Retry delivery without repeating Firecrawl work:

```powershell
& C:\gecko_main\.tools\dashboard-python\Scripts\python.exe C:\gecko_main\scripts\firecrawl_discovery.py --sync-only
```

Searches remain manual. Do not add recurring triggers. A completed smart-search
day skips repeat search work; an interrupted day resumes checkpoints. No trigger
was added by this change. Both enable flags remain false pending live-run approval.

## Files and verification

New: `job-scout/firecrawl_state.py`, `job-scout/firecrawl_discovery.py`,
`job-scout/firecrawl_search.py`, `job-scout/job_extraction.py`,
`job-scout/preferences/firecrawl.json`, `job-scout/tests/test_firecrawl_discovery.py`,
`job-scout/tests/test_firecrawl_search.py`, `job-scout/tests/test_job_extraction.py`,
`scripts/firecrawl_discovery.py`, and this guide.

Modified: `.gitignore`, `job-scout/sources/firecrawl.py`,
`job-scout/sources/indeed_search.py`, `job-scout/scout.py`, `job-scout/sheet_sync.py`,
`job-scout/google_tracker.py`, `job-scout/normalize/__init__.py`,
`scripts/gecko_daily.py`, `scripts/sqlite_daily_report.py`,
`job-scout/tests/test_firecrawl_pacing.py`, `job-scout/tests/test_provider_repairs.py`,
and `docs/tracker-schema.md`.

The complete-extraction extension also modifies `job-scout/models.py`,
`job-scout/storage/__init__.py`, and `scripts/generate_apply_queue.py`.

Earlier uncommitted Found Using model/storage/schema/tests changes were retained.
No credential, role/source preference, resume, application safeguard or scheduled
task was modified. Focused mocked tests cover all 18 requested categories, plus
report delivery, the daily hook, uncertain provider routing charges and archived
matrix recovery. The implementation report records final test counts and live
read-only tracker verification.

Live paid responses, current account balance and live new-job publishing remain
unverified until an approved live test. Tests verify publishing against mocked
Sheets. Unknown/ambiguous dates intentionally reduce recall. Explicit-date fallback
requires recognizable employer ownership and structured job fields; unsupported
unstructured pages remain review cases instead of being guessed into the tracker.

## Final validation results

All focused runs blocked socket connections, with mocked Firecrawl responses:

| Suite | Passed |
| --- | ---: |
| Smart discovery, billing, recovery, daily hook, live-writer and idle-sync fixtures | 35 |
| Adaptive coverage, expansion, pricing, fee exclusion and incomplete-source fixtures | 6 |
| Complete extraction, durable evidence, Sheet mapping and resume cache access | 8 |
| Shared pacing and no-paid-retry policy | 5 |
| Provider repairs | 7 |
| Found Using | 7 |
| Existing Sheet synchronization | 13 |
| Existing expanded sources | 25 |
| Existing resume queue, daily wrapper, Daily Run writer and SQLite tracker | 101 |
| **Total focused tests** | **207** |

Broader unchanged suites have nine existing fixture errors: three rejection tests
refer to the removed Status column, and six run-command tests omit the required
tracker-backend configuration in their temporary workspaces. Both sets reproduced
against the original HEAD implementation; no unrelated fixes were made.

Syntax checks and `git diff --check` passed. The dedicated dry-run command ran with
both enable flags false and no discovery-history database creation. Final read-only
Google Sheet verification found 39 headers, 1,144 rows, Found Using at index 6 with
all 1,144 historical blanks intact, 5,716 formula cells and frozen row 1. New source
values and outbox publishing were verified against mocked Sheets, not live writes.

## Adaptive search depth

The documented [v2 search contract](https://docs.firecrawl.dev/api-reference/endpoint/search)
supports limits from 1 to 100 and `excludeDomains`; it does not document an offset,
page number or next-page cursor. The planner uses those supported expansion tools
instead of sending invented pagination parameters. Coverage and expansion are
reported separately in the existing Daily Run fields.

Sixteen searches at 50 results would reserve more than the 100-credit soft target
before verification. Consequently, 50 is the preferred depth, not a guaranteed
depth for every category on every day. The planner reserves admission capacity for
uncovered categories, reduces initial depth when necessary, then deepens saturated
queries only after they produce verified qualified jobs. Duplicate-only or exhausted
results stop that expansion. At 100 results, a productive query may temporarily
exclude its most represented result domain to explore additional employers. This
does not blacklist the domain on subsequent days. Query/source yield per credit,
duplicate rates, requested depths and uncovered categories remain visible.

## Complete job information and source evidence

Previously supported: employer/title/location, basic employment and salary text,
remote hints, original date evidence, source/ATS identity and description text.
New: durable unabridged Markdown and raw HTML, structured salary components,
normalized employment types, explicit arrangement evidence, work hours/schedule,
remote restrictions, fee evidence, special requirements, section content and direct
application URL. Optional unavailable values remain null/blank; no default salary,
40-hour schedule or free-application claim is invented.

| Published information | Existing tracker destination | Durable evidence |
| --- | --- | --- |
| Company/title | Company / Job Title | Parsed fields and original HTML |
| Employment type | Employment Type | Normalized types plus original schema |
| Salary bounds/currency/period | Salary, as readable text | Separate numeric components and source evidence |
| Arrangement/location | Work Arrangement / Location | Explicit arrangement evidence and location restrictions |
| Hours/schedule/restrictions/special requirements | Notes on new rows | Separate fields, retained original text |
| Mandatory application fee | Cost = x, qualification No, evidence in Notes | Positive required-fee evidence; unknown cost stays blank |
| Full description and all job sections | Job Description | Full Markdown, original structured description, raw Markdown and HTML |
| Original posting date | Date Posted | Original-date evidence, subject to rolling 96-hour validation |
| Listing/direct application URLs | Job URL / Notes | Separate application URL when explicitly published |
| Employer job ID | Existing stable Gecko ID association | Employer/ATS ID retained separately |
| Discovery system | Found Using = Firecrawl on new rows | Original source preserved on rediscovery |
| Company website | Company Website when present | Published hiring-organization URL |

Responsibilities, required/preferred qualifications and benefits are preserved in
the complete description and separate durable fields. No replacement Sheet columns
are created. Original source text is retained separately from the Markdown assembled
for matching. Missing structured sections are appended only from published metadata.

The additive `job_documents` table in the existing jobs database keys evidence by
stable Gecko job ID. It retains status, issues, parsed fields, source URL and capture
time. Completed evidence survives restarts and rediscovery. Review candidates retain
their raw response in discovery history. Empty/short descriptions, explicit truncation,
inaccessible responses and empty published sections stay in review. Completeness
checks are conservative heuristics; they cannot establish that an employer published
every possible detail. No additional scraping or expensive extraction is used to
invent missing fields.

Descriptions exceeding Google's 50,000 UTF-16-unit cell limit remain complete in
`job_documents`; Job Description stays blank and Notes identifies the stable job ID.
A linked tracker field could be added later with approval; none was created here.
`JobStore.get()` exposes the full description, and the existing resume queue archives
completed document storage directly without another retrieval. Existing manual Sheet
descriptions keep their established priority. This changes job-context access only;
resume facts, layout, approval and completion guards remain intact.

Source limitations: unstructured pages without a unique JobPosting stay in review;
missing/ambiguous original dates cannot qualify as recent. Unpublished salary, hours,
benefits, application URLs or restrictions remain unknown. Multiple incompatible salary
offers and unsupported custom metadata remain available in raw evidence rather than
being guessed into normalized fields. Live publishing remains untested pending approval.
