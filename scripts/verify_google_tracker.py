"""Verify Google tracker reads; optionally test writes on a separate test Sheet.

Set GOOGLE_SHEETS_TEST_SPREADSHEET_ID to a separate copy and pass --write-test
to exercise upserts without changing the live tracker.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import Config, GoogleTracker, job_key  # noqa: E402


def verify_live(tracker: GoogleTracker, job_number: str | None) -> None:
    application = tracker.application()
    scout = tracker.scout()
    print(f"Read Google Sheet: {len(application.rows)} Job Tracker rows, {len(scout.rows)} Job Scout rows")
    if job_number:
        found = tracker.find_application(job_number)
        if not found:
            raise RuntimeError(f"Job Number {job_number!r} was not found")
        print(f"Located Job Number {job_number!r} at row {found[0]}")
    seen = set()
    duplicates = []
    for row, data in application.rows:
        key = job_key(data)
        if not key:
            continue
        if key in seen:
            duplicates.append((row, key))
        seen.add(key)
    if duplicates:
        raise RuntimeError(f"Existing duplicate Job Numbers require review: {duplicates}")


def verify_write(config: Config) -> None:
    test_id = os.getenv("GOOGLE_SHEETS_TEST_SPREADSHEET_ID", "").strip()
    if not test_id or test_id == config.spreadsheet_id:
        raise RuntimeError("--write-test requires GOOGLE_SHEETS_TEST_SPREADSHEET_ID for a different spreadsheet")
    test_config = Config(test_id, config.credentials_file, config.application_tab, config.scout_tab)
    tracker = GoogleTracker(test_config)
    number = "gecko-verification-row"
    before = tracker.find_application(number)
    manual = ((before[1].get("Applied"), before[1].get("Contacted")) if before else None)
    tracker.upsert_application({"Job Number": number, "Company": "Gecko Verification",
                                "Match Score": "80/100", "Applied": "overwrite attempt",
                                "Contacted": "overwrite attempt"})
    tracker.upsert_application({"Job Number": number, "Match Score": "81/100",
                                "Applied": "overwrite attempt", "Contacted": "overwrite attempt"})
    found = tracker.find_application(number)
    if not found or found[1].get("Match Score") != "81/100":
        raise RuntimeError("Managed-cell update did not persist")
    after_manual = (found[1].get("Applied"), found[1].get("Contacted"))
    if (manual is not None and after_manual != manual) or (manual is None and
        any(value not in (None, "", False, "FALSE") for value in after_manual)):
        raise RuntimeError("User-controlled Applied or Contacted value changed")
    matches = [data for _, data in tracker.application().rows if job_key(data) == number]
    if len(matches) != 1:
        raise RuntimeError("Verification upsert created duplicate Job Numbers")
    print(f"Test Sheet upsert verified at row {found[0]}: managed update, manual fields, and uniqueness")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-number", help="Locate a known live Job Number")
    parser.add_argument("--write-test", action="store_true", help="Write only to a separate test spreadsheet")
    args = parser.parse_args()
    try:
        tracker = GoogleTracker()
        verify_live(tracker, args.job_number)
        if args.write_test:
            verify_write(tracker.config)
        return 0
    except (RuntimeError, ValueError, OSError) as error:
        print(f"Google tracker verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
