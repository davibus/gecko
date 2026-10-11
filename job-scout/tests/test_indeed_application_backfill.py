"""Isolated live-sheet backfill contract tests; no Google API calls."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from google_tracker import Config, GoogleTracker, INDEED_APPLICATION_HEADER
from indeed_application_backfill import backfill
from test_google_tracker import FakeSheets, SCOUT


NOW = datetime(2026, 10, 7, 23, 0, tzinfo=timezone.utc)


def observation(row, jk, label, **overrides):
    result = {"row": row, "page_url": f"https://www.indeed.com/viewjob?jk={jk}",
            "button_text": label, "primary_blue": True, "visible": True,
            "observed_at": NOW.isoformat()}
    result.update(overrides)
    return result


def status_observation(row, jk, label, **overrides):
    result = observation(row, jk, "")
    result.pop("button_text")
    result.pop("primary_blue")
    result.update({"status_text": label, "primary_status": True})
    result.update(overrides)
    return result


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSheets()
        self.tracker = GoogleTracker(
            Config("test-id", Path("unused.json"), "Job Tracker", "Job Scout"), self.fake)
        self.fake.data["Job Scout"] = [list(SCOUT)]
        for source, jk, current in (("Indeed", "website", ""),
                                    ("indeed", "now", "Company Website"),
                                    ("Indeed", "easy", ""),
                                    ("Indeed", "missing", "Company Website"),
                                    ("LinkedIn", "other", "Manual value")):
            record = dict.fromkeys(SCOUT, "")
            record.update({"Source": source, "Job URL": f"https://www.indeed.com/viewjob?jk={jk}",
                           INDEED_APPLICATION_HEADER: current, "Notes": f"Keep {jk}",
                           "Resume Created": "X"})
            self.fake.data["Job Scout"].append([record[name] for name in SCOUT])

    def test_targeted_backfill_and_rerun(self):
        initial = [list(row) for row in self.fake.data["Job Scout"]]
        evidence = {2: observation(2, "website", "Apply on Company Website"),
                    3: observation(3, "now", "Apply Now"),
                    4: observation(4, "easy", "Easy Apply"),
                    6: observation(6, "other", "Apply on Company Website")}
        result = backfill(self.tracker, evidence, now=NOW, batch_size=1)
        self.assertEqual(result.changed_rows, [2, 3, 4])
        self.assertEqual(result.unresolved_rows, [5])
        self.assertEqual(result.statuses_found, {"Apply on Company Website": 1,
                                                 "Apply Now": 1, "Easy Apply": 1})
        self.assertEqual(result.existing_nonblank, {"Company Website": 2})
        self.assertEqual((result.blank_before, result.blank_after), (2, 0))
        self.assertEqual((result.total_rows_before, result.total_rows_after), (5, 5))
        self.assertEqual(self.fake.structural, [])
        self.assertEqual(self.fake.writes, [("Job Scout", 2, "K"), ("Job Scout", 3, "K"),
                                            ("Job Scout", 4, "K")])
        self.assertEqual([row[SCOUT.index(INDEED_APPLICATION_HEADER)] for row in self.fake.data["Job Scout"][1:4]],
                         ["Apply on Company Website", "Apply Now", "Easy Apply"])
        for index, (before, after) in enumerate(zip(initial, self.fake.data["Job Scout"])):
            if index == 0:
                self.assertEqual(before, after)
            else:
                self.assertEqual(before[:10] + before[11:], after[:10] + after[11:])
        again = backfill(self.tracker, evidence, now=NOW)
        self.assertEqual(again.changed_rows, [])
        self.assertEqual(len(self.fake.writes), 3)

    def test_rearranged_header_and_unreadable_evidence(self):
        old_headers = self.fake.data["Job Scout"][0]
        reordered = [INDEED_APPLICATION_HEADER] + [name for name in old_headers if name != INDEED_APPLICATION_HEADER]
        self.fake.data["Job Scout"] = [reordered] + [
            [dict(zip(old_headers, row))[name] for name in reordered]
            for row in self.fake.data["Job Scout"][1:]]
        evidence = {2: observation(2, "website", "Apply on Company Website"),
                    3: observation(3, "now", "Apply Now", visible=False),
                    4: observation(4, "easy", "Easy Apply", page_url="https://www.indeed.com/viewjob?jk=wrong"),
                    5: observation(5, "missing", "Apply on Company Website",
                                   primary_blue=False)}
        result = backfill(self.tracker, evidence, now=NOW)
        self.assertEqual(result.changed_rows, [2])
        self.assertEqual(result.unresolved_rows, [3, 4, 5])
        self.assertEqual(self.fake.writes, [("Job Scout", 2, "A")])
        self.assertEqual(self.fake.data["Job Scout"][1][0], "Apply on Company Website")

    def test_primary_status_exact_text_and_new_label(self):
        evidence = {2: status_observation(2, "website", "Job no longer available"),
                    3: status_observation(3, "now", "Already applied"),
                    4: observation(4, "easy", "Continue application")}
        result = backfill(self.tracker, evidence, now=NOW)
        self.assertEqual(result.changed_rows, [2, 3, 4])
        self.assertEqual(result.statuses_found, {"Job no longer available": 1,
                                                 "Already applied": 1,
                                                 "Continue application": 1})
        self.assertEqual([row[SCOUT.index(INDEED_APPLICATION_HEADER)] for row in self.fake.data["Job Scout"][1:4]],
                         ["Job no longer available", "Already applied", "Continue application"])
        again = backfill(self.tracker, evidence, now=NOW)
        self.assertEqual(again.changed_rows, [])

    def test_expired_observation_normalizes_status_and_disables_apply(self):
        self.fake.data["Job Scout"][1][SCOUT.index("Apply?")] = "Yes"
        result = backfill(self.tracker, {
            2: status_observation(2, "website", " This job has expired on Indeed ")
        }, now=NOW)
        self.assertEqual(result.changed_rows, [2])
        row = dict(zip(SCOUT, self.fake.data["Job Scout"][1]))
        self.assertEqual(row[INDEED_APPLICATION_HEADER], "Expired")
        self.assertEqual(row["Apply?"], "No")

    def test_existing_expired_enforces_no_without_new_observation(self):
        row = self.fake.data["Job Scout"][1]
        row[SCOUT.index(INDEED_APPLICATION_HEADER)] = " eXpIrEd "
        row[SCOUT.index("Apply?")] = "Yes"
        result = backfill(self.tracker, {}, now=NOW)
        self.assertEqual(result.changed_rows, [2])
        self.assertEqual(row[SCOUT.index(INDEED_APPLICATION_HEADER)], "Expired")
        self.assertEqual(row[SCOUT.index("Apply?")], "No")

    def test_unresolved_preserves_existing_and_blank(self):
        evidence = {2: observation(2, "website", "", visible=False),
                    4: status_observation(4, "easy", "Job no longer available", primary_status=False)}
        result = backfill(self.tracker, evidence, now=NOW)
        self.assertEqual(result.changed_rows, [])
        self.assertEqual(self.fake.data["Job Scout"][1][SCOUT.index(INDEED_APPLICATION_HEADER)], "")
        self.assertEqual(self.fake.data["Job Scout"][2][SCOUT.index(INDEED_APPLICATION_HEADER)], "Company Website")

    def test_short_indeed_redirect_requires_exact_sheet_url(self):
        index = SCOUT.index("Job URL")
        self.fake.data["Job Scout"][1][index] = "https://to.indeed.com/shortcode"
        evidence = observation(2, "resolved-key", "Apply on Company Website",
                               source_url="https://to.indeed.com/wrong")
        self.assertEqual(backfill(self.tracker, {2: evidence}, now=NOW).changed_rows, [])
        evidence["source_url"] = "https://to.indeed.com/shortcode"
        result = backfill(self.tracker, {2: evidence}, now=NOW)
        self.assertEqual(result.changed_rows, [2])
        self.assertEqual(self.fake.data["Job Scout"][1][SCOUT.index(INDEED_APPLICATION_HEADER)],
                         "Apply on Company Website")

    def test_readback_failure_stops_remaining_batches(self):
        self.fake.unclear_cells.add(("Job Scout", 2, "K"))
        evidence = {2: observation(2, "website", "Apply on Company Website"),
                    3: observation(3, "now", "Apply Now")}
        with self.assertRaisesRegex(RuntimeError, "Readback failed after batch for rows \\[2\\]"):
            backfill(self.tracker, evidence, now=NOW, batch_size=1)
        self.assertEqual(self.fake.writes, [("Job Scout", 2, "K")])


if __name__ == "__main__":
    unittest.main()
