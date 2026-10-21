# Gecko Job Tracker live schema

## Columns follow names, not positions

Users may move whole columns freely without asking for code or instruction updates.
Read live headers on every sync; use unique header names for fields and stable IDs
for jobs. Never restore a saved order or treat column letters/counts in documentation
as requirements. Automatic idle sync adopts the current order and preserves custom
columns, resume links and Sheet formulas. Moving columns is different from renaming
or deleting a field: missing or ambiguous names must be resolved without guessing.
Keep row 1 frozen. Historical layout tables are reference snapshots only.


**Frozen header rule:** Always keep row 1 frozen on every Gecko tracker tab and new tracker/export sheet. Preserve any larger existing frozen region. Column edits, reordering, syncing, formatting, and exports must never unfreeze row 1. Verify this after spreadsheet changes.

## Current column layout — October 20, 2026

See `docs/current-tracker-columns.md` (repository-relative) for the verified 36-column layout and field behavior. This supersedes historical letters and schemas below. Resolve unique live headers by name and jobs by ID; never sort or move only part of a job row. Qualifies to Apply? is the eligibility field (legacy internal alias Apply?). Applied Date is primary; Previous Applied Date is preserved history, wherever those named columns are moved. Cover Letter, CV Created Date, Cover Letter Link, and Cover Letter Created Date remain user-managed. Create Resume is a preserved Sheet formula showing Yes only when Enough Data is Yes; it does not start generation. Enough Data is a saved review, not an automatic AI assessment. Preserve Job Description, Notes, Previous Notes, word-count formulas, all jobs and resumes, and frozen row 1. The removed Cursor Instructions tab must not be recreated automatically.

## Current update: 2026-10-14

Live Job List ID `1274044170` has 21 columns: A ID; B Source; C Company; D Job Title; E Apply?; F Resume Created; G Applied; H Cost; I Notes; J Apply or on Company Website (If Indeed); K Response; L Location; M Work Arrangement; N Employment Type; O Salary; P Job URL; Q Resume Link; R Last Updated; S Date Posted; T Date Found; U Last Seen.
This supersedes older layouts below.
Resolve fields by unique live header name; inserted/reordered columns must
not redirect writes. `Last Updated` is the user's last-run field for actual
Firecrawl or Gecko processing, with evidence-backed America/Denver date/time
and tool name. Detailed findings belong in Notes. A tracker pull never
changes the historical run date. Preserve manual content and formulas.

Scratch ID `1775950516` now contains research-column ideas; its synced local
reference is `docs/scratch-column-ideas.md`. Proposed fields are not current
headers and must not be added automatically.

The one-time local pull retains the entire current row and formulas in
`google_tracker_rows` in `job-scout/data/jobs.sqlite3` plus a JSON snapshot.
Compatible discovery fields are imported by stable ID and source; source
conflicts retain the discovery record and the exact Sheet row in the mirror.

On 2026-10-11 the generated areas `Daily Tasks!A3:F134`,
`Daily Run!A3:F140`, and `Job List!A2:T34` were value-cleared after recoverable
backups under `reports/tracker-reset/20261011T121305/`. Headers, instructions,
formulas, formats, validation, frozen rows, widths, rejection history, and
other tab contents were retained. Every existing row on all seven tabs was
explicitly sized to 21 pixels and verified by row metadata readback. New
inserted rows must also be set to 21 pixels.

Read-only verification on **2026-10-11** for the new Job List validation task
found 1,455 job rows with IDs plus six non-job rows containing only `Apply? = No`,
and these live columns: A `ID`, B `Source`,
C `Company`, D `Job Title`, E `Apply?`, F `Resume Created`, G `Applied`,
H `Cost`, I `Notes`, J `Apply or on Company Website (If Indeed)`,
K `Response`, L `Location`, M `Work Arrangement`, N `Employment Type`,
O `Salary`, P `Job URL`, Q `Resume Link`, R `Date Posted`, S `Date Found`,
T `Last Seen`. There is no `Status` header. The schema inspector accepts this
layout and resolves `Apply?` by its unique name. `scripts/validate_job_list.py` reads the tab directly through Gecko's
Sheets client, requires the fields it manages, and verifies the current A:Q
layout before writing. `Cost` contains 518 formulas; two conditional-format
rules existed before this validator. See `docs/job-list-validation.md`.

Read-only and post-write verification on **2026-10-11** found the original
`Daily Tasks` sheet ID `1035087580` temporarily named `Daily`. Its October 11
and October 10 report cells and formatting had survived. The original sheet
name was restored, and the report-only write verified the two-date dashboard
with the newest source table beginning at E9:F9. The current `Daily Run` tab
has sheet ID `2104308869`; one October 11 history block was verified there.
These live identifiers must still be reread before future writes.

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

`Job List`, row 1, current order: A `ID`; B `Source`; C `Company`; D `Job Title`; E `Apply?`; F `Resume Created`; G `Applied`; H `Cost`; I `Notes`; J `Apply or on Company Website (If Indeed)`; K `Response`; L `Location`; M `Work Arrangement`; N `Employment Type`; O `Salary`; P `Job URL`; Q `Resume Link`; R `Last Updated`; S `Date Posted`; T `Date Found`; U `Last Seen`. There is no `Status` column. Resolve unique headers at runtime.

`Rejected Jobs`, row 1: A `Source`; B `Job ID`; C `Original Job URL`; D `Normalized Job URL`; E `Company`; F `Job Title`; G `Date Rejected`; H `Reason or Status`.

`Daily Tasks` has no named header row for job data. Its owned reporting area is A:F, with `DAILY TASKS` at A1, followed by at most five vertical blocks in descending reporting-date order. Metric labels and values use A/B. The newest block begins at row 3 and its existing tracker source table begins at E9:F9, with counts below. The report checks for unrelated content before writing. `Daily Run` blocks use A/B for metrics and E9:F for source counts in the newest block; the report inserts at row 3.

`Deleted Jobs` and `Scratch` have no populated cells or established schema.

The full grid had zero cell-validation rules and zero protected ranges on all
six tabs. `Job Scout` had 518 cell formulas, all in `Cost`; other tabs had
none. It also had two conditional-format rules and one frozen header row. The
current `Cost` formulas test `Job URL` for `jobicy|jooble` and yield `x` or
blank. Queue eligibility reads effective values; writers inspect formula text
and skip protected cells. Never encode today's formula letters in code.

## Runtime mapping and write boundaries

`ID` is the current physical header for logical `Scout ID`; `Apply?` can be
`Apply` in an older verified sheet. The removed `Status` header has no alias
or required writer field. Missing, duplicate, or ambiguous required headers
stop writes. Reordered and extra user columns are safe when named fields stay
unique. `Job List` and `Rejected Jobs` are required for job processing;
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
  Effective `Cost = x` excludes creation. Only `Apply? = Yes` rows with
  verified Utah or explicit remote eligibility, `Cost` other than `x`,
  and both completion fields blank enter the resume queue.
- Utah jobs (including on-site/hybrid) and explicitly remote jobs can get
  `Apply? = Yes` when all remaining eligibility safeguards pass. Unknown Cost
  stays blank and does not block approval. Only a confirmed required application
  fee is recorded as `Cost = x`; it forces `Apply? = No` and blocks resumes.
  Unknown location does not grant approval. Expired Indeed jobs get `No`.
- The Indeed application/status field stores exact verified visible text.
  Preserve manual and unverifiable states. Only `This job has expired on Indeed`
  or `Expired`, ignoring case/spaces, normalize to `Expired` and set `Apply?`
  to `No` in unprotected cells.
- After validated DOCX creation, a new completion may write `X` and a raw
  `file:///` URI from `Path.resolve().as_uri()`.

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
