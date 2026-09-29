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
            [46, "test", "Retry", "Role", "New", "YES", "failed", "", ""],
        ])
        self.tracker = GoogleTracker(Config("test", Path("unused.json"), "Job Tracker", "Job Scout"), self.fake)

    def test_yes_queue_skips_x_and_continues_after_failure(self):
        snapshot = queue.read_queue(self.tracker)
        self.assertEqual([item.scout_id for item in snapshot.pending], [42, 45, 46])
        self.assertEqual([item.scout_id for item in snapshot.already_created], [43])
        processed = []

        with TemporaryDirectory() as temp:
            def generate(item, _db):
                processed.append(item.scout_id)
                if item.scout_id == 42:
                    raise RuntimeError("simulated Word QA failure")
                return queue.Artifacts(Path(temp) / "resume.docx", Path("listing.md"))

            def record(item, _artifacts, tracker):
                queue.manage_job_tracker.mark_batch_resume(item.scout_id, item.row, tracker)

            result = queue.run_queue(self.tracker, Path("unused.sqlite3"),
                                     generator=generate, recorder=record)
            self.assertEqual(result.exit_code, 1)
        self.assertEqual(processed, [42, 45, 46])
        rows = {int(data[0]): dict(zip(SCOUT, data)) for data in self.fake.data["Job Scout"][1:]}
        self.assertEqual(rows[42]["Resume Created"], "")
        self.assertEqual(rows[45]["Resume Created"], "X")
        self.assertEqual(rows[45]["Apply?"], "yes")
        self.assertEqual(rows[46]["Resume Created"], "X")

    def test_final_step_updates_managed_cells_and_preserves_apply(self):
        self.fake.data["Job Scout"][1][7] = "TRUE"
        self.fake.data["Job Scout"][1][8] = (
            "Recruiter contacted\nResume not created: prior temporary failure"
        )
        with TemporaryDirectory() as temp:
            temp = Path(temp)
            resume = temp / "Dave-Call+Existing+queue-42.docx"
            listing = temp / "Existing+queue-42.md"
            resume.write_bytes(b"test artifact")
            listing.write_text("# Role\n\n- **Company:** Existing\n- **Job Number:** queue-42\n"
                               "- **Scout ID:** 42\n- **URL:** https://example.test/job\n", encoding="utf-8")
            item = queue.QueueRow(2, 42, "Existing", "Role")
            queue.record_success(item, queue.Artifacts(resume, listing), self.tracker)
        self.assertEqual([(tab, col) for tab, _, col in self.fake.writes if tab == "Job Scout"],
                         [("Job Scout", "G"), ("Job Scout", "I")])
        scout = next(data for _, data in self.tracker.scout().rows if str(data.get("Scout ID")) == "42")
        self.assertEqual(scout["Resume Created"], "X")
        self.assertEqual(scout["Apply?"], "Yes")
        self.assertEqual(scout["Gecko Status"], "New")
        self.assertEqual(scout["Resume Link"], "")
        self.assertEqual(scout["Applied"], "TRUE")
        self.assertEqual(scout["Notes"], "Recruiter contacted")
        applications = [data for _, data in self.tracker.application().rows
                        if str(data.get("Job Number")) == "queue-42"]
        self.assertEqual(applications, [])

    def test_missing_artifact_or_changed_apply_never_marks_g(self):
        item = queue.QueueRow(2, 42, "Existing", "Role")
        with self.assertRaisesRegex(ValueError, "missing"):
            queue.record_success(item, queue.Artifacts(Path("missing.docx"), Path("listing.md")),
                                 self.tracker)
        self.fake.data["Job Scout"][1][5] = "No"
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"docx")
            with self.assertRaisesRegex(RuntimeError, "Apply"):
                queue.record_success(item, queue.Artifacts(resume, Path("listing.md")),
                                     self.tracker)
        self.assertEqual(self.fake.writes, [])

    def test_tracker_write_failure_leaves_column_g_unchanged(self):
        item = queue.QueueRow(2, 42, "Existing", "Role")
        with TemporaryDirectory() as temp:
            temp = Path(temp)
            resume = temp / "Dave-Call+Existing+Role+queue-42.docx"
            listing = temp / "Existing+queue-42.md"
            resume.write_bytes(b"docx")
            listing.write_text(
                "# Role\n\n- **Company:** Existing\n- **Job Number:** queue-42\n"
                "- **Scout ID:** 42\n- **URL:** https://example.test/job\n",
                encoding="utf-8",
            )
            with patch.object(self.tracker, "_write",
                              side_effect=RuntimeError("simulated Sheets write failure")):
                with self.assertRaisesRegex(RuntimeError, "simulated Sheets"):
                    queue.record_success(item, queue.Artifacts(resume, listing), self.tracker)
        scout = next(data for _, data in self.tracker.scout().rows
                     if str(data.get("Scout ID")) == "42")
        self.assertEqual(scout["Resume Created"], "")

    def test_failure_reason_is_specific_retryable_and_preserves_other_notes(self):
        self.fake.data["Job Scout"][1][8] = "Keep this note"
        queue.manage_job_tracker.record_queue_failure(
            42, 2, "Word-native validation returned three pages", self.tracker
        )
        scout = next(data for _, data in self.tracker.scout().rows
                     if str(data.get("Scout ID")) == "42")
        self.assertEqual(
            scout["Notes"],
            "Keep this note\nResume not created: Word-native validation returned three pages",
        )
        self.assertEqual(scout["Resume Created"], "")

    def test_sparse_row_context_has_no_description_length_floor(self):
        with TemporaryDirectory() as temp, patch.object(queue, "ROOT", Path(temp)):
            item = queue.QueueRow(
                2, 42, "Existing", "Paid Search Manager", "https://example.test/job",
                "test", {"Location": "Remote"},
            )
            listing = queue._archive_row_context(item)
            plan = queue.gecko_v2.create_plan(listing)
        self.assertEqual(plan["job"]["company"], "Existing")
        self.assertEqual(plan["job"]["title"], "Paid Search Manager")

    def test_description_failure_leaves_row_unprocessed_and_logs_attempts(self):
        item = queue.read_queue(self.tracker).pending[0]
        attempt = queue.RetrievalAttempt(
            "original aggregator URL", item.job_url, "failed", "HTTP Error 403: Forbidden"
        )
        result = queue.DescriptionRetrievalResult(
            "failed", attempts=[attempt], authoritative_url="https://careers.example.test/job",
            error="No source produced a complete description.",
        )
        recorded = []
        messages = []
        with TemporaryDirectory() as temp, patch.object(queue, "ROOT", Path(temp)):
            def generate(candidate, _db):
                if candidate.scout_id == item.scout_id:
                    raise queue.DescriptionUnavailableError(result, candidate.job_url)
                raise RuntimeError("second simulated failure")

            run = queue.run_queue(
                self.tracker, Path("unused.sqlite3"), generator=generate,
                recorder=lambda *args: recorded.append(args),
                logger=messages.append,
            )
        self.assertEqual(run.exit_code, 1)
        self.assertEqual(recorded, [])
        self.assertTrue(any("HTTP Error 403" in message for message in messages))
        self.assertFalse((Path(temp) / "output/apply-queue-results.md").exists())
        scout = next(data for _, data in self.tracker.scout().rows if str(data.get("Scout ID")) == "42")
        self.assertEqual(scout["Resume Created"], "")

    def test_daily_scope_processes_only_new_ids_and_respects_apply_and_existing_marker(self):
        processed = []
        with TemporaryDirectory() as temp:
            temp = Path(temp)

            def generate(item, _db):
                processed.append(item.scout_id)
                return queue.Artifacts(temp / "resume.docx", temp / "listing.md")

            run = queue.run_queue(
                self.tracker, Path("unused.sqlite3"), eligible_scout_ids={43, 44, 45},
                generator=generate,
                recorder=lambda item, *_: queue.manage_job_tracker.mark_batch_resume(
                    item.scout_id, item.row, self.tracker
                ),
            )
        self.assertEqual(processed, [45])
        self.assertEqual([item.scout_id for item in run.snapshot.already_created], [43])
        self.assertEqual([item.scout_id for item in run.snapshot.not_approved], [44])

    def test_jooble_row_is_eligible_when_user_marks_yes(self):
        row = [47, "Jooble", "Blocked", "Paid Search Manager", "New", "Yes", "", "", ""]
        while len(row) < len(SCOUT):
            row.append("")
        row[SCOUT.index("Job URL")] = "https://www.jooble.org/jobs/123"
        self.fake.data["Job Scout"].append(row)
        snapshot = queue.read_queue(self.tracker, {47})
        self.assertEqual([item.scout_id for item in snapshot.pending], [47])
        self.assertEqual(snapshot.jooble_excluded, [])

    def test_rerun_skips_rows_marked_x(self):
        with TemporaryDirectory() as temp:
            resume = Path(temp) / "resume.docx"
            resume.write_bytes(b"docx")
            generated = []

            def generator(item, _db):
                generated.append(item.scout_id)
                return queue.Artifacts(resume, Path("listing.md"))

            first = queue.run_queue(
                self.tracker, Path("unused.sqlite3"), generator=generator,
                recorder=lambda item, *_: queue.manage_job_tracker.mark_batch_resume(
                    item.scout_id, item.row, self.tracker
                ), print_summary=False,
            )
            second = queue.run_queue(
                self.tracker, Path("unused.sqlite3"), generator=generator,
                recorder=lambda *_: self.fail("completed row was processed again"),
                print_summary=False,
            )
        self.assertEqual(len(first.successes), 3)
        self.assertEqual(second.snapshot.pending, [])


if __name__ == "__main__":
    unittest.main()
