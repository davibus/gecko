"""Focused reset and approval regressions; never contacts Google Sheets."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "job-scout"), str(ROOT / "job-scout/tests")]

import generate_apply_queue as queue
from google_tracker import Config, GoogleTracker, append_rows_requests, resume_approval_value
from test_google_tracker import FakeSheets, SCOUT
from reset_tracker_tabs import planned_range
from daily_tasks_dashboard import _format_requests
from rejection_workflow import process_rejected_rows


class ResetApprovalTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSheets()
        self.fake.data["Job Scout"] = self.fake.data["Job Scout"][:1]
        self.tracker = GoogleTracker(
            Config("test", Path("unused.json"), "Job Tracker", "Job Scout"), self.fake)

    def row(self, identity, *, decision="Yes", cost="Free", location="Utah",
            arrangement="on-site", applied="", created="", link="", url=None,
            indeed_status=""):
        values = [""] * len(SCOUT)
        for name, value in {"ID": identity, "Source": "test", "Company": f"Co {identity}",
                            "Job Title": "Role", "Apply?": decision, "Cost": cost,
                            "Location": location, "Work Arrangement": arrangement,
                            "Applied": applied, "Resume Created": created,
                            "Resume Link": link,
                            "Job URL": url if url is not None else f"https://example.test/{identity}",
                            "Apply or on Company Website (If Indeed)": indeed_status}.items():
            values[SCOUT.index(name)] = value
        self.fake.data["Job Scout"].append(values)

    def test_unique_column_e_approval_and_no_status_requirement(self):
        tab = self.tracker.scout()
        self.assertEqual(tab.headers["Apply?"], 5)
        self.assertNotIn("Gecko Status", tab.headers)

    def test_yes_needs_geography_and_excludes_only_required_fee(self):
        self.assertEqual(resume_approval_value("Utah", "on-site", "Free"), "Yes")
        self.assertEqual(resume_approval_value("California", "Remote", "No Fee"), "Yes")
        self.assertEqual(resume_approval_value("Utah", "on-site", ""), "Yes")
        self.assertEqual(resume_approval_value("California", "Remote", "unknown"), "Yes")
        for location, arrangement, cost in (("", "", "Free"),
                                             ("California", "Hybrid", "Free"),
                                             ("Utah", "on-site", " x ")):
            self.assertEqual(resume_approval_value(location, arrangement, cost), "No")

    def test_queue_protections_and_trimmed_yes(self):
        self.row(100, decision="  yEs  ")
        self.row(101, cost="")
        self.row(102, location="", arrangement="")
        self.row(103, applied="X")
        self.row(104, url="not a URL")
        self.row(105, created=" x ")
        self.row(106, link="file:///existing.docx")
        self.row(107, indeed_status="Expired")
        self.row(108, decision="No")
        self.row(109, decision="Reject")
        self.row(110, cost="x")
        snapshot = queue.read_queue(self.tracker)
        self.assertEqual([item.scout_id for item in snapshot.pending], [100, 101])
        self.assertEqual({item.scout_id for item in snapshot.already_created}, {105, 106})
        self.assertIn(109, {item.scout_id for item in snapshot.rejected_excluded})
        self.assertEqual({item.scout_id for item in snapshot.cost_excluded}, {110})
        self.assertEqual(len(snapshot.not_approved), 5)

    def test_required_fee_forces_no_without_changing_cost(self):
        self.row(111, decision="Yes", cost=" X ")
        self.tracker.disqualify_required_fee_row(2, company="Co 111", title="Role")
        updated = dict(self.tracker.scout().rows)[2]
        self.assertEqual(updated["Apply?"], "No")
        self.assertEqual(updated["Cost"], " X ")

    def test_ambiguous_approval_header_stops(self):
        self.fake.data["Job Scout"][0].append("Apply")
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            self.tracker.scout()

    def test_completed_resume_and_applied_guards_block_direct_mark(self):
        self.row(201, created=" x ")
        self.row(202, applied="X")
        with self.assertRaisesRegex(RuntimeError, "Resume Created = X"):
            self.tracker.mark_scout_resume(201, "https://example.test/resume")
        with self.assertRaisesRegex(RuntimeError, "Already applied"):
            self.tracker.mark_scout_resume(202, "https://example.test/resume")

    def test_reject_marker_in_approval_column_is_archived_first(self):
        self.row(203, decision="Reject")
        result = process_rejected_rows(self.tracker, SimpleNamespace(get=lambda _: None))
        self.assertEqual((result.marked, result.archived, result.removed), (1, 1, 1))
        self.assertEqual(len(self.fake.data["Rejected Jobs"]), 2)

    def test_row_height_requests_and_reset_boundaries(self):
        requests = append_rows_requests(123, 20, 2)
        self.assertEqual(requests[1]["updateDimensionProperties"]["properties"]["pixelSize"], 21)
        self.assertEqual(requests[1]["updateDimensionProperties"]["range"]["endIndex"], 22)
        self.assertEqual(planned_range("Daily Tasks", [["DAILY TASKS"], [],
                         ["GECKO DAILY TASKS REPORT"]], ["DAILY TASKS"]), "A3:F3")
        self.assertEqual(planned_range("Daily Run", [[], [], ["Daily Run"]], []), "A3:F3")
        dashboard = _format_requests(123, {name: [] for name in (
            "title", "date", "section", "source_header", "status_pass",
            "status_warning", "status_fail", "numbers", "audit")}, 3, False)
        self.assertFalse(any(request.get("updateDimensionProperties", {}).get("range", {}).get(
            "dimension") == "ROWS" and request["updateDimensionProperties"]["properties"].get(
                "pixelSize") != 21 for request in dashboard))
        with self.assertRaisesRegex(RuntimeError, "Formula protects"):
            planned_range("Daily Run", [[], [], ["Daily Run", "=A3"]], [])


if __name__ == "__main__":
    unittest.main()
