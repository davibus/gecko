"""Apply queue tests use an isolated fake Google Sheet, never the live tracker."""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "job-scout"))
sys.path.insert(0, str(ROOT / "job-scout/tests"))
import generate_apply_queue as queue
from google_tracker import Config, GoogleTracker
from test_google_tracker import FakeSheets, SCOUT


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSheets()
        self.fake.data["Job Scout"].extend([
            [43, "test", "Already", "Role", "Resume Created", " YES ", " x ", "", ""],
            [44, "test", "No Apply", "Role", "New", "No", "", "", ""],
            [45, "test", "Another", "Role", "New", "yes", "", "", ""],
        ])
        self.tracker = GoogleTracker(Config("test", Path("unused.json"), "Job Tracker", "Job Scout"), self.fake)

    def test_yes_queue_skips_x_and_continues_after_failure(self):
        pending, skipped = queue.read_queue(self.tracker)
        self.assertEqual([item.scout_id for item in pending], [42, 45])
        self.assertEqual([item.scout_id for item in skipped], [43])
        processed = []

        with TemporaryDirectory() as temp, patch.object(queue, "_write_report"):
            report = Path(temp) / "report.md"
            report.write_text("Match Score: 75/100\n", encoding="utf-8")

            def generate(item, _db):
                processed.append(item.scout_id)
                if item.scout_id == 42:
                    raise RuntimeError("simulated Word QA failure")
                return queue.Artifacts(Path(temp) / "resume.docx", report, Path("listing.md"))

            def record(item, _artifacts, tracker):
                queue.manage_job_tracker.mark_batch_resume(item.scout_id, item.row, tracker)

            self.assertEqual(queue.run_queue(self.tracker, Path("unused.sqlite3"),
                                             generator=generate, recorder=record), 1)
        self.assertEqual(processed, [42, 45])
        rows = {int(data[0]): dict(zip(SCOUT, data)) for data in self.fake.data["Job Scout"][1:]}
        self.assertEqual(rows[42]["Resume Created"], "")
        self.assertEqual(rows[45]["Resume Created"], "X")
        self.assertEqual(rows[45]["Apply?"], "yes")

    def test_final_step_updates_managed_cells_and_preserves_apply(self):
        with TemporaryDirectory() as temp:
            temp = Path(temp)
            resume = temp / "Dave-Call+Existing+queue-42.docx"
            report = temp / "Dave-Call+Existing+queue-42.md"
            listing = temp / "Existing+queue-42.md"
            resume.write_bytes(b"test artifact")
            report.write_text("# Role\n\nMatch Score: 82/100\n", encoding="utf-8")
            listing.write_text("# Role\n\n- **Company:** Existing\n- **Job Number:** queue-42\n"
                               "- **Scout ID:** 42\n- **URL:** https://example.test/job\n", encoding="utf-8")
            item = queue.QueueRow(2, 42, "Existing", "Role")
            queue.record_success(item, queue.Artifacts(resume, report, listing), self.tracker)
        self.assertEqual([(tab, col) for tab, _, col in self.fake.writes if tab == "Job Scout"],
                         [("Job Scout", "G"), ("Job Scout", "E")])
        scout = next(data for _, data in self.tracker.scout().rows if str(data.get("Scout ID")) == "42")
        self.assertEqual(scout["Resume Created"], "X")
        self.assertEqual(scout["Apply?"], "Yes")
        self.assertEqual(scout["Gecko Status"], "Resume Created")

    def test_missing_artifact_or_changed_apply_never_marks_g(self):
        item = queue.QueueRow(2, 42, "Existing", "Role")
        with self.assertRaisesRegex(ValueError, "missing"):
            queue.record_success(item, queue.Artifacts(Path("missing.docx"), Path("missing.md"),
                                                       Path("listing.md")), self.tracker)
        self.fake.data["Job Scout"][1][5] = "No"
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            report = Path(temp) / "report.md"
            resume.write_bytes(b"docx")
            report.write_text("report", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "Apply"):
                queue.record_success(item, queue.Artifacts(resume, report, Path("listing.md")),
                                     self.tracker)
        self.assertEqual(self.fake.writes, [])


if __name__ == "__main__":
    unittest.main()
