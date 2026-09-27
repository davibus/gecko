"""Offline tests for ATS employer discovery and configuration maintenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discover_ats_employers as discovery
from sources.base import ProviderError
from sources.http import FetchedDocument


class IdentifierExtractionTests(unittest.TestCase):
    def test_extracts_greenhouse_token(self):
        self.assertEqual(discovery.extract_identifier(
            "https://job-boards.greenhouse.io/acme/jobs/123"), ("greenhouse", "acme"))

    def test_extracts_lever_site(self):
        self.assertEqual(discovery.extract_identifier(
            "https://jobs.lever.co/acme/abc"), ("lever", "acme"))

    def test_extracts_ashby_board(self):
        self.assertEqual(discovery.extract_identifier(
            "https://jobs.ashbyhq.com/Acme/abc"), ("ashby", "Acme"))

    def test_extracts_workable_account(self):
        self.assertEqual(discovery.extract_identifier(
            "https://apply.workable.com/acme/j/ABC"), ("workable", "acme"))

    def test_rejects_invalid_and_wrong_domains(self):
        self.assertIsNone(discovery.extract_identifier("not a url"))
        self.assertIsNone(discovery.extract_identifier("https://example.com/acme"))
        self.assertIsNone(discovery.extract_identifier(
            "https://jobs.lever.co/acme", "greenhouse"))
        self.assertIsNone(discovery.extract_identifier("https://jooble.org/acme"))


class ValidationTests(unittest.TestCase):
    @patch("discover_ats_employers.get_document")
    @patch("discover_ats_employers.get_json_value")
    def test_board_validation_counts_relevant_and_remote_jobs(self, get_json, get_document):
        get_json.return_value = {"jobs": [{
            "id": 1, "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            "title": "Paid Media Director", "location": {"name": "Remote - US"},
            "content": "Own performance marketing and attribution.",
        }]}
        get_document.return_value = FetchedDocument(
            b"<title>Careers at Acme</title>", "https://job-boards.greenhouse.io/acme", "text/html")
        record = discovery.validate_candidate(discovery.Candidate(
            "Acme", "greenhouse", "acme", "https://job-boards.greenhouse.io/acme",
            ["site:job-boards.greenhouse.io marketing"]))
        self.assertEqual(record["validation_status"], "valid")
        self.assertEqual(record["marketing_job_count"], 1)
        self.assertEqual(record["remote_job_count"], 1)
        self.assertTrue(record["approved"])

    @patch("discover_ats_employers.get_document")
    @patch("discover_ats_employers.get_json_value", return_value=[])
    def test_zero_current_job_board_is_valid(self, _get_json, get_document):
        get_document.return_value = FetchedDocument(
            b"<title>Acme Jobs</title>", "https://jobs.lever.co/acme", "text/html")
        record = discovery.validate_candidate(discovery.Candidate(
            "Acme", "lever", "acme", "https://jobs.lever.co/acme",
            ["site:jobs.lever.co growth marketing"], ["Acme marketing software"]))
        self.assertEqual(record["validation_status"], "valid")
        self.assertEqual(record["open_job_count"], 0)
        self.assertTrue(record["approved"])

    @patch("discover_ats_employers.get_json_value", side_effect=ProviderError("HTTP 503"))
    def test_temporary_network_failure_is_classified(self, _get_json):
        record = discovery.validate_candidate(discovery.Candidate(
            "Acme", "lever", "acme", "https://jobs.lever.co/acme"))
        self.assertEqual(record["validation_status"], "temporary_failure")
        self.assertFalse(record["approved"])

    @patch("discover_ats_employers.get_json_value", return_value={"unexpected": []})
    def test_malformed_endpoint_response_is_rejected(self, _get_json):
        record = discovery.validate_candidate(discovery.Candidate(
            "Acme", "ashby", "acme", "https://jobs.ashbyhq.com/acme"))
        self.assertEqual(record["validation_status"], "invalid")
        self.assertIn("unexpected jobs payload", record["rejection_reason"])


class MergeAndCommandTests(unittest.TestCase):
    def setUp(self):
        self.config = {"providers": {
            "greenhouse": {"enabled": True, "companies": [
                {"name": "Manual Co", "token": "manual"}]},
            "lever": {"enabled": True, "companies": []},
            "ashby": {"enabled": True, "companies": []},
            "workable": {"enabled": True, "companies": []},
            "jooble": {"enabled": False},
        }}

    def test_deduplicates_identifier_and_normalized_name(self):
        candidates, duplicates = discovery.deduplicate_candidates([
            discovery.Candidate("Acme", "lever", "acme", "https://jobs.lever.co/acme"),
            discovery.Candidate("Acme, Inc.", "lever", "acme", "https://jobs.lever.co/acme"),
            discovery.Candidate("Acme Inc", "lever", "other", "https://jobs.lever.co/other"),
        ])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(duplicates), 2)

    def test_apply_preserves_manual_employer_and_sorts_stably(self):
        records = [
            {"platform": "greenhouse", "identifier": "zulu", "company": "Zulu",
             "approved": True, "existing": False},
            {"platform": "greenhouse", "identifier": "alpha", "company": "Alpha",
             "approved": True, "existing": False},
        ]
        added = discovery.merge_config(self.config, records, {"greenhouse"})
        companies = self.config["providers"]["greenhouse"]["companies"]
        self.assertEqual(added["greenhouse"], 2)
        self.assertEqual([item["name"] for item in companies], ["Alpha", "Manual Co", "Zulu"])
        self.assertIn({"name": "Manual Co", "token": "manual"}, companies)

    @patch("discover_ats_employers.validate_candidate")
    @patch("discover_ats_employers.discover", return_value=([], []))
    @patch("discover_ats_employers.load_local_environment")
    def test_dry_run_does_not_modify_config(self, _environment, _discover, validate):
        validate.side_effect = lambda candidate: {
            **discovery.asdict(candidate), "validation_status": "invalid", "approved": False,
            "open_job_count": 0, "marketing_job_count": 0, "us_job_count": 0,
            "remote_job_count": 0, "relevant_role_examples": [], "relevance_score": 0,
            "rejection_reason": "stale", "failure_count": 0,
        }
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "sources.json"
            report = Path(directory) / "report.json"
            original = json.dumps(self.config, indent=2) + "\n"
            config.write_text(original, encoding="utf-8")
            args = argparse.Namespace(dry_run=True, apply=False, refresh=False,
                                      platform=None, limit=None, config=config, report=report,
                                      seeds=Path(directory) / "missing-seeds.json")
            self.assertEqual(discovery.run(args), 0)
            self.assertEqual(config.read_text(encoding="utf-8"), original)
            self.assertEqual(json.loads(report.read_text())["summary"]["existing_failures"], 1)

    @patch("discover_ats_employers.validate_candidate")
    @patch("discover_ats_employers.discover")
    @patch("discover_ats_employers.load_local_environment")
    def test_apply_merges_without_erasing_manual(self, _environment, discover, validate):
        candidate = discovery.Candidate(
            "New Co", "greenhouse", "newco", "https://job-boards.greenhouse.io/newco",
            ["query"])
        discover.return_value = ([candidate], [])
        validate.side_effect = lambda item: {
            **discovery.asdict(item), "company": item.company,
            "validation_status": "valid", "approved": True, "open_job_count": 1,
            "marketing_job_count": 1, "us_job_count": 1, "remote_job_count": 1,
            "relevant_role_examples": ["Growth Marketing Manager"], "relevance_score": 8,
            "rejection_reason": "", "failure_count": 0,
        }
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "sources.json"
            report = Path(directory) / "report.json"
            config.write_text(json.dumps(self.config), encoding="utf-8")
            args = argparse.Namespace(dry_run=False, apply=True, refresh=False,
                                      platform=["greenhouse"], limit=None,
                                      config=config, report=report,
                                      seeds=Path(directory) / "missing-seeds.json")
            discovery.run(args)
            companies = json.loads(config.read_text())["providers"]["greenhouse"]["companies"]
        self.assertEqual({item["token"] for item in companies}, {"manual", "newco"})

    def test_jooble_enabled_is_rejected(self):
        self.config["providers"]["jooble"]["enabled"] = True
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "sources.json"
            config.write_text(json.dumps(self.config), encoding="utf-8")
            args = argparse.Namespace(dry_run=True, apply=False, refresh=False,
                                      platform=None, limit=1, config=config,
                                      report=Path(directory) / "report.json",
                                      seeds=Path(directory) / "missing-seeds.json")
            with self.assertRaisesRegex(ValueError, "Jooble cannot be enabled"):
                discovery.run(args)


if __name__ == "__main__":
    unittest.main()
