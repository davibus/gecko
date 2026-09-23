"""Metadata extraction remains source-grounded without any Excel dependency."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manage_job_tracker import markdown_field, record_from_files


class TrackerMetadataTests(unittest.TestCase):
    def test_blank_salary_does_not_capture_next_line(self):
        for newline in ("\n", "\r\n"):
            text = newline.join(["- **Salary:** ", "- **Source:** web-careers"])
            self.assertEqual(markdown_field(text, ("Salary", "Pay")), "")
            self.assertEqual(markdown_field(text, ("Source",)), "web-careers")

    def test_completed_artifacts_supply_google_record(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            resume = root / "Dave-Call+Example+abc123.docx"
            report = root / "Dave-Call+Example+abc123.md"
            listing = root / "Example+abc123.md"
            resume.write_bytes(b"completed")
            report.write_text("# Role\n\nMatch Score: 86/100\n", encoding="utf-8")
            listing.write_text("# Role\n\n- **Company:** Example\n- **Job Number:** abc123\n"
                               "- **Scout ID:** 42\n- **Salary:** \n", encoding="utf-8")
            record = record_from_files(resume, report, listing)
            self.assertEqual((record.job_number, record.match_score, record.scout_id),
                             ("abc123", "86/100", 42))
            self.assertEqual(record.pay, "")


if __name__ == "__main__":
    unittest.main()
