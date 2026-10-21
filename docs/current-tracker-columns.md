# Current Gecko tracker columns

## Columns follow names, not positions

Users may move whole columns freely without asking for code or instruction updates.
Read live headers on every sync; use unique header names for fields and stable IDs
for jobs. Never restore a saved order or treat column letters/counts in documentation
as requirements. Automatic idle sync adopts the current order and preserves custom
columns, resume links and Sheet formulas. Moving columns is different from renaming
or deleting a field: missing or ambiguous names must be resolved without guessing.
Keep row 1 frozen. Historical layout tables are reference snapshots only.


**Frozen header rule:** Always keep row 1 frozen on every Gecko tracker tab and new tracker/export sheet. Preserve any larger existing frozen region. Column edits, reordering, syncing, formatting, and exports must never unfreeze row 1. Verify this after spreadsheet changes.

Verified October 20, 2026. The existing Gecko Job Tracker Google Sheet is the primary tracker; SQLite is its working cache and stores discovery details and resume attachments. The layout below is a snapshot, not a positional write map. Always resolve unique current headers by name and jobs by stable ID. New or rearranged columns must not change which field receives a write.

| Column | Header |
| --- | --- |
| A | ID |
| B | Company |
| C | Job Title |
| D | Applied |
| E | Applied Date |
| F | Source |
| G | Qualifies to Apply? |
| H | Cover Letter |
| I | CV Created Date |
| J | Create Resume |
| K | Resume Created |
| L | Cost |
| M | Previous Notes |
| N | Apply or on Company Website (If Indeed) |
| O | Response |
| P | Location |
| Q | Work Arrangement |
| R | Employment Type |
| S | Salary |
| T | Job URL |
| U | Resume Link |
| V | Resume Created Date |
| W | Cover Letter Link |
| X | Cover Letter Created Date |
| Y | Last Updated |
| Z | Date Posted |
| AA | Date Found |
| AB | Last Seen |
| AC | Personal priority |
| AD | Previous Applied Date |
| AE | Notes |
| AF | Job Description |
| AG | Enough Data |
| AH | # Words |
| AI | # Job Desc Words |
| AJ | Total Words |

## Field behavior

- **Applied Date** is the main application date. **Previous Applied Date** preserves the earlier date history; never merge conflicting dates silently.
- **Cover Letter**, **CV Created Date**, **Cover Letter Link**, and **Cover Letter Created Date** are user-managed fields. Preserve their contents; do not infer generation actions, dates, or a meaning for CV beyond its heading.
- The former **Cursor Instructions** tab is absent from the current workbook. Do not recreate it automatically; current Gecko guidance lives in the repository.

- **Qualifies to Apply?** retains the prior Apply? eligibility meaning and Yes/No values. Internal `Apply?` is a compatibility alias, never a second physical column.
- **Create Resume** uses a Sheet-owned per-row formula: show Yes when Enough Data is Yes (case-insensitive, trimmed); otherwise show blank. Preserve the formula and sync its calculated value. This display does not itself start or select resume generation. Use the dashboard Create resume actions; existing eligibility and completed-resume protections still apply.
- **Job Description** is user-editable text and takes priority during resume generation. Selected resume runs synchronize saved Sheet edits first. A blank description retains normal retrieval fallback; incomplete text never authorizes a generic resume.
- **Enough Data** records a saved review of Job Description plus Notes. It does not automatically reassess new or edited text. Create Resume follows this saved value; that formula is not an AI assessment. Do not infer a generation gate from the heading.
- **# Words** counts Notes; **# Job Desc Words** counts Job Description; **Total Words** adds those counts. Preserve their Sheet-owned formulas and synchronize their calculated results. Do not overwrite formulas with local counts.
- **Resume Created Date** records the actual verified resume completion date and is written with each new resume completion. Preserve existing historical dates; do not infer missing historical dates.
- **Notes** is the main operational notes field. **Previous Notes** is the preserved earlier copy; leave its contents intact.
- Preserve custom columns, notes, formatting, column widths, formulas, job IDs, resume links, completed markers, and application history. Never restore a historical column order.
- Empty trailing headings are not additional named columns. A populated unnamed column or a duplicate heading requires review instead of guessing where to write.

The central runtime contract is `job-scout/tracker_schema.py`. `CURRENT_SCOUT_HEADERS` records this named-header snapshot; `LEGACY_SCOUT_HEADERS` is retained solely for older-layout compatibility tests. Runtime writers must not require either order. Google Sheets remains responsible for its formatting and formulas; synchronization uses named fields and verifies writes.


## Completion dates — user instruction October 20, 2026

Whenever a confirmed application is marked Applied, write its actual submission date to **Applied Date** in the same update. Use America/Denver dates (YYYY-MM-DD); when Dave confirms submitting today, use today. Preserve **Previous Applied Date** as history. If the actual date is unknown, ask rather than inventing it.

Whenever a resume is successfully created and verified, write its actual completion date to **Resume Created Date** together with Resume Created and Resume Link. Do not substitute CV Created Date or overwrite historical dates merely during sync. Resolve all columns by unique header name, never position. Verify both the completion marker and date by readback. This supersedes earlier wording treating Resume Created Date as exclusively user-managed.
