from __future__ import annotations

from contextlib import ExitStack, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import candidate_profile
from ai_evaluation import screening_models, validate_candidate_profile_for_ai
import scout


class CandidateProfileValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.master = Path(self.temp.name) / "master.txt"
        self.master.write_bytes(b"Reviewed source\n")
        self.profile_path = Path(self.temp.name) / "profile.json"
        self.profile = json.loads(candidate_profile.DEFAULT_PROFILE.read_text(encoding="utf-8-sig"))
        self.profile["master_resume_sha256"] = hashlib.sha256(self.master.read_bytes()).hexdigest()
        self.write_profile()
        patcher = patch.object(candidate_profile, "MASTER_RESUME", self.master)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_profile(self):
        self.profile_path.write_text(json.dumps(self.profile), encoding="utf-8")

    def test_current_bytes_pass(self):
        self.assertEqual(candidate_profile.load_candidate_profile(self.profile_path), self.profile)

    def test_changed_content_is_rejected(self):
        self.master.write_bytes(b"Changed source\n")
        with self.assertRaisesRegex(ValueError, "candidate profile is stale"):
            candidate_profile.load_candidate_profile(self.profile_path)

    def test_line_endings_and_bom_are_part_of_fingerprint(self):
        for raw in (b"Reviewed source\r\n", b"\xef\xbb\xbfReviewed source\n"):
            with self.subTest(raw=raw):
                self.master.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, "candidate profile is stale"):
                    candidate_profile.load_candidate_profile(self.profile_path)

    def test_matching_hash_does_not_bypass_required_fields(self):
        del self.profile["leadership"]
        self.write_profile()
        with self.assertRaisesRegex(ValueError, "missing: leadership"):
            candidate_profile.load_candidate_profile(self.profile_path)

    def test_missing_source_and_profile_are_rejected(self):
        self.profile_path.unlink()
        with self.assertRaisesRegex(FileNotFoundError, "candidate profile"):
            candidate_profile.load_candidate_profile(self.profile_path)
        self.write_profile()
        self.master.unlink()
        with self.assertRaisesRegex(FileNotFoundError, "master resume"):
            candidate_profile.load_candidate_profile(self.profile_path)


class DailyProfilePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stale = Path(self.temp.name) / "stale.json"
        profile = json.loads(candidate_profile.DEFAULT_PROFILE.read_text(encoding="utf-8-sig"))
        profile["master_resume_sha256"] = "0" * 64
        self.stale.write_text(json.dumps(profile), encoding="utf-8")
        self.preferences = {"ai_evaluation": {
            "triage_model": " triage ", "scoring_model": " scoring ",
            "candidate_profile": str(self.stale),
        }}
        patcher = patch.dict(os.environ, {}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_configured_stale_profile_rejected_when_enabled(self):
        with self.assertRaisesRegex(ValueError, "candidate profile is stale"):
            validate_candidate_profile_for_ai(self.preferences)

    def test_valid_default_and_custom_profiles_pass(self):
        for path in ("", str(candidate_profile.DEFAULT_PROFILE)):
            with self.subTest(path=path):
                self.preferences["ai_evaluation"]["candidate_profile"] = path
                validate_candidate_profile_for_ai(self.preferences)

    def test_environment_overrides_match_evaluator_enablement(self):
        self.assertEqual(screening_models(self.preferences), ("triage", "scoring"))
        for env in ({"JOB_SCOUT_TRIAGE_MODEL": " "}, {"JOB_SCOUT_SCORING_MODEL": ""}):
            with self.subTest(env=env), patch.dict(os.environ, env):
                validate_candidate_profile_for_ai(self.preferences)
        self.preferences["ai_evaluation"]["triage_model"] = ""
        self.preferences["ai_evaluation"]["scoring_model"] = ""
        validate_candidate_profile_for_ai(self.preferences)
        with patch.dict(os.environ, {"JOB_SCOUT_TRIAGE_MODEL": " t ", "JOB_SCOUT_SCORING_MODEL": " s "}):
            self.assertEqual(screening_models(self.preferences), ("t", "s"))
            with self.assertRaisesRegex(ValueError, "candidate profile is stale"):
                validate_candidate_profile_for_ai(self.preferences)

    def test_main_rejects_before_opening_database_or_daily(self):
        for options in ([], ["--dry-run"]):
            with (self.subTest(options=options),
                  patch.object(sys, "argv", ["scout.py", "daily", *options]),
                  patch("scout.load_local_environment"),
                  patch("scout.load_preferences", return_value=self.preferences),
                  patch("scout.JobStore") as database,
                  patch("scout.daily") as daily,
                  redirect_stderr(io.StringIO()) as errors):
                self.assertEqual(scout.main(), 1)
                self.assertIn("candidate profile is stale", errors.getvalue())
                database.assert_not_called()
                daily.assert_not_called()

    def test_direct_daily_rejects_before_any_workflow_activity(self):
        boundaries = ["JobStore", "DailyLinkValidator", "sheet_only_active_jobs",
                      "protected_job_ids", "scout_row_ids", "sync_tracker", "search",
                      "GoogleTracker", "process_manual_indeed_rows", "JobEvaluator",
                      "_daily_resume_runner", "_daily_gmail_response_runner"]
        for options in ([], ["--dry-run"]):
            with self.subTest(options=options), ExitStack() as stack:
                mocks = [stack.enter_context(patch("scout." + name)) for name in boundaries]
                store = Mock()
                args = scout.build_parser().parse_args(["daily", *options])
                with self.assertRaisesRegex(ValueError, "candidate profile is stale"):
                    scout.daily(args, store, self.preferences)
                self.assertEqual(store.mock_calls, [])
                for boundary in mocks:
                    boundary.assert_not_called()

    def test_valid_profile_reaches_daily_workflow_boundary(self):
        self.preferences["ai_evaluation"]["candidate_profile"] = ""
        args = scout.build_parser().parse_args(["daily"])
        with patch("scout.DailyLinkValidator", side_effect=RuntimeError("workflow boundary")):
            with self.assertRaisesRegex(RuntimeError, "workflow boundary"):
                scout.daily(args, Mock(), self.preferences)


if __name__ == "__main__":
    unittest.main()
