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
- **Gecko Job Description** and **FireCrawl Job Description** replace the former single Job Description column (October 22, 2026). Gecko search writes to the Gecko field; Firecrawl search writes to the FireCrawl field. Resolve these by name even when columns move. Preserve populated/manual/formula descriptions and the other tool's field. Do not recreate the retired Job Description heading. Legacy single-column workbooks remain supported. Readers use the most complete available saved tool description through a read-only compatibility alias; this does not merge the physical columns. Selected resume runs synchronize saved Sheet edits first. Missing/incomplete descriptions never authorize a generic resume.
- **Enough Data** automatically receives a content review for newly added jobs (Dave's October 22 update). Yes means the actual job description has pertinent role duties, requirements, skills or outcomes sufficient to tailor a resume. No means missing, irrelevant, random, generic-only or otherwise unusable information. This is a semantic review through the existing read-only inference runner, not a word-count formula, candidate-fit score or generation authorization. Source-supported reasons and evidence are cached; runner failures fail closed as No with review pending. Preserve existing manual decisions. Create Resume follows the saved Yes/No value and never starts generation itself.
- **# Words** counts Notes; **# Job Desc Words** counts Job Description; **Total Words** adds those counts. Preserve their Sheet-owned formulas and synchronize their calculated results. Do not overwrite formulas with local counts.
- **Resume Created Date** records the actual verified resume completion date and is written with each new resume completion. Preserve existing historical dates; do not infer missing historical dates.
- **Notes** is the main operational notes field. **Previous Notes** is the preserved earlier copy; leave its contents intact.
- Preserve custom columns, notes, formatting, column widths, formulas, job IDs, resume links, completed markers, and application history. Never restore a historical column order.
- Empty trailing headings are not additional named columns. A populated unnamed column or a duplicate heading requires review instead of guessing where to write.

## Salary display — October 22, 2026

Standardize Salary as `$312,000` or `$124,800 - $124,800`, including comma
separators and a dollar sign on both range bounds. Recover explicit pay from Notes
or Job Description when needed. Prefer an advertised salary range over alternate
rates in descriptive text; use the first listed range when otherwise equally
ranked, preserving the original amounts and conditions in Notes. Keep Salary
blank when no reliable amount is available; move substantive source text to
Notes rather than leaving prose or placeholders in Salary.
Annualize hourly/monthly rates as Dave requested: use stated hours or otherwise
40 hours/week × 52 weeks/year; monthly × 12, weekly × 52, daily × 260. Preserve
the conversion assumptions and estimate/OTE/bound-only qualifications in Notes.
Retain non-USD currency labels; never silently convert currencies. Sheet sync
applies this to existing and new jobs, preserving formula cells, raw discovery
salary evidence, all other fields, and an audit of the original values.

## New-job row structure — October 22, 2026

Primary Sheet synchronization extends existing table/filter/formatting ranges as
jobs are appended, preserving filter choices and custom formatting. Filters that
have been turned off stay off; never recreate them automatically. New tail rows
inherit missing formatting and the existing per-row formulas for Ready to Apply?,
Create Resume, # Words, # Job Desc Words, and Total Words. Resolve these fields by
name, adjust relative references, and never overwrite a populated cell or copy
another job's values. Recalculate and verify the formulas in Sheets before caching
their outputs locally. Keep row 1 frozen and preserve all existing job history.

The central runtime contract is `job-scout/tracker_schema.py`. `CURRENT_SCOUT_HEADERS` records this named-header snapshot; `LEGACY_SCOUT_HEADERS` is retained solely for older-layout compatibility tests. Runtime writers must not require either order. Google Sheets remains responsible for its formatting and formulas; synchronization uses named fields and verifies writes.

October 22 formula-extension update: the renamed **# (Gecko) Words**, **# (FC) Job Desc Words**, and **Total Words** fields inherit their existing row-relative formulas and formatting through the final job row whenever jobs are appended. **Enough Data** inherits formatting/validation and receives the content-review result described above; do not copy another job's literal Yes or invent a word-count threshold. Repair missing formulas independently per column even when another column already reaches the bottom. Preserve populated formulas, manual values and row 1 freezing.


## Completion dates — user instruction October 20, 2026

Whenever a confirmed application is marked Applied, write its actual submission date to **Applied Date** in the same update. Use America/Denver dates (YYYY-MM-DD); when Dave confirms submitting today, use today. Preserve **Previous Applied Date** as history. If the actual date is unknown, ask rather than inventing it.

Whenever a resume is successfully created and verified, write its actual completion date to **Resume Created Date** together with Resume Created and Resume Link. Do not substitute CV Created Date or overwrite historical dates merely during sync. Resolve all columns by unique header name, never position. Verify both the completion marker and date by readback. This supersedes earlier wording treating Resume Created Date as exclusively user-managed.
