# Gecko Main live discovery

Run started 13-10-2026 at 4:10 PM MDT. Collection completed around 4:21 PM MDT; canonical recovery synchronization completed around 4:24 PM MDT. This report uses current live results, not historical candidate counts.

**Verified result: 171 new Job List rows and 543 existing rows updated.** All 4,252 managed cells were independently read back. Before: 839 job rows + 20 residual populated rows = 859. After: 1,010 job rows + the same 20 residual rows = 1,030. No rows were deleted, sorted, moved, or cleaned. Newly inserted physical rows 861–1031 are each 21 pixels high. All 171 additions have structured remote/Utah eligibility, Apply? = Yes, blank Cost, and blank resume fields.

## Provider reconciliation

| Source | Previous audit parsed | Current raw / parsed | Queries or feed/board requests | Duplicate records | Rejected history | Eligibility excluded | URL review | New local unique | Sheet added / updated | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| adzuna | 200 | 446 / 446 | 128 | 62 | 11 | 332 | 41 | 0 | 0 / 24 | success |
| remotive | 3 | 3 / 3 | 9 | 0 | 1 | 2 | 0 | 0 | 0 / 0 | success |
| web-careers | 0 | unknown / 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | blocked |
| jobicy | 123 | 123 / 123 | 1 | 20 | 0 | 103 | 0 | 0 | 0 / 20 | success |
| remoteok | 99 | 100 / 99 | 1 | 1 | 0 | 98 | 0 | 0 | 0 / 1 | success |
| usajobs | 86 | 86 / 86 | 128 | 0 | 0 | 86 | 0 | 0 | 0 / 0 | success |
| greenhouse | 6992 | 6996 / 6996 | 123 | 201 | 0 | 6792 | 0 | 3 | 3 / 199 | success |
| lever | 3070 | 4733 / 4733 | 96 | 109 | 0 | 4572 | 0 | 52 | 52 / 104 | partial failure |
| ashby | 3062 | 3149 / 3149 | 82 | 46 | 0 | 2987 | 0 | 116 | 116 / 45 | partial failure |
| workable | 5464 | 5464 / 5464 | 80 | 320 | 1 | 5143 | 0 | 0 | 0 / 136 | success |
| weworkremotely | 110 | 110 / 110 | 1 | 18 | 0 | 92 | 0 | 0 | 0 / 14 | success |
| workingnomads | 51 | 51 / 51 | 1 | 0 | 0 | 51 | 0 | 0 | 0 / 0 | success |
| themuse | 0 | unavailable / 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | missing credentials |
| indeed | 0 | unknown / 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | blocked |
| linkedin | 0 | unknown / 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | blocked |
| glassdoor | 0 | unknown / 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | blocked |
| ziprecruiter | 0 | unknown / 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | blocked |
| jooble | 0 |  / 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | disabled |

Previous totals are the saved earlier audit snapshot (19,260 parsed), not equivalent searches: Adzuna now exercised all 128 role/location queries, versus the earlier bounded 32-query comparison. Current parsed total is 21,260. Configured employer coverage remains 370 boards: Greenhouse 123, Lever 85, Ashby 82, Workable 80. Lever required 96 supported requests/pages. All 16 target roles and eight established Utah/Remote location queries remain configured. Adzuna and USAJobs each completed 128 queries/pages; none required a second result page in this run. Full feeds were collected before central filtering; no global collection cap was applied. `--results 50` supplies page size. Existing legitimate endpoint/feed limits remain; these results are the currently exposed listings, not an assertion that every provider's historical inventory was available.

Blocked providers have unknown raw availability, not successful zero-result searches. The CSV/JSON retain attempted/completed pages, actual errors, all named eligibility exclusions, duplicate subsets, URL checks, and written rows. Sheet attribution uses the first current source that verified each identity; a job's preserved primary Source may differ.

**Exact reconciliation:** 21,261 observed raw API/feed records − 1 Remote OK metadata entry without a job position = 21,260 parsed listings.

21,260 = 20,258 named eligibility exclusions + 13 rejection-history exclusions + 41 URL-review occurrences + 777 previously-known duplicate occurrences + 171 new unique jobs.

The 777 duplicate occurrences resolve to 543 unique existing matches. Four occurrences added a previously unknown cross-source association; already-recorded associations are counted as known duplicates. No duplicate-within-current-run survivor category occurred. Duplicate and verification metrics are subsets, not additional exclusions. There were zero confirmed-dead-URL, missing-content, disabled-Jooble provenance, or artificial-cap exclusions in this run. Unknown Cost never blocked approval. The historical “13 jobs” metric is addressed by the earlier audit; it is not this live run's result.

Eligibility exclusions: outside target role families 15,263; unrelated role family 3,946; non-remote outside preferred locations 381; generic non-marketing manager/production role 360; non-marketing data science 114; excluded employment type 112; excluded title/seniority 81; missing title 1. Total 20,258. Every parsed occurrence has an exclusive named disposition in `record-decisions.json`; `count-reconciliation-checks.json` passes every source.

## Repairs actually made

- Updated supported employer mappings, verified through real provider requests and official careers links: Hightouch Greenhouse → Ashby `hightouch-inc` (76 jobs); Outschool Greenhouse → Ashby `outschool` (6); Suger.io Lever `suger` → `fours` (11). Employer scope was preserved. Goodlord's unchanged board returned 10 jobs successfully.
- Added bounded transient retries, safe error details, explicit oversized-response failures, HTTP response counts, and source-wide billing-failure suppression. Reduced source concurrency from 6 to 3. Only one unchanged Brave billing request was sent.
- Preserved partial acquisition results and corrected pagination/termination evidence. Query coverage and prior unlimited-collection/FullTime repairs were retained. Corrected internally reported provider failures being labeled successful empty pages; the original run's blocked Web Careers page is reconciled as failed in the report.
- Made standalone canonical search a discovery-only safe path: verify URLs before import; synchronize only current verified new/existing identities; consult rejection history without destructive rejection cleanup; no enrichment, resume queue, Gmail, or applications.
- Added source-qualified identity/canonical posting alias handling and protected managed-cell planning, before-write evidence, formula/manual-change skips, exact readback, and new-row height enforcement in the existing tracker implementation.
- Fixed the missing `json` import discovered at the initial synchronization attempt. It failed before any Sheet write. Added `sync-discovery` in canonical `scout.py` to resume only saved accepted URL identities, reject mismatched evidence, and refuse completed-run replay. The regression test now exercises evidence persistence. Recovery completed the requested live writes.
- Corrected the misleading pre-sync console label “New qualified jobs written” to “New unique jobs saved locally,” followed by separately verified Sheet totals. The original running process had loaded the old label; its 171 meant local new unique jobs, not proof of imports.

Changed this task: `job-scout/scout.py`, `service.py`, `google_tracker.py`, `normalize/__init__.py`, `sources/http.py`, `sources/acquisition.py`, `sources/web.py`, `preferences/job-sources.json`; new `job-scout/tests/test_live_discovery.py`, `scripts/verify_discovery_live.py`, `scripts/report_discovery_live.py`. Earlier audit edits and unrelated uncommitted work were preserved. Production database/configuration/code backups and task-specific patch are alongside this report. The normalized posting-alias addition was not included in the initial code backup; unrelated existing normalization edits were retained.

Official mapping evidence: https://hightouch.com/careers/3f686548-a559-4452-8cf1-0e25894e270f ; https://outschool.com/careers ; https://www.suger.io/careers redirects to https://www.fours.com/careers/ . Detailed fetched evidence is in the employer verification JSON files.

## Sheet verification and safeguards

The configured database resolves to `C:\gecko_main\job-scout\data\jobs.sqlite3`. The configured existing workbook and Job List tab were re-read before writing. Live headers differed from the instruction snapshot: Notes is column 9, Job URL 16, Resume Link 17, Last Updated 18. Every field was resolved by its unique live header; no headers/tabs were added or renamed.

Independent `independent-readback.json` confirms 714 affected stable identities, every planned managed value, zero unplanned cell changes, zero introduced duplicate IDs/posting identities, all old formulas and ARRAYFORMULA protection, manual Apply? decisions, Applied, Response, Resume Created, existing Resume Link/raw file URIs, notes prefixes, custom/unrelated cells, residual rows, physical order, and unrelated tabs preserved. The 269 affected existing X markers were preserved; none had missing links. No affected blank-marker/nonblank-link case occurred. Formula-protected skips: 0. Manual-review write skips: 0. Failed writes remaining: 0. No live rejection-history or Cost=x writer exclusion was newly encountered at sync; those protections remain and rejection history already removed 13 occurrences upstream.

Before each managed batch, the canonical writer read current formula state. No formulas were found in affected writable cells. Metadata readback confirms formatting, colors, filters, checkbox validation, frozen rows, widths, conditional formats, and original rich-text links preserved. Google automatically changed link targets on managed Job URL cells when their URL values changed; these targets were separately checked against the exact intended values and excluded only from the generic formatting comparison. No resume links were changed. Last Updated and appended Notes contain the actual Gecko run time in America/Denver; untouched rows were not timestamped.

The before/after inventory of all 413 resume files is unchanged. **No resumes were generated and no applications were submitted.**

## Tests

54 focused tests passed: 13 standalone discovery/tracker/provider tests, 16 prior audit regression tests, 25 expanded provider tests. They cover live canonical dispatch, no prohibited workflows/cleanup, evidence persistence/recovery identity scope, URL review exclusion, partial-result retention, posting aliases, protected manual/resume/formula fields, managed readback, row height, transient retries, billing suppression/redaction, and provider-reported error pages.

Broader tracker suite: 51 tests run; **3 failures and 8 errors remain**, unchanged from the audit. Six errors use the retired Status field; two expect lifecycle/manual-approval behavior now blocked by safeguards. The three failures assume old columns/timestamp expectations. The broader suite is not green. Exact tracebacks are saved in `broader-tracker-tests.txt`. Current-header protections are covered by passing focused fixtures; no live protections were relaxed to satisfy legacy tests.

## Remaining blockers and review

- Brave HTTP 402: response code `CREDIT_EXHAUSTED`, message explicitly states prepaid credit balance is insufficient. This is billing, not parsing. Web Careers/Indeed/LinkedIn/Glassdoor/ZipRecruiter remain blocked. The account owner must resolve the existing approved Brave billing/credit access before those searches can run. No credits purchased, plan changed, or unchanged request repeatedly retried.
- The Muse: missing `THE_MUSE_API_KEY`; no approved local/process/user/machine credential was found. Supply that approved setting if this source is intended to run.
- Oxylabs configured Lever board `oxylabs`: HTTP 404. Checkbox Technology configured Ashby board `Checkbox Technology`: HTTP 404. Bounded public careers/board checks did not establish a working supported replacement. Alternate-case Checkbox probing also returned 404. Provider owner/current supported board information is needed; inaccessible boards were not treated as empty successful sources.
- URL review: 41 Adzuna occurrences, representing 16 source-qualified job IDs and 38 URL strings, remained unimported because access could not establish a working listing. Reasons are saved per record. These are access/review cases, not invalid jobs. No recovery count is claimed for blocked providers or these uncertain URLs.
- Google CSE fallback settings `GOOGLE_CSE_API_KEY` and `GOOGLE_CSE_ID` are absent; the authorized Indeed API endpoint/token settings are also absent. No credentials were borrowed from another app/account, and no CAPTCHA/auth/access restriction was bypassed.

A further usable-source backfill is not pending: the current verified discovery was fully synchronized. After provider billing/credentials/board access is repaired, another full rediscovery is needed for those blocked sources; additional recoverable jobs are unknown until a successful current listing search and URL verification. Do not rerun the already-completed recovery command.

## Commands and evidence

```powershell
python job-scout/scout.py search --source all --results 50 --audit-dir reports/discovery-live/20261013T161002
python job-scout/scout.py sync-discovery --help
python job-scout/scout.py sync-discovery --audit-dir reports/discovery-live/20261013T161002
python scripts/verify_discovery_live.py reports/discovery-live/20261013T161002
python scripts/report_discovery_live.py reports/discovery-live/20261013T161002
python -m unittest discover -s job-scout/tests -p test_live_discovery.py
python -m unittest discover -s job-scout/tests -p test_discovery_audit_regressions.py
python -m unittest discover -s job-scout/tests -p test_expanded_sources.py
python -m unittest discover -s job-scout/tests -p test_google_tracker.py
```

The initial search exited 1 on the pre-write evidence import defect (and retained explicit provider errors). Recovery sync exited 0 and actual writes were verified. GET-only canonical provider probes, live snapshots, configuration/path inspection, command help, and bounded public careers requests supplied the maintenance evidence. No forbidden daily/queue/application/reporting workflow was executed.

For a future full live rediscovery after provider access is restored, use a new timestamped evidence directory:

```powershell
$runStamp = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::UtcNow, 'Mountain Standard Time').ToString('yyyyMMddTHHmmss')
python job-scout/scout.py search --source all --results 50 --audit-dir "reports/discovery-live/$runStamp"
```

Machine-readable evidence: `source-reconciliation.csv/json`, `final-reconciliation.json`, `count-reconciliation-checks.json`, `record-decisions.json`, per-source files, `http-requests.json`, `tracker-before-write.json`, `tracker-after-write.json`, `tracker-result.json`, `independent-readback.json`, before/after workbook values and formatting snapshots, provider repair evidence, and test logs. Authentication secrets are excluded.
