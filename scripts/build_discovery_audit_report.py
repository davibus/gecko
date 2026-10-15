"""Build the local audit report from saved, reconciled evidence."""
import json
from datetime import datetime, timezone, timedelta
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/discovery-audit/20261013'
def read(name):return json.loads((OUT/name).read_text())
def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |',
        *['| '+' | '.join(str(v).replace('|','/') for v in row)+' |' for row in rows]])
def main():
    r=read('reconciliation.json');live=read('live-before.json');history=read('historical-runs.json')
    old=read('historical-identity-reconciliation.json');links=read('candidate-url-validation.json')
    sources=r['sources'];rules=Counter()
    fixed={'source','enabled','queries','raw_parsed','source_errors','status','tracker_written','reconciled','evidence','windows','eligible new unique'}
    for row in sources:
        for key,value in row.items():
            if key not in fixed and not key.startswith('subset:') and isinstance(value,int):rules[key]+=value
    assert sum(rules.values())==r['record_count']
    high=next(x['run'] for x in history if 'search-core-max.log' in x['file'])
    latest=next(x['run'] for x in history if '130723' in x['file'])
    valid=sum(x['validation']['status']=='valid' for x in links)
    pending=sum(x['validation']['status']=='temporary_failure' for x in links)
    ledger=Counter(str(row.get('Source') or '(blank)').casefold() for _,row in live['ledger_rows'])
    previous=Counter()
    for source,count in old['historical_by_source'].items():previous[source.casefold()]+=count
    queue=read('live-eligibility.json');applied=Counter()
    for _,row in live['ledger_rows']:
        value=row.get('Applied')
        if value not in (None,'',False) and str(value).strip().casefold() not in {'false','no'}:
            applied[str(row.get('Source') or '(blank)')]+=1
    ledger_stages=table(['Source','Rows','Pending','Resume X','Cost x','Apply No','Missing URL','Outside Utah or Remote','Applied subset'],[
        [source,sum(d.values()),d.get('ELIGIBLE',0),d.get('SKIP RESUME: existing tracker row already has Resume Created = X',0),
         d.get('SKIP: Cost = X',0),d.get('SKIP: Apply? explicitly No',0),d.get('SKIP: missing or invalid Job URL',0),
         d.get('SKIP: outside Utah and not remote',0),applied[source]]
        for source,d in sorted(queue['source_decisions'].items(),key=lambda pair:pair[0].casefold())])
    totals_table=table(['Source','Historical database','Current ledger','Oct 11 uncapped parsed','Last daily processed','Audit parsed'],[
        [s,previous[s],ledger[s],high['source_counts'].get(s,0),latest['source_counts'].get(s,0),
         next((x['raw_parsed'] for x in sources if x['source']==s),0)]
        for s in sorted(set(previous)|set(ledger)|{x['source'] for x in sources})])
    reconciliation_table=table(['Source','Enabled','Health','Queries or pools','Parsed fetched','Errors','Within source duplicates','Cross source known subset','Previously known','Rejected or deleted','Other exclusions','New unique','Eligible new','Tracker writes'],[
        [x['source'],'Yes' if x['enabled'] else 'No',x['status'],x['queries'],x['raw_parsed'],x.get('source_errors',0),
         x.get('duplicates within source',0),x.get('subset: cross-source previously known',0),
         x.get('previously known in live tracker',0)+x.get('previously known only in database',0),
         str(x.get('previously rejected',0))+' / 0',sum(v for k,v in x.items() if k not in fixed and not k.startswith('subset:')
         and k not in {'duplicates within source','cross-source duplicates','previously known in live tracker',
                      'previously known only in database','previously rejected','new unique'} and isinstance(v,int)),
         x.get('new unique',0),x.get('eligible new unique',0),0] for x in sources])
    window_rows=[]
    for x in sources:
        if x['raw_parsed']:
            path=ROOT/x['evidence'];data=json.loads(path.read_text());w=Counter()
            now=datetime.now(timezone.utc)
            for item in data['raw']:
                try:
                    posted=datetime.fromisoformat(item['date_posted'].replace('Z','+00:00'))
                    if posted.tzinfo is None:posted=posted.replace(tzinfo=timezone.utc)
                    for days in [1,7,30]:
                        if now-timedelta(days=days)<=posted<=now:w[str(days)]+=1
                except (ValueError,TypeError):w['unknown_date']+=1
            dates=['Unavailable']*3 if w['unknown_date']==x['raw_parsed'] else [w.get(str(d),0) for d in [1,7,30]]
            window_rows.append([x['source'],*dates,w.get('unknown_date',0)])
    windows=read('server-windows.json')
    after=read('adzuna-remote-windows-after-fix.json')
    server_rows=[]
    for name in ['adzuna','usajobs']:
        for location in ['Utah','Remote']:
            values=[]
            for days in [1,7,30]:
                candidate=next(x for x in windows if x['source']==name and x['location']==location and x['days']==days)
                if name=='adzuna' and location=='Remote':candidate=next(x for x in after if x['days']==days)
                values.append(candidate['parsed_results'] if candidate['status']!='error' else 'Error')
            server_rows.append([name,location,*values])
    report=f'''# Gecko Main job discovery audit

13 October 2026. Project: `C:\\gecko_main`.

The main discovery loss is a cap introduced on **28 September** in commit `e6b9365`: most sources were reduced to 50 sorted listings **before** role and location filtering. Undated feeds were sorted by reverse title order rather than job relevance. October 11 evidence records **18,757 discarded listings** in a capped search. Removing that cap in the historical comparison changed 490 processed listings and one new unique job to 19,247 processed listings and 288 new unique jobs. Today's independent searches returned **{r['record_count']:,} parsed listings**, with **{r['new_unique']} new unique candidates** after the fixes.

The shrinking stored ledger also reflects an explicit reset and selective restoration. Those storage changes and the discovery cap are separate causes.

## What the 13 means

Exactly 13 current records have `Date Found = 2026-10-13`, IDs 2544 through 2556: Workable 5, Indeed 4, Jobicy 2, Greenhouse 1, and We Work Remotely 1. The four Indeed records came from supplied listings; the automated sources account for nine. The saved ledger snapshots changed from 846 populated rows to 859: **846 + 9 + 4 = 859**.

These 13 are dated additions represented in the tracker/database, not raw search results. There is no retained discovery event reporting 13 raw returns. The latest Daily Run is a report-only snapshot: its discovery metrics are unavailable internally and the specified display cells show zero. The last retained actual daily search reports **483 processed listings, 39 duplicates, 442 deterministic exclusions, zero new unique jobs, and zero tracker additions**. The remaining two processed candidates are attributable to the link-validation exclusion path; historical aggregate counters did not name that path separately. The repaired counters now do.

The ledger has 859 populated rows but only **839 job rows with URLs**; the other 20 are retained cells without job identities or URLs. Counting populated rows as jobs overstates current inventory.

## Previous and current source totals

Historical database counts come from `jobs-before-fresh-discovery-20261011T090814.sqlite3`, containing 1,932 retained records. No exact archived run for the remembered approximately 1,600 figure was found. The dated historical raw responses were not preserved, so their raw volume cannot be reconstructed from a cumulative database. The most recent retained high-volume discovery is October 11's uncapped run below.

{totals_table}

Source totals count the primary source of stored records; cross-source links can preserve another provider's identity without another ledger row. The historical 996 rows labeled Jooble differ from the 999 Jooble-provenance exclusions because three other source rows had Jooble destinations.

## Historical storage reconciliation

The restoration audit accounts for every one of its 1,932 input records:

`1,932 = 524 restored + 999 disabled Jooble provenance + 227 duplicate or existing + 134 unverified URLs + 20 expired or dead + 17 protected lifecycle + 11 rejection history`.

The 134 inaccessible/review records were excluded from that restoration, not proven expired. Their URLs should remain review cases. These are historical classifications, not current confirmation that all those jobs remain open.

The current database contains 839 records. Comparing source-qualified primary identities gives **1,932 = 641 retained identities + 1,291 absent primary identities**, and **839 = 641 retained + 198 new primary identities**. This accounts for the 1,093-record difference without pretending that every missing provider identity is a distinct lost job. Source aliases and cross-source merges can represent the same posting.

Of 20 restoration records subsequently absent under their original primary identities, 18 company/title pairs match the later confirmed-dead removal log and two remain as source aliases. The daily removal path clears managed cells while preserving other content, which explains residual populated rows without job identities. The actual logs retain the original URLs and removal evidence.

Evidence: `reports/repopulation/20261011/backup-restoration-audit.json`, `sync-restored.log`, `search-core-max.log`, and `reports/daily/2026-10-11/20261011T130723-df932952eb.log`. Full identity and later-removal comparisons are in this audit directory.

## Current source count reconciliation

**Parsed fetched** means the adapter returned a RawListing before Gecko normalization, deduplication, eligibility, and tracker decisions. It is not a web-search hit count. Failed APIs that yielded zero parsed records are failures, not successful zero-result searches. Provider-side unreturned records and unobserved historical HTTP payloads remain unknown. Every returned record has one exclusive primary decision in `record-decisions.json`.

{reconciliation_table}

The query/pool column counts keyword requests or full-feed collections, not individual HTTP requests. ATS coverage is 125 Greenhouse, 85 Lever, 80 Ashby, and 80 Workable employers. Remotive reads nine category feeds. Retries and pagination can add HTTP calls. Detailed requests, successful zero-result queries, errors, and board failures are in each source's JSON evidence.

Within-source duplicates, previously known jobs, and new cross-source duplicates are disjoint primary buckets. No new cross-source duplicate was found. The four cross-source matches to previously known jobs (Ashby 2, We Work Remotely 2) are subsets, stored as `subset: cross-source previously known` in the CSV/JSON; they must not be added again to the equation. The rejected/deleted column shows rejection-history exclusions followed by zero deleted-history exclusions: Deleted Jobs is empty. The audit made **zero tracker writes** for every source.

{table(['Exclusive primary decision','Records'],sorted(rules.items()))}

The primary decisions sum exactly to **{r['record_count']:,}**. Cost, applied state, existing resumes, and manual approval belong to the live tracker/queue decision stage; they are not fabricated exclusions from provider responses.

## Live eligibility and protections

The canonical queue read against the saved live headers yields:

`859 = 126 pending + 378 Resume Created X + 320 Apply explicitly No + 10 Cost x + 20 missing or invalid URL + 5 outside Utah or explicit Remote`.

The tracker also has 53 applied records, overlapping those queue buckets. The queue protects applied records before generation. Rejection history has 30 records; Deleted Jobs is empty. No deletion fingerprint or row number is used as a permanent rejection key. Rejections use a source-qualified stable job ID, with canonical URL fallback. Resume Created X remains a skip even with a blank link, and existing links remain protected. Formula Cost is evaluated by its effective value; blank Cost is allowed and Cost x blocks approval. The new regression verifies this with a valid URL and no writes.

{ledger_stages}

The Applied column is an overlapping protection count, not an additional mutually exclusive bucket. Every other stage column sums to the row count for that source. Saved per-row decisions are in `live-eligibility.json`.

The discovery replay found **{r['database_only_blocks']}** candidates blocked solely by a database record absent from the live ledger after matching URL aliases and HTTP/HTTPS posting identity. The database high-water ID is an allocation guard, not a discovery blacklist. The tracker previously matched numeric record IDs without proving posting identity; that write path now stops on an ID belonging to another posting. No live collision was forced or repaired.

Live headers were read by name. The actual order is:

`{' | '.join(live['tabs']['Job List']['physical_headers'])}`.

This differs from older physical-column descriptions. All diagnostics resolved current names. The before and final workbook formula/value hashes are identical; no tabs, cells, headers, formulas, formatting, manual fields, applications, or resumes were changed by this audit.

## Discovery windows

These independent server queries used **Paid Search Manager**, Utah and Remote, with pagination where available. They compare posting-age query windows, not tracker additions:

{table(['Source','Location','24 hours','7 days','30 days'],server_rows)}

Before the Adzuna Remote fix, all three Remote windows returned zero because `Remote` was supplied as a geographic place. Searching remote as a keyword returned one in both the 7-day and 30-day checks. This does not automatically establish remote eligibility: the structured location/work-arrangement guard still controls approval.

All three windows for Indeed, LinkedIn, Glassdoor, and ZipRecruiter failed with Brave HTTP 402. Their raw search returns are unknown. USAJOBS previously imposed DatePosted 30 and Brave board discovery imposed freshness pm; unrestricted discovery now omits those forced date filters while diagnostic windows remain explicit.

The following are observed date windows within returned feeds, **not separate server searches**:

{table(['Source','24 hours','7 days','30 days','Undated'],window_rows)}

Greenhouse supplies an update timestamp, Workable a creation timestamp, and other feeds their publication field. Lever supplies no usable date in this adapter, so its window counts are unavailable rather than actual zeros. Fresh feed timestamps and retry timing can move a boundary. Remotive's separate official API diagnostic returned 16 records, none passing current deterministic filters; the configured normal path remains its category RSS. No feed API date-window support was invented.

## Proven defects and repairs

- **Premature truncation:** global default 50 and Remotive's daily review limit capped discovery. Default source limits are now zero/unlimited; the review limit no longer controls discovery. The regression passes 301 listings through the default acquisition path.
- **Employment normalization:** Ashby FullTime became fulltime and failed the full-time filter. The initial diagnostic identifies 183 affected full-time records. Normalization now maps FullTime to full-time; Contract still fails the configured rule.
- **Pagination:** Adzuna and USAJOBS now continue using returned totals. Lever follows documented skip/limit pagination instead of stopping at 200 per employer; a live retry returned 264 postings for solidcore. Repeating pages fail explicitly. [Lever API documentation](https://github.com/lever/postings-api#Get-a-list-of-postings).
- **Query coverage:** all 16 historical role queries and eight preferred locations reach query adapters, replacing four broad board-search terms and Utah/Remote-only request construction. Utah cities and explicitly Remote searches remain enabled.
- **Adzuna Remote search:** Remote is searched as a term rather than an unsupported geographic place, while structured eligibility remains unchanged.
- **Failure reporting:** successful queries survive another query's failure. ATS board failures, Web Careers errors, and failed RSS feeds appear in source errors/partial health. Search dry runs return an error status for partial discovery instead of implying full success.
- **Metric reconciliation:** Remotive counts fetched listings separately from selected/imported candidates. Missing content, dead links, named deterministic reasons, and explicit limits are now represented separately. Source attempt counts do not double-count partial failures.
- **ID collision safety:** a numeric record ID cannot match a different posting for a managed tracker update. Large-description comparisons also wait until company/title anchors pass, preserving duplicate decisions while avoiding unnecessary work.
- **The Muse adapter:** page one maps to API page zero and complete API pages are retained. Live execution remains credential-blocked. [The Muse API documentation](https://www.themuse.com/developers/api/v2) shows page zero and page sizes; its published terms require app registration for ongoing use.

## Migration and remaining failures

The G-drive and initial C-drive configuration have the same 17 enabled sources, 16 roles, eight preferred locations, and employer counts. The G-drive database still has 1,932 records and matches the source totals in the preserved C-drive backup. The 50-record cap exists in the G configuration too and predates migration. Runtime roots and all four inspected Gecko scheduled-task working directories resolve to C:\\gecko_main; credentials for Adzuna, USAJOBS and Brave are present. None of those four tasks is a daily-discovery task. The Indeed authorized integration and The Muse key are absent. Search discovery uses Brave as its Indeed fallback, and the standard daily command includes Indeed in CORE_PROVIDERS. It was attempted, then failed with HTTP 402; it is not silently absent from daily.

Persistent blockers are Brave payment failures for Web Careers and four board adapters; missing The Muse credentials; Greenhouse Hightouch and Outschool boards returning 404; Ashby Checkbox Technology returning 404 and Goodlord connection failure; and Lever Oxylabs and Suger.io failures. Initial DNS/timeouts on Workable, We Work Remotely and Working Nomads recovered on retry. HTTP 403 on the Adzuna candidate URLs remains a review condition. No account, billing setting, employer identity, or unavailable credential was guessed or changed.

## Files changed and validation

Runtime changes: `job-scout/scout.py`, `service.py`, `google_tracker.py`, `normalize/__init__.py`, `deduplicate/__init__.py`, `preferences/job-sources.json`, and `sources/acquisition.py`, `base.py`, `config.py`, `adzuna.py`, `ats.py`, `usajobs.py`, `search_discovery.py`, `themuse.py`, `indeed.py`.

Tests: new `job-scout/tests/test_discovery_audit_regressions.py`, plus a new ID-collision regression and corrected posting identity in the existing expiry fixture in `test_google_tracker.py`. Existing unrelated working-tree changes were preserved.

Reusable audit tools: `scripts/audit_job_discovery.py`, `audit_discovery_windows.py`, `reconcile_discovery_audit.py`, and `build_discovery_audit_report.py`. They save evidence locally. The collection tools do not open the writable production JobStore or invoke resumes, applications, cleanup, or tracker import.

**45 focused offline tests pass**, including 17 newly added regressions. The earlier scout suite passed 48 tests and source suite passed 25. Compile checks and diff whitespace checks pass. The full tracker suite is **not green**: 51 tests, 3 failures and 8 errors, reflecting remaining legacy Status/column/timestamp fixtures. See `test-results.txt` and `full-tracker-tests.txt`; those limitations are not reported as successful validation.

## Recovery and safe rediscovery

The observed sources expose **{r['new_unique']} new unique candidates**, of which **{r['eligible_new_unique']} pass structured approval**. Live URL checks confirm **{valid}** candidates, while **{pending}** remain access-review cases and none is confirmed dead. These are a measured recovery opportunity, not promised tracker additions: manual state, fees, applications, rejection history, and current URL identity must be rechecked before import. Unreachable sources can contain additional jobs, so a total for all recoverable jobs is not established.

A full uncapped rediscovery is warranted after these repairs. Backfill is needed for verified candidates if Dave later authorizes repopulation. Historical unverified records require fresh URL review; Jooble provenance and permanent rejections must stay excluded. This audit did not repopulate or clear Job List.

Safe complete discovery preview from C:\\gecko_main:

```powershell
python job-scout/scout.py search --source all --dry-run --results 50
```

The command uses a temporary database copy and performs no tracker import, resume generation, or applications. `--results 50` controls page size, not a per-source total; supported pagination continues. Partial provider failures make the search exit nonzero and remain visible. Do not use the daily/orchestrator apply command for this audit because it includes resumes and other live work.

The evidence collector can also be repeated independently:

```powershell
python scripts/audit_job_discovery.py --output reports/discovery-audit/next-check
```

Raw historical per-source exclusions, historical HTTP hits, and the exact remembered 1,600-job run remain unidentifiable where logs did not retain them. Current record decisions are fully reconciled; no missing historical metric is substituted with a guess.
'''
    (OUT/'REPORT.md').write_text(report,encoding='utf-8')
    print('Report written:',OUT/'REPORT.md')

if __name__=='__main__':main()
