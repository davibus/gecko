"""Focused tests for the targeted live expiration command."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
sys.path.insert(0, str(ROOT / "job-scout" / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from google_tracker import Config, GoogleTracker, INDEED_APPLICATION_HEADER
from test_google_tracker import FakeSheets, SCOUT
from expire_indeed_jobs import update_expired_rows


class ExpireIndeedTests(unittest.TestCase):
    def test_full_message_existing_expired_formula_and_custom_columns(self):
        fake = FakeSheets()
        headers, first = fake.data["Job Scout"]
        headers.append("Custom")
        first.append("=1+1")
        first[headers.index(INDEED_APPLICATION_HEADER)] = " This JOB has expired on Indeed "
        second = list(first)
        second[headers.index("ID")] = 43
        second[headers.index(INDEED_APPLICATION_HEADER)] = " expired "
        second[headers.index("Apply?")] = "Yes"
        third = list(second)
        third[headers.index("ID")] = 44
        third[headers.index("Apply?")] = '=IF(TRUE,"Yes","No")'
        fake.data["Job Scout"].extend([second, third])
        tracker = GoogleTracker(Config("test", Path("unused"), "Job Tracker", "Job Scout"), fake)
        result = update_expired_rows(tracker)
        self.assertEqual(result["rows_updated"], 3)
        self.assertEqual(result["cells_updated"], 5)
        self.assertEqual(len(result["skipped_formula_cells"]), 1)
        self.assertEqual(first[headers.index(INDEED_APPLICATION_HEADER)], "Expired")
        self.assertEqual(first[headers.index("Apply?")], "No")
        self.assertEqual(second[headers.index("Apply?")], "No")
        self.assertEqual(third[headers.index("Apply?")], '=IF(TRUE,"Yes","No")')
        self.assertEqual(third[headers.index("Custom")], "=1+1")
        self.assertEqual(update_expired_rows(tracker)["cells_updated"], 0)


if __name__ == "__main__":
    unittest.main()
