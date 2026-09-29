from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "job-scout"))
sys.path.insert(0, str(ROOT / "job-scout/tests"))

from check_job_links import (  # noqa: E402
    CheckResult,
    FetchResult,
    _classify_job_fetch,
    _generic_removed_redirect,
    check_company_website,
    check_job_url,
    process_google_tracker,
)
from google_tracker import Config, GoogleTracker  # noqa: E402
from test_google_tracker import FakeSheets, SCOUT  # noqa: E402


class ClassificationTests(unittest.TestCase):
    def test_dead_and_unknown_rules_are_conservative(self):
        self.assertEqual(
            _classify_job_fetch("https://jobs.test/1", FetchResult("x", "x", 404)).status,
            "removed",
        )
        self.assertEqual(
            _classify_job_fetch("https://jobs.test/1", FetchResult("x", "x", 403)).status,
            "unknown",
        )
        self.assertEqual(
            _classify_job_fetch(
                "https://jobs.test/1", FetchResult("x", "x", 200, "This job is no longer available")
            ).status,
            "removed",
        )
        self.assertEqual(
            _classify_job_fetch(
                "https://jobs.test/1", FetchResult("x", "x", 200, "Checking your browser - Cloudflare")
            ).status,
            "unknown",
        )

    def test_indeed_generic_redirect_is_removed(self):
        self.assertTrue(_generic_removed_redirect(
            "https://www.indeed.com/viewjob?jk=abc123", "https://www.indeed.com/jobs"
        ))
        self.assertFalse(_generic_removed_redirect(
            "https://www.indeed.com/viewjob?jk=abc123",
            "https://www.indeed.com/viewjob?jk=abc123",
        ))
        self.assertTrue(_generic_removed_redirect(
            "https://careers.example.com/jobs/paid-search-manager",
            "https://careers.example.com/careers",
        ))

    def test_resolved_domain_with_ssl_problem_counts_as_existing(self):
        fetcher = type("Fetcher", (), {
            "fetch": lambda self, url: FetchResult(url, error_kind="ssl", reason="certificate")
        })()
        with patch("check_job_links.host_is_public", return_value=("public", "203.0.113.1")):
            result = check_company_website("https://example.test", fetcher)
        self.assertEqual(result.status, "exists")

    def test_nxdomain_is_no_website(self):
        fetcher = type("Fetcher", (), {"fetch": lambda self, url: None})()
        with patch(
            "check_job_links.host_is_public",
            return_value=("nonexistent", "DNS reports that example.test does not exist"),
        ):
            result = check_company_website("https://example.test", fetcher)
        self.assertEqual(result.status, "removed")

    def test_temporary_job_failure_is_retried_once(self):
        class Fetcher:
            def __init__(self):
                self.results = [
                    FetchResult("x", error_kind="timeout", reason="timed out"),
                    FetchResult("x", "https://jobs.example.test/1", 200, "Paid Search Manager"),
                ]

            def fetch(self, _url):
                return self.results.pop(0)

        fetcher = Fetcher()
        with patch("check_job_links.validate_public_url", return_value=None):
            result = check_job_url("https://jobs.example.test/1", fetcher, retries=1)
        self.assertEqual(result.status, "exists")
        self.assertEqual(fetcher.results, [])


class GoogleSheetPreservationTests(unittest.TestCase):
    def test_only_notes_change(self):
        fake = FakeSheets()
        fake.data["Job Scout"] = [SCOUT]
        for scout_id, company, url, notes in (
            (1, "Acme", "https://jobs.test/removed", "Recruiter contacted"),
            (2, "Example", "https://jobs.test/exists", ""),
            (3, "Blocked", "https://jobs.test/unknown", "Keep this"),
        ):
            row = [""] * len(SCOUT)
            for field, value in {"Scout ID": scout_id, "Company": company,
                                 "Job URL": url, "Notes": notes}.items():
                row[SCOUT.index(field)] = value
            fake.data["Job Scout"].append(row)
        tracker = GoogleTracker(Config("test", Path("unused.json"), "Job Tracker", "Job Scout"), fake)

        job_results = {
            "https://jobs.test/removed": CheckResult("removed", "", reason="HTTP 404"),
            "https://jobs.test/exists": CheckResult("exists", ""),
            "https://jobs.test/unknown": CheckResult("unknown", "", reason="HTTP 403"),
        }
        summary = process_google_tracker(
            tracker,
            job_checker=lambda url: job_results[url],
            website_checker=lambda url: CheckResult("unknown", url),
            project_lookup=None,
            progress=lambda _message: None,
        )

        rows = {int(data[0]): dict(zip(SCOUT, data)) for data in fake.data["Job Scout"][1:]}
        self.assertEqual(rows[1]["Notes"], "Recruiter contacted\nDoesn't exist")
        self.assertEqual(rows[2]["Notes"], "")
        self.assertEqual(rows[3]["Notes"], "Keep this")
        self.assertEqual((summary.jobs_removed, summary.jobs_existing, summary.job_status_unknown), (1, 1, 1))
        self.assertEqual([(tab, row, col) for tab, row, col in fake.writes],
                         [("Job Scout", 2, "I")])


if __name__ == "__main__":
    unittest.main()
