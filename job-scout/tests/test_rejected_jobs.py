"""Permanent rejected-job history and archive-before-delete tests."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from google_tracker import Config, GoogleTracker
from manual_indeed import process_manual_indeed_rows
from models import RawListing
from normalize import normalize
from rejected_jobs import RejectedJobsIndex, rejection_record
from rejection_workflow import process_rejected_rows
from service import discover_listings
from storage import JobStore
from test_google_tracker import FakeSheets, SCOUT


def listing(source_id: str, url: str, *, source: str = "Test Board"):
    return RawListing(
        source=source,
        source_job_id=source_id,
        url=url,
        company="Same Company",
        title="Paid Search Manager",
        location="Remote",
        description="Lead paid search strategy and reporting for a growing team.",
    )


class NoCallProvider:
    def retrieve(self, _url):
        raise AssertionError("A permanently rejected Indeed job must not be retrieved")


class RejectedJobsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp.name) / "jobs.sqlite3")
        self.fake = FakeSheets()
        self.tracker = GoogleTracker(
            Config("test-id", Path("unused.json"), "Job Tracker", "Job Scout"),
            self.fake,
        )

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    @staticmethod
    def rejected(*, source_id="blocked", url="https://jobs.test/opening?job=blocked"):
        return RejectedJobsIndex((rejection_record(
            source="Test Board", job_id=source_id, url=url,
            company="Same Company", title="Paid Search Manager",
            date_rejected="2026-10-04", reason="Reject",
        ),))

    def test_rejected_job_id_is_never_saved_by_job_scout(self):
        summary = discover_listings(
            [listing("blocked", "https://jobs.test/another-url")], self.store,
            rejected_jobs=self.rejected(),
        )
        self.assertEqual(summary.rejected_history_excluded, 1)
        self.assertEqual(self.store.all(), [])

    def test_rejected_normalized_url_is_never_saved_without_id(self):
        history = self.rejected(
            source_id="", url="https://jobs.test/opening/55?utm_source=email&ref=share",
        )
        summary = discover_listings(
            [listing("", "https://jobs.test/opening/55?utm_campaign=again")], self.store,
            rejected_jobs=history,
        )
        self.assertEqual(summary.rejected_history_excluded, 1)
        self.assertEqual(self.store.all(), [])

    def test_url_only_rejection_matches_when_scout_later_has_a_stable_id(self):
        history = self.rejected(source_id="", url="https://jobs.test/opening/55?utm_source=old")
        summary = discover_listings(
            [listing("newly-known-id", "https://jobs.test/opening/55?utm_campaign=again")],
            self.store,
            rejected_jobs=history,
        )
        self.assertEqual(summary.rejected_history_excluded, 1)
        self.assertEqual(self.store.all(), [])

    def test_different_stable_id_is_allowed_even_if_url_was_previously_rejected(self):
        history = self.rejected(source_id="old-id", url="https://jobs.test/opening/shared")
        candidate = listing("new-id", "https://jobs.test/opening/shared")
        index = history
        self.assertIsNone(index.matches_job(normalize(candidate)))

    def test_same_company_title_with_different_job_id_is_allowed(self):
        summary = discover_listings(
            [listing("new-id", "https://jobs.test/opening/new-id")], self.store,
            rejected_jobs=self.rejected(),
        )
        self.assertEqual(summary.added, 1)
        self.assertEqual(summary.rejected_history_excluded, 0)

    def test_same_company_title_with_different_legitimate_url_is_allowed(self):
        history = self.rejected(source_id="", url="https://jobs.test/opening/old")
        summary = discover_listings(
            [listing("", "https://jobs.test/opening/new")], self.store,
            rejected_jobs=history,
        )
        self.assertEqual(summary.added, 1)

    def test_reject_marker_is_archived_and_verified_before_visible_row_is_removed(self):
        job = normalize(listing("provider-42", "https://jobs.test/opening/42?utm_source=x"))
        self.store.save(job, job_id=42)
        visible = self.fake.data["Job Scout"][1]
        visible[SCOUT.index("Source")] = "Test Board"
        visible[SCOUT.index("Company")] = "Same Company"
        visible[SCOUT.index("Job Title")] = "Paid Search Manager"
        visible[SCOUT.index("Job URL")] = "https://jobs.test/opening/42?utm_source=x"
        visible[SCOUT.index("Status")] = "Reject"
        events = []
        append = self.tracker.append_rejected_jobs
        delete = self.tracker.delete_scout_rows
        with (
            patch.object(self.tracker, "append_rejected_jobs",
                         side_effect=lambda records: (events.append("archive"), append(records))[1]),
            patch.object(self.tracker, "delete_scout_rows",
                         side_effect=lambda rows, **kwargs: (
                             events.append("delete"), delete(rows, **kwargs)
                         )[1]),
        ):
            summary = process_rejected_rows(self.tracker, self.store, today="2026-10-04")
        self.assertEqual(events, ["archive", "delete"])
        self.assertEqual((summary.archived, summary.removed), (1, 1))
        self.assertEqual(len(self.fake.data["Job Scout"]), 1)
        rejected = self.tracker.rejected_jobs_index()
        self.assertIsNotNone(rejected.match(
            source="Test Board", job_id="provider-42", url="https://jobs.test/opening/42",
        ))

    def test_rejected_jobs_write_failure_never_deletes_visible_row(self):
        self.fake.data["Job Scout"][1][SCOUT.index("Status")] = "Delete / Reject"
        with patch.object(
            self.tracker, "append_rejected_jobs", side_effect=RuntimeError("simulated write failure")
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated write failure"):
                process_rejected_rows(self.tracker, self.store)
        self.assertEqual(len(self.fake.data["Job Scout"]), 2)
        self.assertFalse(any("deleteDimension" in request for request in self.fake.structural))

    def test_row_identity_change_after_archive_prevents_deletion(self):
        visible = self.fake.data["Job Scout"][1]
        visible[SCOUT.index("Source")] = "Test Board"
        visible[SCOUT.index("Company")] = "Same Company"
        visible[SCOUT.index("Job Title")] = "Paid Search Manager"
        visible[SCOUT.index("Job URL")] = "https://jobs.test/opening/42"
        visible[SCOUT.index("Status")] = "Reject"
        original_scout = self.tracker.scout
        reads = 0

        def scout_with_concurrent_edit(*args, **kwargs):
            nonlocal reads
            reads += 1
            if reads == 3:
                self.fake.data["Job Scout"][1][SCOUT.index("Company")] = "Changed Company"
            return original_scout(*args, **kwargs)

        with patch.object(self.tracker, "scout", side_effect=scout_with_concurrent_edit):
            with self.assertRaisesRegex(RuntimeError, "changed Job Scout rows"):
                process_rejected_rows(self.tracker, self.store)
        self.assertEqual(len(self.fake.data["Job Scout"]), 2)
        self.assertFalse(any("deleteDimension" in request for request in self.fake.structural))

    def test_google_tracker_upsert_has_final_rejection_guard(self):
        self.tracker.append_rejected_job(rejection_record(
            source="Test Board", job_id="blocked", url="https://jobs.test/blocked",
            company="Same Company", title="Paid Search Manager",
            date_rejected="2026-10-04", reason="Reject",
        ))
        job = normalize(listing("blocked", "https://jobs.test/elsewhere"))
        job.id = 99
        result = self.tracker.upsert_scout([job], append_only=True)
        self.assertEqual(result["rejected_excluded"], 1)
        self.assertFalse(any(str(row[0]) == "99" for row in self.fake.data["Job Scout"][1:]))

    def test_manual_indeed_scout_respects_rejection_history_without_cell_writes(self):
        url = "https://www.indeed.com/viewjob?jk=blocked-jk&utm_source=email"
        row = [""] * len(SCOUT)
        row[SCOUT.index("Job URL")] = url
        row[SCOUT.index("Apply?")] = "Yes"
        self.fake.data["Job Scout"].append(row)
        self.tracker.append_rejected_job(rejection_record(
            source="Indeed", job_id="blocked-jk", url=url,
            company="Same Company", title="Same Job Title",
            date_rejected="2026-10-04", reason="Reject",
        ))
        writes_before = list(self.fake.writes)
        result = process_manual_indeed_rows(
            self.tracker, self.store, provider=NoCallProvider(), today="2026-10-04",
        )
        self.assertEqual(result.rejected, 1)
        self.assertEqual(result.processed, 0)
        self.assertEqual(self.fake.writes, writes_before)
        self.assertEqual(self.store.all(), [])

    def test_final_resume_link_writer_blocks_rejection_without_cell_writes(self):
        self.tracker.append_rejected_job(rejection_record(
            source="test", job_id="", url="https://example.test/job",
            company="Same Company", title="Paid Search Manager",
            date_rejected="2026-10-04", reason="Reject",
        ))
        writes_before = list(self.fake.writes)
        with self.assertRaisesRegex(RuntimeError, "permanently rejected"):
            self.tracker.mark_scout_resume(42, "https://drive.google.test/resume")
        self.assertEqual(self.fake.writes, writes_before)


if __name__ == "__main__":
    unittest.main()
