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

`Daily Tasks` row 1 contains `DAILY TASKS` and is frozen. Each report starts with `GECKO DAILY TASKS REPORT`, a human-readable date, and nine sections: Run Information, Job Discovery, Tracker Changes, Deleted Jobs Protection, Indeed Status, Resume Readiness, Application Readiness, Errors & Script Health, and Audit Information. Metric labels are in A and values in B. The Job Discovery section also has `Existing Tracker Jobs by Source` in E and `Jobs in Tracker` in F, followed by one source per row, sorted by count descending. These counts are existing `Job Scout` ledger rows, not jobs found by this report execution. The section expands with the source count, so following sections cannot overlap. A blank row separates sections and reporting dates.

The dashboard keeps five distinct dates, newest first. Its owned area is A:F through the end of the fifth block. The writer checks for unrelated content, formulas, ARRAYFORMULA spill risk, and protected ranges before writing. It never clears the whole worksheet or creates a tab. A user-owned cell that would conflict with expansion stops the write. Column widths and the frozen header are set on the initial empty installation; section and status formatting stays inside the owned A:F rows. The writer reads the cells back after writing. A local `.dashboard-pending.json` plan permits a retry to finish a partial values write only when every affected cell still matches the old or planned value; other changes stop recovery for review.

`Daily Run` receives the newest block at row 3, pushing older blocks down. Metric labels and values occupy A:B. `Jobs by Source` stays at E9 for the newest block, with source labels at E10 and numeric counts at F10. `Report Details` is omitted from this history block. Only the 17 named discovery, projection, and resume-reuse metrics render missing or unavailable values as numeric zero; the audit JSON and unrelated unavailable fields retain their original meanings. A repeated run ID does not insert a second block.

The audit JSON retains every machine-readable metric, proposed action, warning, and safety hash. The visible `Report Details` cell is a short summary. `Audit Log Location` contains a local `file:///` URI; whether Google Sheets opens a local file link depends on the browser and its permissions. Existing local audit files are not removed when a date rolls off the dashboard.

## Counts and safety

`Actual Before` and `Actual After` are counts of nonempty job rows read before and after reporting. The command checks that all source job tabs have the same content hash before and after the dashboard write. `Indeed Actual` counts Indeed rows in `Job Scout`. Existing resume and readiness counts derive from tracker values and the canonical read-only queue classifier. An X in `Resume Created` blocks regeneration even with a blank link; Cost x, permanent rejection, and expired Indeed statuses retain their existing protections.

Discovery and projected changes require actual provider or page work, which this command does not perform. The `Daily Tasks` dashboard continues to display `Unavailable` for those metrics. The `Daily Run` history uses the narrow numeric-zero display rule above. The source table is explicitly an existing ledger breakdown. `WARNING` means the read-only checks passed with those unavailable signals; `FAIL` means a required read, write, readback, or source-data safety check failed. Full errors remain in the local audit. The older `python job-scout/scout.py daily-report --dry-run` is console-only and does not write the dashboard.
