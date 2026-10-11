"""Schema and report regressions; no live Google Sheet access."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daily_report import build_snapshot
from tracker_schema import (CURRENT_SCOUT_HEADERS, INDEED_APPLICATION_HEADER, SCOUT_TAB,
                            discover_tabs, resolve_headers)


class TrackerSchemaReportTests(unittest.TestCase):
    def test_live_tab_discovery_classifies_unknown_without_assigning_writer(self):
        tabs = discover_tabs([{"title": SCOUT_TAB, "sheetId": 1},
                              {"title": "Rejected Jobs", "sheetId": 2},
                              {"title": "New User Tab", "sheetId": 3},
                              {"title": "Daily Run", "sheetId": 4},
                              {"title": "Scratch", "sheetId": 5}])
        self.assertEqual(tabs[SCOUT_TAB]["role"], "required")
        self.assertEqual(tabs["Daily Run"]["role"], "optional")
        self.assertEqual(tabs["New User Tab"]["role"], "unassigned")
        self.assertEqual(tabs["Scratch"]["role"], "unassigned")

    def test_missing_or_duplicate_required_tabs_fail(self):
        with self.assertRaisesRegex(RuntimeError, "missing required tabs"):
            discover_tabs([{"title": SCOUT_TAB, "sheetId": 1}])
        with self.assertRaisesRegex(RuntimeError, "duplicate tab title/ID"):
            discover_tabs([{"title": SCOUT_TAB, "sheetId": 1},
                           {"title": "Rejected Jobs", "sheetId": 1}])

    def test_reordered_headers_and_documented_aliases(self):
        moved = list(reversed(CURRENT_SCOUT_HEADERS))
        moved[moved.index("ID")] = "Scout ID"
        moved[moved.index("Status")] = "Gecko Status"
        fields = resolve_headers(moved, required=("Scout ID", "Gecko Status", "Resume Link"))
        self.assertEqual(fields["Resume Link"], moved.index("Resume Link") + 1)
        self.assertEqual(fields["Scout ID"], moved.index("Scout ID") + 1)

    def test_unapproved_rename_missing_and_duplicate_alias_fail(self):
        with self.assertRaisesRegex(RuntimeError, "missing required"):
            resolve_headers(["Company", "Position"], required=("Job Title",))
        with self.assertRaisesRegex(RuntimeError, "ambiguous"):
            resolve_headers(["ID", "Scout ID"], required=("Scout ID",))
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            resolve_headers(["Job URL", " job   url "])

    def test_report_separates_observed_proposed_and_completed(self):
        rows = [
            (2, {"Scout ID": 1, "Source": "Indeed", "Company": "A", "Job Title": "Role",
                 "Job URL": "https://www.indeed.com/viewjob?jk=abc", "Apply?": "Yes",
                 "Resume Created": "", "Resume Link": "", INDEED_APPLICATION_HEADER: ""}),
            (3, {"Scout ID": 2, "Source": "indeed", "Company": "A", "Job Title": "Role",
                 "Job URL": "https://www.indeed.com/viewjob?jk=abc&utm_source=mail",
                 "Apply?": "Yes", "Resume Created": "", "Resume Link": ""}),
            (4, {"Scout ID": 3, "Source": "adzuna", "Company": "B", "Job Title": "Role",
                 "Apply?": "Yes", "Resume Created": " X ", "Resume Link": ""}),
            (5, {"Scout ID": 4, "Source": "adzuna", "Company": "C", "Job Title": "Role",
                 "Apply?": "Yes", "Resume Created": "", "Resume Link": "file:///existing.docx"}),
            (6, {"Scout ID": 5, "Source": "adzuna", "Company": "D", "Job Title": "Role",
                 "Apply?": "Yes", "Resume Created": "", "Resume Link": "", "Cost": " x "}),
        ]
        report = build_snapshot(rows)
        observed = report["observed"]
        self.assertEqual(observed["existing_duplicate_rows"], 1)
        self.assertEqual(observed["blank_indeed_statuses_before"], 2)
        self.assertEqual(observed["missing_resume_links"], 1)
        self.assertEqual(observed["eligible_jobs"], 2)
        self.assertEqual(report["proposed"]["resume_generations"], 2)
        self.assertEqual(report["completed_by_this_command"]["resume_generations"], 0)
        self.assertEqual(observed["total_jobs_before"], observed["total_jobs_after"])


if __name__ == "__main__":
    unittest.main()
