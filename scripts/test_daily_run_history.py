"""Daily Run layout and insertion regressions; all Sheets calls are fake."""

from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "job-scout"))

from daily_run_history import ZERO_FALLBACK_METRICS, build_block, inspect_history, write_history
from test_daily_report import FakeSheets


class DailyRunHistoryTests(unittest.TestCase):
    def tracker(self):
        fake = FakeSheets()
        tracker = SimpleNamespace(api=fake,
            config=SimpleNamespace(spreadsheet_id="test"),
            _sheet_properties=fake._sheet_properties)
        return fake, tracker

    def test_sources_are_sorted_numeric_and_start_at_e9(self):
        block = build_block({"Run Date": "2026-10-10", "Run ID": "one",
                             "Jobs by Source": {"zeta": 2, "Alpha": 4},
                             "Jobs Ready to Apply": 1})
        self.assertEqual(block[6][4], "Jobs by Source")
        self.assertEqual(block[7][4:6], ["Alpha", 4])
        self.assertEqual(block[8][4:6], ["zeta", 2])
        self.assertEqual(block[-1], [""] * 6)
        self.assertNotIn("{", str(block[7]))

    def test_only_named_missing_metrics_render_as_numeric_zero(self):
        fields = {"Run Date": "2026-10-10", "Run ID": "one", "Jobs by Source": {},
                  "Report Details": "summary", "Started At": "Unavailable"}
        fields.update({name: None for name in ZERO_FALLBACK_METRICS})
        fields["Indeed Found"] = " unavailable "
        fields["Total Found"] = ""
        fields["Existing Jobs"] = 7
        fields["Qualified Jobs"] = 0
        block = build_block(fields)
        metrics = {row[0]: row[1] for row in block if row[0]}
        for name in ZERO_FALLBACK_METRICS - {"Existing Jobs", "Qualified Jobs"}:
            self.assertEqual(metrics[name], 0, name)
            self.assertIs(type(metrics[name]), int, name)
        self.assertEqual(metrics["Existing Jobs"], 7)
        self.assertEqual(metrics["Qualified Jobs"], 0)
        self.assertEqual(metrics["Started At"], "Unavailable")
        self.assertNotIn("Report Details", metrics)
        self.assertEqual(fields["Job Scout Found"], None)
        self.assertEqual(fields["Indeed Found"], " unavailable ")

    def test_report_details_removal_closes_gap_in_a_b(self):
        block = build_block({"Run Date": "2026-10-10", "Run ID": "one",
                             "Jobs by Source": {}, "Errors": 2,
                             "Report Details": "summary", "Warnings": 3})
        self.assertEqual(block[2][:2], ["Errors", 2])
        self.assertEqual(block[3][:2], ["Warnings", 3])
        self.assertNotIn("Report Details", [row[0] for row in block])

    def test_row_three_insertion_preserves_old_a_b_and_e_f(self):
        fake, tracker = self.tracker()
        first = {"Run Date": "2026-10-09", "Run ID": "old",
                 "Jobs by Source": {"Indeed": 5}, "Errors": 0}
        second = {"Run Date": "2026-10-10", "Run ID": "new",
                  "Jobs by Source": {"Adzuna": 2, "Indeed": 3}, "Errors": 0}
        self.assertEqual(write_history(tracker, first)[0], 3)
        old_rows = [list(row) for row in fake.data["Daily Run"]]
        _, height = write_history(tracker, second)
        self.assertEqual(fake.data["Daily Run"][2][1], "2026-10-10")
        self.assertEqual(fake.data["Daily Run"][8][4], "Jobs by Source")
        self.assertEqual(fake.data["Daily Run"][9][4:6], ["Adzuna", 2])
        self.assertEqual(fake.data["Daily Run"][2 + height:], old_rows[2:])
        before = [list(row) for row in fake.data["Daily Run"]]
        self.assertEqual(write_history(tracker, second), (None, 0))
        self.assertEqual(fake.data["Daily Run"], before)

    def test_history_write_keeps_numeric_zero_and_valid_counts(self):
        fake, tracker = self.tracker()
        fields = {"Run Date": "2026-10-10", "Run ID": "one",
                  "Jobs by Source": {"Indeed": 5},
                  "Job Scout Found": "Unavailable", "Indeed Found": 12,
                  "Projected Adds": None, "Indeed Actual After": "Unavailable"}
        write_history(tracker, fields)
        values = {row[0]: row[1] for row in fake.data["Daily Run"] if row}
        self.assertIs(type(values["Job Scout Found"]), int)
        self.assertEqual(values["Job Scout Found"], 0)
        self.assertEqual(values["Indeed Found"], 12)
        self.assertIs(type(values["Projected Adds"]), int)
        self.assertEqual(values["Indeed Actual After"], "Unavailable")

    def test_retry_after_committed_response_loss_verifies_without_duplicate(self):
        fake, tracker = self.tracker()
        fields = {"Run Date": "2026-10-11", "Run ID": "retry",
                  "Jobs by Source": {"Indeed": 5}, "Job Scout Found": None,
                  "Report Details": "omit", "Errors": 0}
        fake.fail_history_after_commit = True
        with self.assertRaisesRegex(OSError, "lost history response"):
            write_history(tracker, fields)
        committed = [list(row) for row in fake.data["Daily Run"]]
        self.assertEqual(write_history(tracker, fields), (None, 0))
        self.assertEqual(fake.data["Daily Run"], committed)
        self.assertEqual(sum(row[:1] == ["Run ID"] for row in committed), 1)

    def test_failed_atomic_request_retries_without_blank_gap(self):
        fake, tracker = self.tracker()
        fields = {"Run Date": "2026-10-11", "Run ID": "retry",
                  "Jobs by Source": {}, "Job Scout Found": None}
        fake.fail_history_before_commit = True
        with self.assertRaisesRegex(OSError, "before commit"):
            write_history(tracker, fields)
        self.assertEqual(fake.data["Daily Run"], [[], []])
        self.assertEqual(write_history(tracker, fields)[0], 3)

    def test_incomplete_existing_run_id_is_not_treated_as_success(self):
        fake, tracker = self.tracker()
        fields = {"Run Date": "2026-10-11", "Run ID": "retry",
                  "Jobs by Source": {}, "Job Scout Found": None}
        write_history(tracker, fields)
        fake.data["Daily Run"][4][0] = "wrong label"
        with self.assertRaisesRegex(RuntimeError, "missing or shifted metrics"):
            write_history(tracker, fields)

    def test_unknown_layout_formula_and_missing_tab_block(self):
        with self.assertRaisesRegex(RuntimeError, "unknown layout"):
            inspect_history([[], [], ["manual"]], "one")
        with self.assertRaisesRegex(RuntimeError, "formulas"):
            inspect_history([[], [], ["Daily Run", "date"], ["Run ID", "old"], ["=NOW()"]], "one")
        fake, tracker = self.tracker()
        del fake.data["Daily Run"]
        with self.assertRaisesRegex(RuntimeError, "not found"):
            write_history(tracker, {"Run ID": "one", "Run Date": "2026-10-10", "Jobs by Source": {}})


if __name__ == "__main__":
    unittest.main()
