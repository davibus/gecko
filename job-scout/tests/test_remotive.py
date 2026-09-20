from __future__ import annotations

import sys
import tempfile
import unittest
import argparse
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCOUT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCOUT_ROOT))

from models import RawListing
from normalize import normalize
from preferences import load_preferences
from scout import diagnose_remotive, search
from service import SearchSummary, discover_remotive_full_feed
from sources.base import ProviderError, SearchRequest
from sources.remotive import RemotiveProvider
from storage import JobStore


REMOTIVE_JOB = {
    "id": 123456,
    "url": "https://remotive.com/remote-jobs/marketing/paid-search-manager-123456",
    "title": "Paid Search Manager",
    "company_name": "Example Co",
    "category": "Marketing",
    "job_type": "full_time",
    "publication_date": "2026-09-17T14:30:00",
    "candidate_required_location": "USA",
    "salary": "$100,000 - $120,000",
    "description": "<p>Own Google Ads, paid search, and analytics.</p>",
    "tags": ["PPC", "Analytics"],
}


class RemotiveProviderTests(unittest.TestCase):
    @patch("sources.remotive.get_json")
    def test_maps_public_api_response_with_attribution_url_and_publication_date(self, mocked_get):
        mocked_get.return_value = {"job-count": 1, "jobs": [REMOTIVE_JOB]}
        provider = RemotiveProvider()

        jobs = list(provider.search(SearchRequest("paid search", "Remote", results_per_page=5)))

        self.assertTrue(provider.configured())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source, "remotive")
        self.assertEqual(jobs[0].source_job_id, "123456")
        self.assertEqual(jobs[0].url, REMOTIVE_JOB["url"])
        self.assertEqual(jobs[0].date_posted, "2026-09-17T14:30:00")
        self.assertEqual(jobs[0].remote_type, "remote")
        normalized = normalize(jobs[0])
        self.assertEqual(normalized.date_posted, "2026-09-17")
        self.assertEqual(normalized.category, "Marketing")
        self.assertEqual(normalized.tags, ["PPC", "Analytics"])
        self.assertEqual(normalized.location, "USA")
        self.assertEqual(normalized.salary, "$100,000 - $120,000")
        self.assertEqual(normalized.url, REMOTIVE_JOB["url"])
        mocked_get.assert_called_once_with("https://remotive.com/api/remote-jobs")

    @patch("sources.remotive.get_json")
    def test_fetches_feed_once_across_multiple_scout_requests(self, mocked_get):
        mocked_get.return_value = {"jobs": [REMOTIVE_JOB]}
        provider = RemotiveProvider()

        list(provider.search(SearchRequest("paid search", "Utah")))
        list(provider.search(SearchRequest("analytics", "Remote")))

        mocked_get.assert_called_once()

    @patch("sources.remotive.get_json")
    def test_full_feed_returns_every_job_without_query_filtering(self, mocked_get):
        unrelated = {
            **REMOTIVE_JOB,
            "id": 999999,
            "url": "https://remotive.com/remote-jobs/software-dev/backend-engineer-999999",
            "title": "Backend Engineer",
            "description": "Build distributed APIs in Go.",
            "category": "Software Development",
            "tags": ["Go", "APIs"],
        }
        mocked_get.return_value = {"jobs": [REMOTIVE_JOB, unrelated]}
        provider = RemotiveProvider()

        jobs = list(provider.full_feed())

        self.assertEqual([job.source_job_id for job in jobs], ["123456", "999999"])
        self.assertEqual(jobs[1].title, "Backend Engineer")
        self.assertEqual(jobs[1].source, "remotive")
        self.assertEqual(jobs[1].url, unrelated["url"])
        mocked_get.assert_called_once()

    @patch("sources.remotive.get_json", return_value={"jobs": "unexpected"})
    def test_rejects_invalid_jobs_payload(self, _mocked_get):
        with self.assertRaisesRegex(ProviderError, "unexpected jobs payload"):
            list(RemotiveProvider().search(SearchRequest("marketing")))

    @patch("sources.remotive.get_json", return_value=[])
    def test_rejects_malformed_top_level_response(self, _mocked_get):
        with self.assertRaisesRegex(ProviderError, "unexpected response payload"):
            list(RemotiveProvider().search(SearchRequest("marketing")))

    @patch("sources.remotive.get_json", side_effect=ProviderError("HTTP 503"))
    def test_propagates_failed_api_request(self, _mocked_get):
        with self.assertRaisesRegex(ProviderError, "HTTP 503"):
            list(RemotiveProvider().search(SearchRequest("marketing")))

    @patch("sources.remotive.get_json", return_value={"jobs": [REMOTIVE_JOB]})
    def test_zero_result_search_is_successful(self, _mocked_get):
        provider = RemotiveProvider()
        self.assertEqual(list(provider.search(SearchRequest("quantum veterinarian"))), [])
        self.assertEqual(provider.raw_count, 1)

    @patch("sources.remotive.get_json")
    def test_applies_page_and_result_limit_locally(self, mocked_get):
        mocked_get.return_value = {
            "jobs": [{**REMOTIVE_JOB, "id": number, "url": f"https://remotive.com/jobs/{number}"}
                     for number in range(1, 6)]
        }

        jobs = list(RemotiveProvider().search(
            SearchRequest("paid search", page=2, results_per_page=2)
        ))

        self.assertEqual([job.source_job_id for job in jobs], ["3", "4"])

    def test_cross_provider_duplicate_keeps_remotive_attribution_link(self):
        adzuna = normalize(RawListing(
            source="Adzuna", source_job_id="adzuna-1",
            url="https://adzuna.example/jobs/1", title="Paid Search Manager",
            company="Example Co", location="Remote - USA",
            description="Own Google Ads paid search analytics and reporting.",
        ))
        remotive = normalize(RawListing(
            source="remotive", source_job_id="123456", url=REMOTIVE_JOB["url"],
            title="Paid Search Manager", company="Example Co", location="USA",
            description="Own Google Ads paid search analytics and reporting.",
            date_posted=REMOTIVE_JOB["publication_date"], remote_type="remote",
        ))

        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                job_id = store.save(adzuna)
                store.merge(job_id, remotive)
                saved = store.get(job_id)

        remotive_links = [link for link in saved.source_links if link["source"] == "remotive"]
        self.assertEqual(len(remotive_links), 1)
        self.assertEqual(remotive_links[0]["url"], REMOTIVE_JOB["url"])

    def test_normalized_category_and_tags_survive_storage(self):
        job = normalize(RawListing(
            source="remotive", source_job_id="123456", url=REMOTIVE_JOB["url"],
            title="Paid Search Manager", company="Example Co", location="USA",
            description="Own paid search analytics.", category="Marketing",
            tags=["PPC", "Analytics"],
        ))
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                saved_id = store.save(job)
                saved = store.get(saved_id)
        self.assertEqual(saved.category, "Marketing")
        self.assertEqual(saved.tags, ["PPC", "Analytics"])

    @patch("sources.remotive.get_json")
    def test_full_feed_scores_and_retains_below_threshold_jobs(self, mocked_get):
        unrelated = {
            **REMOTIVE_JOB,
            "id": 999999,
            "url": "https://remotive.com/remote-jobs/software-dev/backend-engineer-999999",
            "title": "Backend Engineer",
            "description": "Build distributed APIs in Go.",
            "category": "Software Development",
            "tags": ["Go", "APIs"],
        }
        mocked_get.return_value = {"jobs": [REMOTIVE_JOB, unrelated]}
        provider = RemotiveProvider()

        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                summary = discover_remotive_full_feed(
                    provider, store, load_preferences(), "paid search analytics",
                )
                saved = store.all(retained_only=True)
                rerun = discover_remotive_full_feed(
                    provider, store, load_preferences(), "paid search analytics",
                )

        self.assertEqual(summary.raw_retrieved, 2)
        self.assertEqual(summary.normalized, 2)
        self.assertEqual(summary.scored, 2)
        self.assertEqual(summary.added, 2)
        self.assertEqual(summary.updated, 0)
        self.assertEqual(len(saved), 2)
        self.assertTrue(any(job.match_score < 80 for job in saved))
        self.assertEqual({job.source for job in saved}, {"remotive"})
        self.assertEqual({job.url for job in saved}, {REMOTIVE_JOB["url"], unrelated["url"]})
        self.assertEqual(rerun.added, 0)
        self.assertEqual(rerun.updated, 2)
        self.assertEqual(rerun.duplicates, 2)


class RemotiveDiagnosticTests(unittest.TestCase):
    def test_diagnostic_uses_only_remotive_and_reports_all_stages(self):
        class FakeRemotive:
            endpoint = "https://remotive.com/api/remote-jobs"
            raw_count = 3

            def search(self, request):
                self.last_request = request
                yield RawListing(
                    source="remotive", source_job_id="123456", url=REMOTIVE_JOB["url"],
                    title="Paid Search Manager", company="Example Co", location="USA",
                    description="Own Google Ads, PPC, paid search, and marketing analytics.",
                    category="Marketing", tags=["PPC", "Analytics"], remote_type="remote",
                )

        args = argparse.Namespace(
            query=["paid search"], results=100, minimum_score=0, examples=5,
        )
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                output = io.StringIO()
                with patch("scout.RemotiveProvider", return_value=FakeRemotive()), \
                     patch("scout.extract_resume_text", return_value="paid search analytics"), \
                     patch("scout.providers", side_effect=AssertionError("other providers must not run")), \
                     redirect_stdout(output):
                    result = diagnose_remotive(args, store, load_preferences())
        report = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(report["provider"], "remotive")
        self.assertEqual(report["raw_retrieved"], 3)
        self.assertEqual(report["query_matches"], 1)
        self.assertEqual(report["matched_gecko_filters"], 1)
        self.assertEqual(report["survived_deduplication"], 1)
        self.assertEqual(report["source_counts"], {"remotive": 1})

    def test_failed_remotive_run_logs_warning_and_nonzero_status(self):
        class FailedRemotive:
            name = "remotive"

            def configured(self):
                return True

            def full_feed(self):
                raise ProviderError("API unavailable")
                yield  # pragma: no cover

        args = argparse.Namespace(
            source="remotive", query=["PPC"], location=["Remote"], page=1,
            results=20, minimum_score=80, tracker="unused.xlsx",
        )
        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store, \
                 patch("scout.providers", return_value={"remotive": FailedRemotive()}), \
                 patch("scout.extract_resume_text", return_value=""), \
                 redirect_stdout(stdout), redirect_stderr(stderr):
                result = search(args, store, load_preferences())
        report = json.loads(stdout.getvalue())
        self.assertEqual(result, 1)
        self.assertEqual(report["source_counts"], {"remotive": 0})
        self.assertIn("remotive", report["source_errors"])
        self.assertIn("Warning: remotive provider failed: API unavailable", stderr.getvalue())

    def test_successful_run_includes_remotive_source_count(self):
        args = argparse.Namespace(
            source="remotive", query=["PPC"], location=["Remote"], page=1,
            results=20, minimum_score=80, tracker="unused.xlsx",
        )
        provider = type("Provider", (), {"name": "remotive", "configured": lambda self: True})()
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store, \
                 patch("scout.providers", return_value={"remotive": provider}), \
                 patch("scout.extract_resume_text", return_value=""), \
                 patch("scout.discover_remotive_full_feed", return_value=SearchSummary(
                     raw_retrieved=20, fetched=8, normalized=8, scored=8,
                 )), \
                 patch("scout.discover", side_effect=AssertionError("query discovery must not run")), \
                 patch("scout.sync_tracker"), redirect_stdout(output):
                result = search(args, store, load_preferences())
        report = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(report["source_counts"], {"remotive": 8})
        self.assertEqual(report["raw_retrieved"], 20)
        self.assertEqual(report["normalized"], 8)
        self.assertEqual(report["scored"], 8)


if __name__ == "__main__":
    unittest.main()
