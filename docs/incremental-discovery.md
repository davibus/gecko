# Incremental daily discovery

Daily Scout and `Gecko job search` now use `job-scout/incremental_discovery.py`.
This supersedes the daily search-first behavior described in older Firecrawl
documentation. Zero new matches is a successful run; there is no job quota.

All configured public employer/ATS feeds and authorized jobs APIs are acquired
before detail retrieval. Providers that mix discovery with page scraping are
reserved for explicit broad discovery. Free source failures appear separately
as partial coverage; they never cause a paid broad search fallback.

The existing `firecrawl_discovery.sqlite` retains additive `daily_candidates`,
`daily_aliases`, and `daily_events` tables. Source IDs, posting URLs with tracking
removed, supported ATS URL aliases and retained source links establish identity.
Company/title similarity never merges candidates. Jobs, archived workspace rows,
the freshly read primary Sheet and permanent rejections seed known identities.
Conflicting aliases/reused URLs require review rather than silently hiding a
different requisition. Discovery never deletes existing records or files.

States are `seen`, `pending`, `accepted`, `rejected`, `expired`, and verified `duplicate`, with recorded
reasons. Paid dispatch, response, complete content, match review, reserved Gecko
ID and publication receipt are separate checkpoints. The existing History OS
lock serializes discovery/publication across workers and restarts. The outer
Gecko run lock coordinates dashboard and daily work. A second worker fails busy;
it does not launch a duplicate paid request or tracker write.

Cheap role/location/salary/provenance filters precede retrieval. Full source
descriptions and saved transport/content evidence are reused first. Incomplete
descriptions try exact public ATS APIs and ordinary permitted retrieval before
basic Firecrawl scraping. Restricted sources are retained for review. Paid
requests use the existing pricing, account reconciliation, reservations and
limits. New `request_targets` records retain target and payload alongside each
reservation, including requests interrupted before a response.

Free retrieval/inference failures have a seven-day cooldown. New complete free
source evidence can rescue pending work immediately. A paid dispatch is never
repeated automatically; successful saved responses can recover a crash between
transport settlement and the candidate checkpoint. Incomplete paid content stays
pending for free evidence or explicit review. Unknown legacy bills without a
recorded target conservatively block new paid retrieval until reviewed. Nothing
silently releases reservations or guesses a provider bill.

Validated match evidence uses the existing resume-match cache. Changing the
thresholds/master/policy reopens reviewed rejections for evaluation; thresholds
alone reuse inference evidence. Existing 60/50/50 thresholds and 40/30/15/10/5
weights are unchanged. Permanent rejections never reopen through policy changes.

Accepted jobs are published immediately with the canonical managed-cell writer.
A second primary-Sheet read verifies ID, posting URL and actual query provenance;
frozen headers are verified. A reserved ID and pending publication survive Sheet
outages. Publication retries spend no retrieval credits. Existing rows are append
protected; manual fields, formulas, completion markers and resume links remain.

Commands (from the project root, using the existing Python environment):

```powershell
# Ordinary incremental search; no resumes/applications.
.tools/dashboard-python/Scripts/python.exe scripts/gecko.py job search
# Controlled admission cap; all remaining candidates stay durable/pending.
.tools/dashboard-python/Scripts/python.exe job-scout/scout.py search --max-new-candidates 3
# Deliver accepted pending rows only; no candidate retrieval.
.tools/dashboard-python/Scripts/python.exe scripts/gecko.py job search --sync-only
# Explicit free/content/review retry by daily_candidates.key. Paid dispatch is retained.
.tools/dashboard-python/Scripts/python.exe job-scout/scout.py search --retry-candidate KEY
# Explicit broad market search, with existing budget/usage reporting.
.tools/dashboard-python/Scripts/python.exe scripts/gecko.py job search --broad-discovery
```

Existing availability checks/manual Indeed maintenance are opt-in via
`scout.py daily --maintenance-existing` (the daily command retains its normal
resume workflow). Use search commands for discovery-only work. The dedicated
`scripts/firecrawl_discovery.py --apply --broad-discovery` command is also an
explicit broad search. Ordinary daily/search commands never call broad search.

`reports/discovery/live-status.json` and timestamped incremental reports contain
candidates, known skips, new local IDs, independently published IDs, free detail
retrievals, avoided paid requests, actual request reservations, pending counts,
source coverage and ledger changes. Avoided requests count skipped candidate
retrieval opportunities, not claimed saved credits. Confirmed credits require
provider totals; unresolved reservations are reported separately. Historical
ledger totals are separate from this run's usage delta.

Offline verification: `python scripts/test_resume_match_filter.py`. Tests use
temporary databases, mocked providers/inference and prohibited network access.
## Verified requisition variants

Greenhouse's first-party `internal_job_id`, qualified by its ATS tenant, is
recorded as a requisition alias alongside public posting IDs and canonical URLs.
Multiple public posting IDs for that verified requisition share discovery
admission. A retained posting establishes the alias before retrieval even when
the new variant appears first in the feed. Different internal requisitions remain
distinct, including a genuinely new requisition reusing a public URL. A complete,
eligible new variant can recover an older deterministic location exclusion;
permanent tracker rejection history remains protected. Confirmed duplicate
candidate records retain their evidence with state `duplicate` and cannot trigger
ordinary discovery or an explicit retry of the alias instead of its canonical job.

Explicit employer country and workplace restrictions are checked before match
reviews or paid retrieval, including conflicting generic remote flags. Verified
applicant-country restrictions take precedence over office addresses. These
evidence holds use durable `retry_mode: manual`; unchanged daily discovery does
not retry them. Changed complete source evidence or an explicit retry can release
the hold, while unresolved paid dispatches remain protected. Ordinary temporary
failures retain their cooldown, and run-limit deferrals remain eligible for the
next run. Publication readback must confirm qualification as well as ID/URL/query.

