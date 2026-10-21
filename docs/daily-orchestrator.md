# Gecko daily orchestrator

## Columns follow names, not positions

Users may move whole columns freely without asking for code or instruction updates.
Read live headers on every sync; use unique header names for fields and stable IDs
for jobs. Never restore a saved order or treat column letters/counts in documentation
as requirements. Automatic idle sync adopts the current order and preserves custom
columns, resume links and Sheet formulas. Moving columns is different from renaming
or deleting a field: missing or ambiguous names must be resolved without guessing.
Keep row 1 frozen. Historical layout tables are reference snapshots only.


## Current column layout — October 20, 2026

See `docs/current-tracker-columns.md` (repository-relative) for the verified 36-column layout and field behavior. This supersedes historical letters and schemas below. Resolve unique live headers by name and jobs by ID; never sort or move only part of a job row. Qualifies to Apply? is the eligibility field (legacy internal alias Apply?). Applied Date is primary; Previous Applied Date is preserved history, wherever those named columns are moved. Cover Letter, CV Created Date, Cover Letter Link, and Cover Letter Created Date remain user-managed. Create Resume is a preserved Sheet formula showing Yes only when Enough Data is Yes; it does not start generation. Enough Data is a saved review, not an automatic AI assessment. Preserve Job Description, Notes, Previous Notes, word-count formulas, all jobs and resumes, and frozen row 1. The removed Cursor Instructions tab must not be recreated automatically.

From the Gecko Main directory, run:

```powershell
python scripts/gecko_daily.py --dry-run
python scripts/gecko_daily.py --apply
```

For a full daily run that limits **resume generation** to specified live
Column A IDs, use `python scripts/gecko_daily.py --apply --resume-ids 2218 2219`.
Discovery, tracker sync, Gmail, and Daily Run reporting still run. The ID
limit is verified before those steps begin. Completed IDs remain skipped.

The default without a flag is `--dry-run`. `--apply` first verifies the live
workbook title, the configured `Job List` and `Rejected Jobs` headers, the
canonical resume queue, the source resume files, and the existing `Daily Run`
history layout. If `Daily Run` is missing or unsafe to write, it stops before
discovery or any job, resume, or Gmail changes. It never creates tabs.

After preflight, the command runs the existing `job-scout/scout.py daily`
workflow. That workflow searches configured sources, including automated
Indeed discovery, handles manual Indeed intake, syncs the tracker, runs the
canonical all-source resume queue, and checks Gmail for employer replies.
During the daily run, declined rows are retained and skipped by Indeed intake;
Gecko does not move formula-bearing ledger rows to clean them up.
It consults rejection history, avoids duplicates, and preserves completed
`Resume Created = X` rows and their links. Only approved and geographically
eligible jobs enter resume generation. It does not submit applications.

The orchestrator records the final labeled workflow counts in the existing
`Daily Run` tab, with new jobs, duplicates, resumes created and reused, Gmail
responses, errors, and attention items. Each execution has a unique Run ID.
It also saves a JSON audit and captured command log under
`reports/daily/YYYY-MM-DD/`. A failed workflow is recorded as failed when the
history tab remains available. If the history write itself fails, the local
audit records the failure and the command exits nonzero.

The dry run invokes the existing daily preview, which can perform provider
requests, read the live Sheet, and write local logs or temporary SQLite state;
it does not update Sheet cells or generate resumes. Gmail is skipped in the
preview, so its counts are shown as `Unavailable`.

Run `python scripts/archive_applied_resumes.py --apply` separately after
application decisions. Gecko never submits an application from this command.

## Test only selected resume IDs

To generate resumes only for named live Column A IDs, use the canonical queue
directly. For example:

```powershell
python scripts/generate_apply_queue.py --dry-run --ids 2218 2219
python scripts/generate_apply_queue.py --ids 2218 2219
```

The queue verifies that each requested ID appears exactly once under the live
Column A `ID` header, then classifies and processes only those rows. It skips
unrelated rejection maintenance and does not run discovery, Gmail, or the
Daily Run report. Completed, rejected, excluded, or ineligible target rows
remain skipped under the queue's normal safeguards.
