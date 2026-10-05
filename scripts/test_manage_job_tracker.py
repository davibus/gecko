"""Metadata extraction remains source-grounded without any Excel dependency."""

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from manage_job_tracker import (
    JobRecord, _assert_no_existing_scout_resume,
    filename_job_number, markdown_field, record_from_files,
)


class TrackerMetadataTests(unittest.TestCase):
    def test_manual_tracker_upsert_refuses_existing_x_without_scout_id(self):
        record = JobRecord("Example", "Role", "", "abc123",
                           "https://www.indeed.com/viewjob?jk=abc123",
                           Path("resume.docx"), None, source="indeed")
        tab = SimpleNamespace(headers={"Resume Created": 7}, rows=[
            (2, {"Scout ID": 42, "Job URL": "https://www.indeed.com/viewjob?jk=abc123",
                 "Resume Created": " X "}),
        ])
        tracker = SimpleNamespace(scout=lambda **_kwargs: tab)
        with self.assertRaisesRegex(RuntimeError, "SKIP RESUME"):
            _assert_no_existing_scout_resume(record, tracker)
        tab.rows[0][1]["Resume Created"] = ""
        _assert_no_existing_scout_resume(record, tracker)

    def test_job_number_stays_last_in_title_bearing_resume_name(self):
        self.assertEqual(filename_job_number(Path("Dave-Call+Example+Growth-Marketing-Manager+abc123.docx")),
                         "abc123")

    def test_blank_salary_does_not_capture_next_line(self):
        for newline in ("\n", "\r\n"):
            text = newline.join(["- **Salary:** ", "- **Source:** web-careers"])
            self.assertEqual(markdown_field(text, ("Salary", "Pay")), "")
            self.assertEqual(markdown_field(text, ("Source",)), "web-careers")

    def test_completed_artifacts_supply_google_record(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            resume = root / "Dave-Call+Example+abc123.docx"
            listing = root / "Example+abc123.md"
            resume.write_bytes(b"completed")
            listing.write_text("# Role\n\n- **Company:** Example\n- **Job Number:** abc123\n"
                               "- **Scout ID:** 42\n- **Salary:** \n", encoding="utf-8")
            record = record_from_files(resume, listing)
            self.assertEqual((record.job_number, record.scout_id), ("abc123", 42))
            self.assertEqual(record.pay, "")


if __name__ == "__main__":
    unittest.main()
