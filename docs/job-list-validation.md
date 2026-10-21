# Job List validation

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

Run `python scripts/validate_job_list.py --apply` to check the live `Job List`
tab. The command uses Gecko's configured service account and exact workbook
title. It resolves unique current headers, including R Last Updated and I
Notes (verified 2026-10-14), and stops on missing/ambiguous fields or changed row identity.
It does not run resume creation, archive, discovery, or
application submission.

The command checks public HTTP/HTTPS job links. Confirmed 404/410 responses and
job-specific removal evidence can clear a URL. It records the original URL in
`reports/job-list-validation/<run-id>.jsonl` first. Access restrictions,
CAPTCHAs, timeouts, and pages without company/title evidence are marked
`Needs Review` in Notes and retain their URLs. Existing
manual notes are kept. Formula cells are skipped.

Indeed application text is copied only when the page shows a recognizable
primary button or an explicit expired notice. A verified status other than
`Apply Now`, a Cost `x`, or a confirmed invalid URL sets `Apply?` to `No`.
The command never sets it to `Yes` and does not change a manual rejection.
Confirmed mandatory application fees set `Cost` to `x`; optional services do
not. Unknown cost stays blank, and the validator does not write `Free`.
Blank Cost does not by itself set `Apply?` to `No`. Ambiguous cost evidence
stays unchanged and is in the audit.

One conditional-format rule highlights A:E light red when `Apply?` is `No`
and the status, cost, or workflow-owned invalid marker meets the rule. Existing
rules remain present. This rule removes the red display automatically when its
condition no longer holds.

For an existing, verified resume URL, the named Resume Link column (currently R) displays `Company - Job Title`.
Browser-accessible HTTPS URLs use `HYPERLINK`. Google Sheets explicitly does
not make `file:///` targets clickable through `HYPERLINK`, so the command
attempts a rich-text link and verifies its target by readback. If the Sheets
API rejects it, the original URI stays in Resume Link and the warning is logged. Browsers
may still refuse to open local files directly. Blank links on rows with
`Resume Created = X` remain blank for manual review; the command creates no
resume and invents no target.

The persistent checkpoint is `reports/job-list-validation/checkpoint.json`.
An interrupted run resumes inspected rows with unchanged ID, URL, and row;
changed rows are rechecked. Successful runs mark the checkpoint complete so a
later run starts a fresh audit. The JSON summary includes changed physical row
numbers. The command compares target cells again before writing and verifies
every written value and hyperlink after each batch.
