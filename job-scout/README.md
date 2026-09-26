# Gecko Job Scout

Job Scout discovers role-relevant openings and records them in the canonical Google Sheet. It does not calculate compatibility ratings or use an evaluation field to decide whether a resume may be created.

## Daily workflow

```powershell
python job-scout/scout.py daily
```

The daily command:

1. validates known active links;
2. searches configured Adzuna, Remotive, and Web Careers sources;
3. rejects Jooble records;
4. applies the existing role-family filter;
5. deduplicates by stable provider identity, URL, company, and title;
6. appends only newly discovered jobs to `Job Scout`;
7. runs Gecko for new rows where `Apply?` is `Yes` and `Resume Created` is blank.

`python job-scout/scout.py daily --dry-run` uses a temporary SQLite copy and does not write the Google Sheet, descriptions, resumes, or reports. A failure for one job is logged without stopping later jobs.

The standalone retry command remains:

```powershell
python scripts/generate_apply_queue.py
```

It reads columns by header name, requires `Apply? = Yes`, requires a blank `Resume Created`, and never depends on a compatibility rating.

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
10. Location
11. Work Arrangement
12. Employment Type
13. Salary
14. Date Posted
15. Date Found
16. Last Seen
17. Job URL
18. Resume Link

The schema migration deletes the retired original columns J, K, L, M, V, X, and Y in place. Future writes are restricted to the headers above and never recreate or repurpose those retired columns. User formatting, filters, manual values, checkboxes, hyperlinks, and row order remain in place because writes target specific cells and structural migration uses native column deletion.

## Configuration

Copy `.env.example` to `.env.local` and configure the provider and Google Sheets credentials. The default queries live in `preferences/default.json`; they contain search preferences only.

The normal source set is `adzuna`, `remotive`, and `web-careers`. Jooble is rejected defensively during discovery, Sheet sync, and resume queue processing. Remotive is read as a remote feed, filtered to the supported role family, ordered newest first, and bounded by `--limit`.

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
```

`review` is newest-first and read-only. `select` archives the job description for Gecko. Enrichment retrieves a fuller legitimate description without reclassifying or rating the job.

## Resume handoff

Gecko evaluates the job description directly against the current master DOCX while building the tailoring plan. It produces:

- an exactly two-page DOCX after native Microsoft Word validation;
- a qualitative Match Analysis report with strengths, gaps, ATS terms, resume emphasis, and interview considerations.

No numerical compatibility value is required before generation. The completed resume is recorded only after both files exist and native QA passes.

## Data preservation

SQLite stores discovery evidence, source links, lifecycle state, enrichment text, and URL-resolution metadata. Schema migration removes obsolete evaluation columns from existing databases while preserving job records and relationships.

Google Sheet operations update only managed cells by header name. Existing `Apply?`, `Applied`, `Contacted` or note-based contact tracking, formatting, formulas, filters, conditional formatting, colors, hyperlinks, widths, frozen panes, and manual fields remain user-owned.

## Tests

```powershell
python -m unittest discover -s job-scout/tests -p "test_*.py" -v
python -m unittest discover -s scripts -p "test_*.py" -v
```

The regression suite covers schema migration idempotence, header-based writes, discovery without evaluation fields, daily orchestration, and resume creation without rating data.
