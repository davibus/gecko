# Indeed direct-search collector

The new collector reads public Indeed search result pages, follows observed Next
Page links, and retrieves the full public posting for each distinct Indeed job
key. It uses the existing local Firecrawl credential. It does not depend on Brave
index coverage, read email, submit applications, or impersonate a signed-in user.
Personalized homepage coverage is not claimed.

Standalone discovery and append-only import:

```powershell
& C:\gecko_main\.tools\dashboard-python\Scripts\python.exe C:\gecko_main\scripts\search_indeed.py --query "digital marketing" --location Utah --max-pages 5 --max-jobs 150
```

Repeat --query / --location for additional searches. Without those arguments the
collector searches digital marketing, paid search, performance marketing, and
marketing analytics in Utah and Remote. --collect-only saves evidence without
writing tracker data. No resumes or applications are started by this command.

The canonical provider factory supports mode `public-search` in the existing
Indeed provider settings, with optional queries, locations, max_pages and
max_jobs. Indeed is now configured in this mode for normal discovery, with five
pages per search and a shared budget of 150 distinct postings per run.

## Verification and limits

- Require one structured JobPosting whose Indeed job key and title match the
  result card. Redirects to another identity, missing descriptions, and blocked
  pages are reported rather than fabricated as jobs.
- Use the existing role, geography, employment, rejection and deduplication rules.
- Standalone imports append new rows; existing tracker rows remain unchanged.
  IDs are allocated by the canonical store. An interrupted import can recover
  an already-stored exact Indeed identity without making another job.
- Fetch sequentially with seven seconds between request starts. Throttled reads
  wait sixty seconds and retry at most twice. Auth failures and blocked access
  are not bypassed.
- Budgets limit cost and runtime. Reaching a budget is **partial coverage**,
  never a claim to have collected every Indeed job. One inaccessible posting
  does not discard successful postings.
- Each run saves listings, page evidence, failures, limits, a pre-import database
  backup, and before/after import readback under reports/indeed-search/.
- SQLite remains authoritative; this command never writes Google Sheets.

The Indeed chat connector can independently search Indeed, but the available
search tool returns a limited batch and exposes no pagination argument. It is
not a callable local-app credential or a replacement for this collector.
