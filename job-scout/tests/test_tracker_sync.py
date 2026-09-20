from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill


SCOUT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCOUT_ROOT))
SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_ROOT))

from models import RawListing
from normalize import normalize
from tracker_sync import HEADERS, LEGACY_HEADERS, SHEET_NAME, sync_job_scout
from manage_job_tracker import HEADERS as TRACKER_HEADERS
from manage_job_tracker import JobRecord, load_tracker, mark_scout_resume_created, upsert_record


class TrackerSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "tracker.xlsx"
        workbook = Workbook()
        tracker = workbook.active
        tracker.title = "Job Tracker"
        tracker.append(["Existing", "Formula"])
        tracker.append(["Keep me", "=1+1"])
        tracker["A1"].font = Font(bold=True, color="FFFFFF")
        tracker["A1"].fill = PatternFill("solid", fgColor="1F4E78")
        notes = workbook.create_sheet("Notes")
        notes["A1"] = "Do not change"
        workbook.save(self.path)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def cell(ws, header, row=2):
        return ws.cell(row, HEADERS.index(header) + 1)

    @staticmethod
    def job(job_id, score=82, confidence=80, *, posted="2026-09-01", status="new"):
        raw = RawListing(
            source="adzuna", source_job_id=str(job_id),
            url=f"https://www.adzuna.com/details/{job_id}?utm_source=test",
            title=f"Paid Search Manager {job_id}", company=f"Company {job_id}",
            location="Lehi, Utah", description="Paid search manager role.",
            employment_type="full_time", salary="$100,000", date_posted=posted,
        )
        job = normalize(raw, discovered="2026-09-10")
        job.id = job_id
        job.last_seen = "2026-09-19"
        job.match_score = score
        job.evidence_confidence = confidence
        job.match_strengths = ["Strong one", "Strong two", "Strong three", "Strong four"]
        job.match_weaknesses = ["Weak one", "Weak two", "Weak three", "Weak four"]
        job.status = status
        return job

    def test_creates_sheet_and_preserves_existing_tabs_data_formulas_and_style(self):
        before = load_workbook(self.path, data_only=False)
        original_style = before["Job Tracker"]["A1"].style_id
        summary = sync_job_scout([self.job(1)], self.path)
        after = load_workbook(self.path, data_only=False)
        self.assertEqual(after.sheetnames, ["Job Tracker", "Notes", SHEET_NAME])
        self.assertEqual(after["Job Tracker"]["A2"].value, "Keep me")
        self.assertEqual(after["Job Tracker"]["B2"].value, "=1+1")
        self.assertEqual(after["Job Tracker"]["A1"].style_id, original_style)
        self.assertEqual(after["Notes"]["A1"].value, "Do not change")
        self.assertTrue(summary.tracker_preserved)

    def test_new_jobs_append_with_required_headers(self):
        sync_job_scout([self.job(1), self.job(2)], self.path)
        ws = load_workbook(self.path)[SHEET_NAME]
        self.assertEqual([cell.value for cell in ws[1]], HEADERS)
        self.assertEqual(ws.max_row, 3)
        self.assertEqual({ws.cell(row, 1).value for row in (2, 3)}, {1, 2})

    def test_existing_and_enriched_jobs_update_without_duplicate(self):
        job = self.job(1, 81, 35)
        job.provisional = True
        sync_job_scout([job], self.path)
        job.match_score = 93
        job.evidence_confidence = 96
        job.provisional = False
        job.enriched_source_url = "https://careers.example.test/jobs/1"
        job.match_strengths = ["Updated strength"]
        sync_job_scout([job], self.path)
        ws = load_workbook(self.path)[SHEET_NAME]
        self.assertEqual(ws.max_row, 2)
        self.assertEqual(ws["E2"].value, 93)
        self.assertEqual(ws["G2"].value, "Confirmed Strong Match")
        self.assertEqual(ws["B2"].value, "adzuna")
        self.assertEqual(self.cell(ws, "Enrichment URL").value, "https://careers.example.test/jobs/1")
        self.assertNotIn("Top Strengths", [cell.value for cell in ws[1]])
        self.assertNotIn("Top Weaknesses", [cell.value for cell in ws[1]])

    def test_manual_applied_and_contacted_marks_are_preserved(self):
        sync_job_scout([self.job(1)], self.path)
        workbook = load_workbook(self.path)
        ws = workbook[SHEET_NAME]
        self.cell(ws, "Applied").value = "X"
        self.cell(ws, "Contacted").value = "manual note"
        workbook.save(self.path)
        changed = self.job(1, 95, 99)
        sync_job_scout([changed], self.path)
        ws = load_workbook(self.path)[SHEET_NAME]
        self.assertEqual(self.cell(ws, "Applied").value, "X")
        self.assertEqual(self.cell(ws, "Contacted").value, "manual note")

    def test_legacy_source_column_moves_to_b_without_losing_manual_fields(self):
        workbook = load_workbook(self.path)
        legacy = workbook.create_sheet(SHEET_NAME)
        legacy.append(LEGACY_HEADERS)
        record = {header: None for header in LEGACY_HEADERS}
        record.update({
            "Scout ID": 1, "Company": "Company 1", "Job Title": "Paid Search Manager 1",
            "Match Score": 82, "Evidence Confidence": 0.8, "Match Status": "Confirmed Strong Match",
            "Source": "adzuna", "Job URL": "https://www.adzuna.com/details/1",
            "Gecko Status": "Applied", "Applied": "X", "Contacted": "manual",
        })
        legacy.append([record[header] for header in LEGACY_HEADERS])
        workbook.save(self.path)
        sync_job_scout([self.job(1)], self.path)
        ws = load_workbook(self.path)[SHEET_NAME]
        self.assertEqual([cell.value for cell in ws[1]], HEADERS)
        self.assertEqual(ws["B2"].value, "adzuna")
        self.assertEqual(self.cell(ws, "Applied").value, "X")
        self.assertEqual(self.cell(ws, "Contacted").value, "manual")

    def test_sorting_and_hyperlinks(self):
        first = self.job(1, 90, 80, posted="2026-09-01")
        second = self.job(2, 91, 70, posted="2026-08-01")
        third = self.job(3, 90, 90, posted="2026-07-01")
        third.enriched_source_url = "https://careers.example.test/jobs/3"
        sync_job_scout([first, second, third], self.path)
        ws = load_workbook(self.path)[SHEET_NAME]
        self.assertEqual([ws.cell(row, 1).value for row in (2, 3, 4)], [2, 3, 1])
        for row in (2, 3, 4):
            self.assertIsNotNone(self.cell(ws, "Job URL", row).hyperlink)
        self.assertEqual(self.cell(ws, "Enrichment URL", 3).hyperlink.target, "https://careers.example.test/jobs/3")
        self.assertEqual(ws.freeze_panes, "A2")
        self.assertEqual(ws.auto_filter.ref, "A1:W4")

    def test_old_scout_rows_are_not_deleted(self):
        sync_job_scout([self.job(1)], self.path)
        sync_job_scout([self.job(2)], self.path)
        ws = load_workbook(self.path)[SHEET_NAME]
        self.assertEqual(ws.max_row, 3)
        self.assertEqual({ws.cell(row, 1).value for row in (2, 3)}, {1, 2})

    def test_selected_status_is_written(self):
        job = self.job(1, status="selected")
        sync_job_scout([job], self.path)
        ws = load_workbook(self.path)[SHEET_NAME]
        self.assertEqual(self.cell(ws, "Gecko Status").value, "Selected")

    def test_resume_completion_updates_scout_row_without_manual_columns(self):
        sync_job_scout([self.job(1, status="selected")], self.path)
        workbook = load_workbook(self.path)
        scout = workbook[SHEET_NAME]
        self.cell(scout, "Applied").value = "X"
        self.cell(scout, "Contacted").value = "manual"
        record = JobRecord(
            company="Company 1", job_title="Paid Search Manager 1", pay="",
            job_number="1", match_score="90/100", job_link="",
            resume_path=Path("resume.docx"), date_created=None, scout_id=1,
        )
        self.assertTrue(mark_scout_resume_created(workbook, record))
        self.assertEqual(self.cell(scout, "Gecko Status").value, "Resume Created")
        self.assertEqual(self.cell(scout, "Resume Created").value, "X")
        self.assertEqual(self.cell(scout, "Applied").value, "X")
        self.assertTrue(str(self.cell(scout, "Resume Link").value).startswith("file:///"))
        self.assertEqual(self.cell(scout, "Contacted").value, "manual")

    def test_existing_tracker_loader_accepts_job_scout_tab(self):
        workbook = Workbook()
        tracker = workbook.active
        tracker.title = "Job Tracker"
        tracker.append(TRACKER_HEADERS)
        workbook.create_sheet(SHEET_NAME)
        workbook.save(self.path)
        loaded = load_tracker(self.path)
        self.assertEqual(loaded.sheetnames, ["Job Tracker", SHEET_NAME])

    def test_application_upsert_updates_owned_fields_and_preserves_manual_fields(self):
        workbook = Workbook()
        tracker = workbook.active
        tracker.title = "Job Tracker"
        tracker.append(TRACKER_HEADERS)
        tracker.append([1, "Old Company", "Old Title", None, "job-1", "80/100", None,
                        "resumes/old.docx", None, "X", "manual", None, None, "resume-created"])
        record = JobRecord(
            company="New Company", job_title="New Title", pay="$100,000",
            job_number="job-1", match_score="95/100", job_link="https://example.test/job-1",
            resume_path=Path("resumes/new.docx"), date_created=None, status="resume-created",
        )
        added, changed = upsert_record(tracker, self.path, record)
        self.assertFalse(added)
        self.assertTrue(changed)
        self.assertEqual(tracker.max_row, 2)
        self.assertEqual(tracker["B2"].value, "New Company")
        self.assertEqual(tracker["F2"].value, "95/100")
        self.assertEqual(tracker["J2"].value, "X")
        self.assertEqual(tracker["K2"].value, "manual")


if __name__ == "__main__":
    unittest.main()
