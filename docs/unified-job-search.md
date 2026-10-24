# Unified manual job search

Verified October 21, 2026 using mocked discovery APIs and Sheets only. No live
discovery, paid Firecrawl request, live Sheet write, application or schedule change
was performed.

## Audit findings

The audited shell had no installed `gecko` command. `Start-Gecko.ps1` only starts
the existing daily Windows task or reports status; it had no `job search` parser.
`scout.py search` searched internal providers and synchronized records, but did not
invoke expanded Firecrawl discovery. Firecrawl was wired into `scout.py daily`,
which also includes resume preparation and Gmail processing. Those commands remain
available with their original behavior.

This change adds a repository-local router and a search-only orchestrator. It
reuses the existing provider registry, filtering, link validation, normalization,
deduplication, JobStore, Firecrawl ledger/history, GoogleTracker cell writer,
Sheet synchronization, run lock and Daily Run block writer.

## Exact syntax

From PowerShell in `C:\gecko_main`:

```powershell
.\gecko.cmd job search --dry-run
.\gecko.cmd job search
.\gecko.cmd job search --sync-only
```

Only the first command was executed during this implementation. `--dry-run` is a
local plan: no provider requests, account calls, database writes or Sheet writes.
`--sync-only` publishes pending jobs/reports and reconciles the existing cache; it
never searches, enriches or instantiates a paid discovery client.

The bare spelling `gecko job search` works when `C:\gecko_main` is on PATH. No
global PATH, profile, alias or installed command was changed. Without that setup,
use `.\gecko.cmd` or `C:\gecko_main\gecko.cmd`. To use the bare spelling in one
PowerShell session without a persistent change:

```powershell
$env:Path = 'C:\gecko_main;' + $env:Path
gecko job search --help
```

Equivalent Python command:

```powershell
& .\.tools\dashboard-python\Scripts\python.exe .\scripts\gecko.py job search
```

Existing direct CLI syntax gains an opt-in flag:

```powershell
& .\.tools\dashboard-python\Scripts\python.exe .\job-scout\scout.py search --source all --unified
```

The router accepts `--db PATH`, `--preferences PATH`, `--sources-config PATH`,
and `--results N` (the existing internal-provider page size). Firecrawl depth uses
its existing policy, independently of `--results`. Bare `.\gecko.cmd` still starts
the existing daily task; `.\gecko.cmd --status` uses its existing status handler.
No new task is created and no recurring trigger is enabled.

## Execution sequence

1. Acquire Gecko's existing run lock and reconcile the primary Sheet with the
   working cache. Conflicting edits stop for review. Temporary availability errors
   are reported while retained local records remain available.
2. Search **all registered configured providers** with existing configured roles,
   locations, provider limits and safeguards. Disabled/unconfigured providers and
   failures remain visible in source health reporting. This means attempting each
   configured source, not a promise that every external provider will respond.
3. Deduplicate internal results through existing stable identities/source links.
   Listings already present only in the primary tracker adopt its ID and retain
   its original or unknown Found Using value. Conflicting identities stop.
4. Enrich incomplete descriptions using the existing retrieval/storage path.
   Complete cached descriptions need no additional extraction. Source descriptions
   are kept separately from manual Sheet content.
5. If both `enabled` and `daily_enabled` in `preferences/firecrawl.json` are true,
   invoke the expanded Firecrawl pipeline in the same run. These flags name the
   shared once-per-day discovery stage; they do not create a schedule. They remain
   false until separately approved. Internal discovery runs first, so shared jobs
   keep the first source and avoid another Firecrawl extraction.
6. Merge new IDs and queue publication durably before writing. Retain all full
   Firecrawl evidence and fields in existing job document storage. Firecrawl
   availability/billing failures cannot cancel successful internal discovery.
7. Drain the established Firecrawl outbox, append unique ordinary jobs, and fill
   only blank descriptive fields on existing tracker records. The named-header
   writer protects formulas and nonblank manual values, including a value typed
   during planning. Existing attribution, decisions, notes, completion markers,
   resume links and IDs remain intact. New jobs receive Gecko/Firecrawl attribution.
   Unknown historic attribution stays blank. Mandatory-fee evidence retains the
   established Cost guard. Full descriptions exceeding the Sheet cell limit stay
   intact locally, with a storage note for new rows.
8. Verify cell writes and job identities by readback, preserve frozen row 1, publish
   one combined block through the existing Daily Run writer, and reconcile the
   cache again. No resume generation, Gmail processing or application workflow is
   part of this route.

Firecrawl retains the shared 5,000-credit allocation, 100-credit soft target,
200-credit admission maximum, transactional reservations, uncertain-billing guard,
rolling 96-hour verified original posting window, cache and history. Existing
internal-source freshness rules remain unchanged. Combined reporting distinguishes
provider-confirmed costs from reserved estimates; a provider charge surprise cannot
be represented as a guaranteed exact ceiling. See [Firecrawl policy](firecrawl-discovery.md).

## Pending updates and reports

`reports/discovery/unified-pending.json` retains job IDs and undelivered report
fields. Complete job data remains in JobStore/document storage. A Sheet outage
reports publication as pending; it never claims verified delivery. Run `--sync-only`
to retry delivery without repeating searches or spending credits. Daily Run retries
use the existing Run ID check, preventing duplicate blocks.

One full combined audit per search is saved under `reports/discovery/unified/`.
Daily Run includes internal source health/results/duplicates, combined new unique
jobs, Firecrawl query coverage/expansion/freshness outcomes and credit accounting.
Repeated cached Firecrawl results are excluded from this invocation's new-job count;
Firecrawl usage remains the shared cumulative total for that Denver budget day.

## Files changed for this command integration

- Added `gecko.cmd` and `scripts/gecko.py`: repository command routing.
- Added `job-scout/unified_search.py`: orchestration, pending delivery and combined reporting.
- Modified `job-scout/scout.py`: opt-in routing, deferred publication, primary-ID adoption.
- Modified `job-scout/google_tracker.py`: opt-in blank-field enrichment and concurrent manual-value protection.
- Added `job-scout/tests/test_unified_search.py`: end-to-end mocked contracts.
- Added this guide and linked it from `docs/gecko-command.md`.

No configuration/credential, scheduled task, resume, application safeguard or live
job record was changed. Earlier uncommitted Firecrawl work remains preserved.

## Verification and limitations

Ten focused unified tests cover routing, both discovery systems, cross-source
deduplication, complete description/field preservation, Sheet readback/attribution,
blank-only enrichment, concurrent manual edits, existing primary IDs, combined
reporting, Firecrawl disabled/unavailable, reruns, no-spend synchronization and
no-network planning. Regression results are recorded in the implementation reply.
All discovery/API/Sheet behavior in these tests is mocked, with socket connections
blocked and temporary databases. Real command help and the local plan were checked.

| Regression group | Passing tests |
| --- | ---: |
| New unified workflow | 10 |
| Firecrawl, extraction, provenance, pacing, provider, sync and expanded-source contracts | 106 |
| Existing discovery audit regressions | 16 |
| Existing standalone discovery contracts | 13 |
| Existing resume queue, daily wrapper, Daily Run and SQLite cache contracts | 101 |
| Total focused passing tests | 246 |

The broader legacy GoogleTracker suite has 40 passing tests and 11 existing
failures (8 errors, 3 assertions), involving removed Status/positional fixtures and
older approval/completion expectations. The identical 11 failures reproduced using
the original HEAD tracker implementation. No unrelated fixture changes were made.
Syntax checks and `git diff --check` passed. Read-only local checks still found
1,147 jobs, no live `job_documents` table initialization, no paid history database
creation and no unified pending file. The existing Gecko task retained zero triggers.

Outstanding activation steps: use the repository-local spelling or put the project
on PATH; approve and explicitly enable Firecrawl before any paid manual run. Current
provider balance and live unified publishing remain untested. Unknown dates,
unavailable sources and identity conflicts retain their existing review safeguards.
