# Direct Playwright applications

The current October 23 batch runs locally with Python Playwright and installed Google Chrome. OpenClaw remains stopped. The scripts make no model calls; Codex assistance with unfamiliar forms and questions still uses the account allowance. No scheduled job was installed.

## Runtime and evidence

Use `.tools/playwright-python/Scripts/python.exe` with the pinned `scripts/playwright-requirements.txt`. Installed Chrome uses a separate `.tools/playwright-direct-profile` and a loopback-only debugging endpoint at `127.0.0.1:9333`. The user's main browser profile is separate. Closing a short-lived script preserves browser tabs.

`scripts/playwright_direct.py --request <request.json>` processes explicit actions on the exact job tab. The current packet/evidence directory is `reports/playwright-pilot/direct-20261023`. Its batch paths are specific to this authorized 40-job run; do not reuse it for unrelated applications. Private application evidence is ignored by Git.

The older `playwright_application.py` is a draft-only single-job pilot. `playwright_batch.py` supplies shared helpers and the older command-folder worker. Keep earlier submission-attempt ledgers: a new folder does not authorize a repeat submission.

## Submission policy

Dave authorizes automatic submission of complete applications from this batch. Read the answer bank before each application; preserve confirmed Applied jobs and unknown-answer drafts. Use only the matching existing tailored resume. Preview or downloaded-content checks are no longer required. Verify the source file, matching selected filename and size, and site attachment acknowledgement. Some sites send selected files with the final form rather than uploading separately; require the matching selection and displayed filename, followed by employer confirmation.

The same-stem PDF is permitted for 829 Studios after native Word/PDF validation. Humana's shortened upload copy must remain byte-identical to its original tracked DOCX. Neither operation regenerates or replaces the original tailored resume.

Never solve or bypass CAPTCHA, invent qualifications, create accounts automatically, or repeat a submission with an unresolved result. Leave CAPTCHA applications for Dave after other complete applications.

## Confirmation and tracking

Fresh Google Sheet preflight checks the unique ID, employer/title, eligibility, exclusions, existing Applied state, and exact Resume Link. A submission-attempt ledger is written before the final click. A click or timeout never marks Applied.

After a positive employer receipt, `scripts/playwright_tracker.py --receipt <receipt.json>` writes Applied=X and the actual America/Denver Applied Date together in the primary Google Sheet, verifies both by readback, and preserves Previous Applied Date, formulas, unrelated cells, and frozen row 1. A screenshot failure must not prevent an already-confirmed receipt from reaching the tracker.

If an employer uses unexpected confirmation wording, inspect the saved page and reconcile its positive receipt through the tracker helper without clicking Submit again. Email verification remains pending until completed.

## Checks

`test_playwright_submission.py` exercises required-answer and attachment checks, positive receipt handling, tracker verification, and repeat-submission prevention against a local fake form. It never sends an employer application.
