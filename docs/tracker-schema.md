# Gecko Job Tracker live schema

Read-only verification on **2026-10-11** found that the ledger tab was renamed
from `Job Scout` to `Job List`. Its sheet ID remains `1274044170`, all 21
headers match the prior snapshot, and it has 1,460 job rows. Gecko's configured
ledger tab is now `Job List`; the 2026-10-10 table below records the earlier
name and row count.

During the 2026-10-11 failure investigation, `Daily Run` was first visible
under sheet ID `22681260` with zero rows, then absent from a later metadata
read. The reporting command now stops before writing `Daily Tasks` if
`Daily Run` is missing. This live tab state must be checked again before a
report rerun; Gecko does not recreate the tab.

Read-only verification on **2026-10-10**, using the configured service account
and spreadsheet ID `1-HnqGq3Il7SZDlNdB6vChN4GAznxWh8ZHjS7Czq8t8I`.
The workbook title was `Gecko Job Tracker`. This is a snapshot, never a fixed
column map. `job-scout/tracker_schema.py` defines logical fields and tab roles;
`GoogleTracker.discover_workbook()` reads current tabs and headers. Every writer
must reread headers and formula state immediately before writing.

| Live tab | Sheet ID | Layout and owner | Data rows |
| --- | ---: | --- | ---: |
| `Daily Run` | 22681260 | Run-history blocks inserted at row 3 by `scripts/daily_report.py` | 0 on latest read |
| `Daily Tasks` | 1035087580 | Five-date vertical dashboard; `scripts/daily_report.py` owns report blocks in A:F | 0 before the new dashboard |
| `Job Scout` | 1274044170 | Row 1 job headers; canonical ledger | 1,441 |
| `Deleted Jobs` | 1798362999 | Empty; no header or inferred writer | 0 |
| `Scratch` | 1775950516 | Empty, unassigned; no inferred writer | 0 |
| `Rejected Jobs` (hidden) | 1868015582 | Row 1 rejection headers; durable archive | 30 |

`Daily Run` is the same sheet ID previously observed under `Daily Reports` and `Sheet7`. Its older report blocks are preserved when new history is inserted at row 3. The reporting command also writes the `Daily Tasks` dashboard. `Daily Reports` and `List of Job Sources` are absent; do not recreate or rename them. There is no `Indeed` or `Job Tracker` tab. Indeed records are `Job Scout` rows with `Source = Indeed`. Unknown future tabs are unassigned until verified.

## Exact physical headers

`Job Scout`, row 1, current order: A `ID`; B `Source`; C `Company`; D `Job Title`; E `Status`; F `Apply?`; G `Resume Created`; H `Applied`; I `Cost`; J `Notes`; K `Apply or on Company Website (If Indeed)`; L `Response`; M `Location`; N `Work Arrangement`; O `Employment Type`; P `Salary`; Q `Job URL`; R `Resume Link`; S `Date Posted`; T `Date Found`; U `Last Seen`. Positions are diagnostic only.

`Rejected Jobs`, row 1: A `Source`; B `Job ID`; C `Original Job URL`; D `Normalized Job URL`; E `Company`; F `Job Title`; G `Date Rejected`; H `Reason or Status`.

`Daily Tasks` has no named header row for job data. Its owned reporting area is A:F, with `DAILY TASKS` at A1, followed by at most five variable-height vertical blocks in descending reporting-date order. Metric labels and values use A/B. Existing tracker source counts use E/F within each Job Discovery section. The report checks for unrelated content before expanding. `Daily Run` blocks use A/B for metrics and E9:F for source counts in the newest block; the report inserts at row 3.

`Deleted Jobs` and `Scratch` have no populated cells or established schema.

The full grid had zero cell-validation rules and zero protected ranges on all
six tabs. `Job Scout` had 518 cell formulas, all in `Cost`; other tabs had
none. It also had two conditional-format rules and one frozen header row. The
current `Cost` formulas test `Job URL` for `jobicy|jooble` and yield `x` or
blank. Queue eligibility reads effective values; writers inspect formula text
and skip protected cells. Never encode today's formula letters in code.

## Runtime mapping and write boundaries

`ID` is the current physical header for logical `Scout ID`; `Status` for
`Gecko Status`; `Apply?` can be `Apply` in an older verified sheet. These are
the only approved aliases. Missing, duplicate, or ambiguous required headers
stop writes. Reordered and extra user columns are safe when named fields stay
unique. `Job Scout` and `Rejected Jobs` are required for job processing;
`Daily Tasks`, `Daily Run`, and `Deleted Jobs` are additionally required for the reporting
command. No command creates or renames tabs implicitly. A missing required
tab is an explicit blocker.

Writers update only managed named cells, reread target identities and formula
state, preserve user fields, and verify changes by readback. ARRAYFORMULA
anchors and possible output ranges are protected. Row moves, sorting, and
deletion stop when formulas cannot be kept with their jobs. `Applied`, `Cost`,
and `Response` are manual/protected for ordinary syncs; only the conservative
Gmail response checker may update `Response`.

## Canonical job rules

- Source-qualified stable Job ID is primary rejection identity; Indeed uses
  `jk`. Normalized canonical URL is fallback. Company/title alone never
  permanently rejects a listing. `Rejected Jobs` records are written and
  verified before a marked visible row can be removed.
- An existing `Resume Created = X`, ignoring case/spaces, always stops
  generation and preserves its link, even if blank. Blank link means manual
  review. A nonblank link with blank marker also stops generation for review.
  Effective `Cost = x` excludes creation. Only qualified `Apply? = Yes` rows
  with both completion fields blank enter the resume queue.
- Utah jobs (including on-site/hybrid) and explicitly remote jobs can get
  `Apply? = Yes` from `Location` and `Work Arrangement` only. Blank arrangement
  is not remote. Other values are preserved. Expired Indeed jobs get `No`.
- The Indeed application/status field stores exact verified visible text.
  Preserve manual and unverifiable states. Only `This job has expired on Indeed`
  or `Expired`, ignoring case/spaces, normalize to `Expired` and set `Apply?`
  to `No` in unprotected cells.
- After validated DOCX creation, a new completion may write `X`, a raw
  `file:///` URI from `Path.resolve().as_uri()`, and an appropriate status.
  It never overwrites an existing resume or downgrades a later status.

## Verified commands and effects

`python scripts/daily_report.py --dry-run` reads the live ledger, writes
the owned vertical dashboard in `Daily Tasks`, inserts `Daily Run` history, and saves local audit logs. It does not
run discovery, page verification, Gmail, resume generation, or job writes.
Run-level metrics requiring those operations are `Unavailable`. The older
`python job-scout/scout.py daily-report --dry-run` prints a console snapshot
without a report-tab write. `python job-scout/scout.py daily --dry-run` is a
separate preview that still opens SQLite and writes a queue log. The live
`python job-scout/scout.py daily` runs discovery, Sheet sync, the canonical
resume queue, and the response check. None submits applications.
