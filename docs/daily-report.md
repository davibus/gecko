# Daily dry-run report

Run `python scripts/daily_report.py --dry-run` from Gecko Main. This is a report-only command: it reads the current Google Sheet, writes the owned vertical dashboard in `Daily Tasks`, inserts a run-history block in `Daily Run`, and saves local JSON and event logs under `reports/daily/YYYY-MM-DD/`. It does not run discovery, Indeed page checks, Gmail tracking, resume creation, tracker synchronization, or applications. Existing `Daily Run` history is preserved below the new block.

On 2026-10-11 the live job ledger was renamed to `Job List` while retaining
the same sheet ID and headers. The report uses that current tab name. A missing
configured ledger tab stops before either report write; a failed CLI message
then says `not written` instead of implying a history retry was found.
The `Daily Run` tab was absent on a later read that morning. The report now
preflights it before updating `Daily Tasks`; do not run the standard report
until the tab is present and its identity and history have been checked. The
`--refresh-today` path below updates only `Daily Tasks` and does not depend on
`Daily Run`.

The command accepts `--verbose`, `--json`, `--date YYYY-MM-DD`, and `--run-id RUN_ID`. The date defaults to America/Denver today. A new run ID identifies each execution and its separate local audit. Rerunning a date replaces that date's dashboard block in its chronological position. A date older than the five newest dates keeps its local audit but does not displace a newer dashboard report.

To repair a failed report whose audit has complete metrics and whose validated
source hash still matches the live ledger, run `python scripts/daily_report.py
--reconcile-audit RUN_ID`. It keeps the original failed JSON intact and writes
`RUN_ID.reconciliation.json` with per-tab readback status. If `Daily Run` was
verified missing and its empty history can safely be restored, add
`--restore-missing-daily-run`. If the dashboard has only its A1 title and an
earlier verified date must be restored, add `--restore-history-audit PATH`.
The repair does not run job discovery, resume generation, or applications.
It refuses to replace a different run ID already present for the same date.
Retrying the repair verifies already committed rows before any insertion.

If `Daily Run` already contains a verified run but its `Daily Tasks` block was
deleted, use `python scripts/daily_report.py --restore-daily-tasks-audit RUN_ID`.
Add `--restore-history-audit PATH` only when the dashboard is empty and an
earlier verified date also needs rebuilding. This command uses the existing
Run ID, checks the audit source hash against the live job data, and writes only
the missing Daily Tasks blocks. A matching populated block is verified without
a second write. It never inserts another Daily Run block. If physical Daily
Tasks rows were deleted, the writer appends only the rows needed for the
dashboard before writing the owned A:F values.

Use `python scripts/daily_report.py --refresh-today` to refresh the current
America/Denver date in `Daily Tasks` without reading or writing `Daily Run`.
It uses current validated ledger and queue data, replaces the existing date
block or creates one if absent, and records changed A:F cell addresses and
whether the date was updated or created in its local audit. `--date` cannot
be combined with `--refresh-today`. A new date is refused if adding it would
evict one of five historical dates. The pending dashboard plan supports a
retry with the same `--run-id` after an interrupted write. The command verifies
today's Run ID, historical date values, unrelated cells, and source tab hashes
after the write.

## Dashboard layout

`Daily Tasks` row 1 contains `DAILY TASKS` and is frozen. Each report starts with `GECKO DAILY TASKS REPORT`, a human-readable date, and nine sections: Run Information, Job Discovery, Tracker Changes, Deleted Jobs Protection, Indeed Status, Resume Readiness, Application Readiness, Errors & Script Health, and Audit Information. Metric labels are in A and values in B. The first report's source table begins at E9:F9 with `Existing Tracker Jobs by Source` and `Jobs in Tracker`; source counts start at E10:F10, sorted by count descending. The table runs beside the A:B sections without replacing their metrics. These counts are existing ledger rows, not jobs found by this report execution. A blank row separates reporting dates. The writer recognizes the earlier E15:F source layout and converts owned report blocks on the next write.

The dashboard keeps five distinct dates, newest first. Its owned area is A:F through the end of the fifth block. The writer checks for unrelated content, formulas, ARRAYFORMULA spill risk, and protected ranges before writing. It never clears the whole worksheet or creates a tab. A user-owned cell that would conflict with expansion stops the write. Column widths and the frozen header are set on the initial empty installation; section and status formatting stays inside the owned A:F rows. The writer reads the cells back after writing. A local `.dashboard-pending.json` plan permits a retry to finish a partial values write only when every affected cell still matches the old or planned value; other changes stop recovery for review.

`Daily Run` receives the newest block at row 3, pushing older blocks down. Metric labels and values occupy A:B. `Jobs by Source` stays at E9 for the newest block, with source labels at E10 and numeric counts at F10. `Report Details` is omitted from this history block. Only the 17 named discovery, projection, and resume-reuse metrics render missing or unavailable values as numeric zero; the audit JSON and unrelated unavailable fields retain their original meanings. A repeated run ID does not insert a second block.

The audit JSON retains every machine-readable metric, proposed action, warning, and safety hash. The visible `Report Details` cell is a short summary. `Audit Log Location` contains a local `file:///` URI; whether Google Sheets opens a local file link depends on the browser and its permissions. Existing local audit files are not removed when a date rolls off the dashboard.

## Counts and safety

`Actual Before` and `Actual After` are counts of nonempty job rows read before and after reporting. The command checks that all source job tabs have the same content hash before and after the dashboard write. `Indeed Actual` counts Indeed rows in `Job List`. Existing resume and readiness counts derive from tracker values and the canonical read-only queue classifier. An X in `Resume Created` blocks regeneration even with a blank link; Cost x, permanent rejection, and expired Indeed statuses retain their existing protections.

Discovery and projected changes require actual provider or page work, which this command does not perform. The `Daily Tasks` dashboard continues to display `Unavailable` for those metrics. The `Daily Run` history uses the narrow numeric-zero display rule above. The source table is explicitly an existing ledger breakdown. `WARNING` means the read-only checks passed with those unavailable signals; `FAIL` means a required read, write, readback, or source-data safety check failed. Full errors remain in the local audit. The older `python job-scout/scout.py daily-report --dry-run` is console-only and does not write the dashboard.
