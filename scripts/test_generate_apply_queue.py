"""Apply queue tests use an isolated fake Google Sheet, never the live tracker."""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

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

        def generate(item, _db):
            processed.append(item.scout_id)
            if item.scout_id == 42:
                raise RuntimeError("simulated Word QA failure")
            return queue.Artifacts(Path("already-exists.docx"), Path("report.md"), Path("listing.md"))

        def record(artifacts, tracker):
            tracker.mark_scout_resume(45, artifacts.resume.as_uri() if artifacts.resume.is_absolute() else "file:///resume.docx")

        self.assertEqual(queue.run_queue(self.tracker, Path("unused.sqlite3"),
                                         generator=generate, recorder=record), 1)
        self.assertEqual(processed, [42, 45])
        rows = {int(data[0]): dict(zip(SCOUT, data)) for data in self.fake.data["Job Scout"][1:]}
        self.assertEqual(rows[42]["Resume Created"], "")
        self.assertEqual(rows[45]["Resume Created"], "X")
        self.assertEqual(rows[45]["Apply?"], "yes")

    def test_real_tracker_final_step_updates_google_fields_only(self):
        with TemporaryDirectory() as temp:
            temp = Path(temp)
            resume = temp / "Dave-Call+Existing+queue-42.docx"
            report = temp / "Dave-Call+Existing+queue-42.md"
            listing = temp / "Existing+queue-42.md"
            resume.write_bytes(b"test artifact")
            report.write_text("# Role\n\nMatch Score: 82/100\n", encoding="utf-8")
            listing.write_text("# Role\n\n- **Company:** Existing\n- **Job Number:** queue-42\n"
                               "- **Scout ID:** 42\n- **URL:** https://example.test/job\n", encoding="utf-8")
            queue.record_success(queue.Artifacts(resume, report, listing), self.tracker)
        application = self.tracker.find_application("queue-42")
        self.assertIsNotNone(application)
        self.assertEqual(application[1]["Match Score"], "82/100")
        self.assertEqual(application[1]["Resume Link"], resume.resolve().as_uri())
        scout = next(data for _, data in self.tracker.scout().rows if str(data.get("Scout ID")) == "42")
        self.assertEqual(scout["Resume Created"], "X")
        self.assertEqual(scout["Apply?"], "Yes")


if __name__ == "__main__":
    unittest.main()
