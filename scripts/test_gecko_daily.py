"""Safety and reporting checks for the single daily entry point."""

from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gecko_daily
from daily_run_history import build_block


class GeckoDailyTests(unittest.TestCase):
    def test_live_output_is_retained_for_audit(self):
        import sys
        from contextlib import redirect_stdout
        from io import StringIO
        observed = StringIO()
        with redirect_stdout(observed):
            result = gecko_daily.run_streamed([sys.executable, "-c", "print('workflow progress')"], timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("workflow progress", result.stdout)
        self.assertEqual(result.stdout, observed.getvalue())

    def test_missing_approval_header_has_clear_redacted_error(self):
        error = RuntimeError(
            "Google worksheet 'Job List' has missing header for 'Apply?'; "
            "expected exactly one of 'Apply?', 'Apply'")
        self.assertEqual(gecko_daily.safe_error(error),
                         "Job List approval header is missing or ambiguous; daily workflow stopped")

    def test_parser_keeps_missing_counts_unavailable(self):
        counts = gecko_daily.counts_from_output(
            "New jobs added: 2\nResumes already existing: 8\n"
            "New Gecko resumes created: 1\nGmail responses matched: 3\n")
        self.assertEqual(counts["New Jobs Added"], 2)
        self.assertEqual(counts["Resumes Reused"], 8)
        self.assertEqual(counts["Employer Responses Matched"], 3)
        self.assertEqual(counts["Response Rows Updated"], "Unavailable")

    def test_missing_history_blocks_apply_before_runner(self):
        tracker = SimpleNamespace(config=SimpleNamespace(scout_tab="Job List"))
        calls = []

        def runner(*args, **kwargs):
            calls.append(args)
            raise AssertionError("daily workflow must not start")

        with tempfile.TemporaryDirectory() as folder, patch.object(
            gecko_daily, "inventory", return_value={"validation": {"daily_run_present": False}}
        ):
            code, report = gecko_daily.run(
                apply=True, runner=runner, tracker_factory=lambda: tracker,
                audit_root=Path(folder))
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertFalse(report["daily_run_written"])
        self.assertIn("Daily Run tab is missing", report["errors"][0])

    def test_dry_run_does_not_write_history(self):
        tracker = SimpleNamespace(config=SimpleNamespace(scout_tab="Job List"))
        completed = SimpleNamespace(returncode=0,
            stdout="Daily Job Scout complete (dry run)\nNew jobs added: 0\nNew Gecko resumes created: 0\n",
            stderr="")
        with tempfile.TemporaryDirectory() as folder, patch.object(
            gecko_daily, "inventory", return_value={"validation": {"daily_run_present": False}}
        ), patch("generate_apply_queue.read_queue", return_value=SimpleNamespace(
            pending=[], already_created=[], cost_excluded=[], rejected_excluded=[], duplicate_excluded=[]
        )), patch.object(gecko_daily, "write_history", side_effect=AssertionError("history write")):
            code, report = gecko_daily.run(
                apply=False, runner=lambda command, **kw: completed,
                tracker_factory=lambda: tracker, audit_root=Path(folder))
        self.assertEqual(code, 0)
        self.assertFalse(report["daily_run_written"])

    def test_history_contains_requested_outcomes(self):
        counts = gecko_daily.counts_from_output(
            "New jobs added: 1\nNew Gecko resumes created: 2\n"
            "Resumes already existing: 5\nGmail responses matched: 3\n"
            "Gmail emails checked: 10\nResume failures: 1")
        fields = gecko_daily.history_fields("run-1", "2026-10-11", counts,
                                           {"Indeed": 4}, dry_run=False,
                                           exit_code=0)
        self.assertEqual(fields["New Jobs Added"], 1)
        self.assertEqual(fields["Resumes Created"], 2)
        self.assertEqual(fields["Resumes Reused"], 5)
        self.assertEqual(fields["Employer Responses Matched"], 3)
        self.assertIn("Resume generation failures", fields["Attention Items"])
        self.assertEqual(fields["Applications Submitted"], 0)
        block = build_block(fields)
        self.assertEqual(block[0][0], "Daily Run")
        self.assertIn(["Indeed", 4], [row[4:6] for row in block])

    def test_apply_runs_existing_daily_then_writes_history(self):
        tracker = SimpleNamespace(config=SimpleNamespace(scout_tab="Job List"))
        completed = SimpleNamespace(returncode=0, stdout=(
            "Daily Job Scout complete\nNew jobs added: 2\nNew Gecko resumes created: 1\n"
            "Resumes already existing: 7\nGmail emails checked: 4\n"
            "Gmail responses matched: 1\nResponse rows updated: 1\n"), stderr="")
        commands = []
        fields_written = []
        queue = SimpleNamespace(already_created=[], missing_identity=[])

        def runner(command, **kwargs):
            commands.append(command)
            return completed

        def history(_tracker, fields):
            fields_written.append(fields)
            return 3, 20

        with tempfile.TemporaryDirectory() as folder, patch.object(
            gecko_daily, "validate_live_targets", return_value={"validation": {}}
        ), patch.object(gecko_daily, "source_counts", return_value={"Indeed": 2}), patch(
            "generate_apply_queue.read_queue", return_value=queue
        ), patch.object(gecko_daily, "write_history", side_effect=history):
            code, report = gecko_daily.run(
                apply=True, runner=runner, tracker_factory=lambda: tracker,
                audit_root=Path(folder))
        self.assertEqual(code, 0)
        self.assertEqual(commands[0][-1], "daily")
        self.assertTrue(report["daily_run_written"])
        self.assertEqual(fields_written[0]["New Jobs Added"], 2)
        self.assertEqual(fields_written[0]["Applications Submitted"], 0)

    def test_scoped_apply_passes_only_requested_resume_ids(self):
        tracker = SimpleNamespace(config=SimpleNamespace(scout_tab="Job List"))
        completed = SimpleNamespace(returncode=0,
            stdout="Daily Job Scout complete\nNew jobs added: 0\nGmail emails checked: 0\n", stderr="")
        commands = []
        with tempfile.TemporaryDirectory() as folder, patch.object(
            gecko_daily, "validate_live_targets", return_value={"validation": {}}
        ), patch.object(gecko_daily, "source_counts", return_value={}), patch(
            "generate_apply_queue.read_queue", return_value=SimpleNamespace(
                already_created=[], missing_identity=[])
        ), patch.object(gecko_daily, "write_history", return_value=(3, 10)):
            code, report = gecko_daily.run(
                apply=True, resume_ids={2219, 2218},
                runner=lambda command, **kw: (commands.append(command) or completed),
                tracker_factory=lambda: tracker, audit_root=Path(folder))
        self.assertEqual(code, 0)
        self.assertEqual(commands[0][-3:], ["--resume-ids", "2218", "2219"])
        self.assertEqual(report["resume_ids"], [2218, 2219])

    def test_partial_discovery_counts_are_kept_when_later_step_fails(self):
        output = ('{\n  "fetched": 483, "duplicates": 38, '
                  '"newly_discovered": 1, "source_counts": {"indeed": 0}, '
                  '"source_errors": {"indeed": "HTTP 402"}\n}\n'
                  '{\n"job_scout_worksheet": {"added": 1}\n}\n')
        counts = gecko_daily.counts_from_output(output)
        self.assertEqual(counts["Jobs Discovered"], 483)
        self.assertEqual(counts["New Jobs Added"], 1)
        self.assertEqual(counts["Provider Failures"], 1)


if __name__ == "__main__":
    unittest.main()
