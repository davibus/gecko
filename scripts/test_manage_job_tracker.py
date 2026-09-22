"""Regression checks for blank metadata and safe tracker refreshes."""

from datetime import date
from pathlib import Path
import unittest

from manage_job_tracker import JobRecord, append_record, create_workbook, markdown_field, upsert_record


class TrackerMetadataTests(unittest.TestCase):
    def test_blank_salary_does_not_capture_next_line(self):
        for newline in ("\n", "\r\n"):
            with self.subTest(newline=repr(newline)):
                text = newline.join(["- **Salary:** ", "- **Source:** web-careers"])
                self.assertEqual(markdown_field(text, ("Salary", "Pay")), "")
                self.assertEqual(markdown_field(text, ("Source",)), "web-careers")

    def test_populated_metadata_and_aliases(self):
        self.assertEqual(markdown_field("- **Pay:** $80,000–$100,000\n", ("Salary", "Pay")), "$80,000–$100,000")
        self.assertEqual(markdown_field("- **Job Number:** `abc123`\n", ("Job Number",)), "abc123")

    def test_refresh_clears_bad_pay_and_preserves_identity_and_manual_fields(self):
        wb = create_workbook()
        ws = wb["Job Tracker"]
        tracker = Path("output/job-tracker.xlsx")
        record = JobRecord("Example", "Paid Media Manager", "", "abc123", "86/100", "",
                           Path("output/resumes/example.docx"), date(2026, 9, 22))
        append_record(ws, tracker, record)
        number = ws.cell(2, 1).value
        ws.cell(2, 4).value = "- **Source:** web-careers"
        ws.cell(2, 10).value = "Applied manually"
        ws.cell(2, 11).value = "Contacted manually"
        self.assertEqual(upsert_record(ws, tracker, record), (False, True))
        self.assertIsNone(ws.cell(2, 4).value)
        self.assertEqual(ws.cell(2, 1).value, number)
        self.assertEqual(ws.cell(2, 10).value, "Applied manually")
        self.assertEqual(ws.cell(2, 11).value, "Contacted manually")
        self.assertEqual(ws.max_row, 2)
        self.assertEqual(upsert_record(ws, tracker, record), (False, False))


if __name__ == "__main__":
    unittest.main()
