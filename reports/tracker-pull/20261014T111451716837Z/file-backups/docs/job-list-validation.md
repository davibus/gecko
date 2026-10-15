# Job List validation

Run `python scripts/validate_job_list.py --apply` to check the live `Job List`
tab. The command uses Gecko's configured service account and exact workbook
title. It resolves unique current headers, including I Last Updated and J
Notes, and stops on missing/ambiguous fields or changed row identity.
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
