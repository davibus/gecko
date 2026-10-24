# Salary formatting — final cleanup, October 22, 2026

All 1151 job rows checked. Salary contains either a standardized amount/range or a blank; no prose entries remain.

- 49 additional salaries formatted, including Sanctuary Computer Inc (job 467): **$80,000 - $150,000**.
- 340 remaining unknown/unparseable entries left blank; substantive original text is preserved in Notes.
- 679 standardized nonblank salaries and 472 blank salaries.
- Alternate ranges and rate conditions are preserved in Notes. The advertised range is preferred; the first listed range is used for otherwise equally ranked amounts.
- Hourly/monthly rates are annualized using the recorded assumptions. Non-USD currency labels are retained.
- Raw discovery salary evidence, unrelated tracker fields and formulas remain unchanged.
- 50 relevant tests passed. Google Sheet and SQLite readback matched; repeat normalization made no changes; backup integrity passed.

The earlier readback.json describes the first cleanup pass. The final verified totals are in text-cleanup-readback.json; timestamped audit files preserve before/after values.
