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
from scout import diagnose_remotive, diagnose_remotive_feeds, diagnose_remotive_rss, search
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

REMOTIVE_RSS = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0"><channel>
  <item>
    <title>Paid Search Manager</title><jobId>123456</jobId>
    <company>Example Co</company><location>USA</location><type>full_time</type>
    <guid>https://remotive.com/remote-jobs/marketing/paid-search-manager-123456</guid>
    <link>https://remotive.com/remote-jobs/marketing/paid-search-manager-123456</link>
    <pubDate>Thu, 17 Sep 2026 14:30:00 GMT</pubDate><dc:creator>Example Co</dc:creator>
    <category>Marketing</category><category>PPC</category>
    <salary>$100,000 - $120,000</salary>
    <description><![CDATA[<p>Own Google Ads, paid search, and analytics.</p>]]></description>
  </item>
  <item>
    <title>Backend Engineer</title><jobId>999999</jobId>
    <company>Code Co</company><location>Worldwide</location><type>contract</type>
    <link>https://remotive.com/remote-jobs/software-dev/backend-engineer-999999</link>
    <pubDate>Fri, 18 Sep 2026 10:00:00 GMT</pubDate>
    <category>Software Development</category>
    <description><![CDATA[<p>Build distributed APIs in Go.</p>]]></description>
  </item>
</channel></rss>'''

REMOTIVE_SALES_RSS = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Paid Search Manager</title><jobId>123456</jobId>
    <company>Example Co</company><location>USA</location><type>full_time</type>
    <link>https://remotive.com/remote-jobs/marketing/paid-search-manager-123456?utm_source=rss</link>
    <pubDate>Thu, 17 Sep 2026 14:30:00 GMT</pubDate>
    <category>Revenue</category><description>Own paid media and sales analytics.</description>
  </item>
  <item>
    <title>Account Executive</title><jobId>777777</jobId>
    <company>Sales Co</company><location>Worldwide</location>
    <link>https://remotive.com/remote-jobs/sales/account-executive-777777</link>
    <description>Own enterprise sales.</description>
  </item>
</channel></rss>'''


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
        self.assertEqual(normalized.tags, ["Marketing", "PPC", "Analytics"])
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

    @patch("sources.remotive.get_bytes")
    def test_multiple_category_feeds_deduplicate_and_preserve_provenance(self, mocked_get):
        provider = RemotiveProvider()
        provider.category_feeds = (
            ("Marketing", "https://remotive.test/marketing"),
            ("Sales", "https://remotive.test/sales"),
        )
        mocked_get.side_effect = lambda url, headers=None: (
            REMOTIVE_RSS if url.endswith("marketing") else REMOTIVE_SALES_RSS
        )

        jobs = list(provider.full_feed())
        repeated = list(provider.full_feed())

        self.assertEqual([job.source_job_id for job in jobs], ["123456", "999999", "777777"])
        self.assertEqual(jobs[1].title, "Backend Engineer")
        self.assertEqual(jobs[1].source, "remotive")
        self.assertEqual(jobs[1].url, "https://remotive.com/remote-jobs/software-dev/backend-engineer-999999")
        self.assertEqual(jobs[0].company, "Example Co")
        self.assertEqual(jobs[0].location, "USA")
        self.assertEqual(jobs[0].employment_type, "full_time")
        self.assertEqual(jobs[0].salary, "$100,000 - $120,000")
        self.assertEqual(jobs[0].category, "Marketing")
        self.assertEqual(jobs[0].tags, ["Marketing", "PPC", "Sales", "Revenue"])
        self.assertEqual(jobs[0].metadata["feed_categories"], ["Marketing", "Sales"])
        self.assertEqual(jobs[0].date_posted[:10], "2026-09-17")
        self.assertEqual(repeated, jobs)
        self.assertEqual(provider.active_source, "category-rss")
        self.assertEqual(provider.rss_raw_count, 4)
        self.assertEqual(provider.rss_count, 3)
        self.assertEqual(provider.rss_duplicate_count, 1)
        self.assertEqual(provider.successful_feed_count, 2)
        self.assertEqual(mocked_get.call_count, 2)

    @patch("sources.remotive.get_json", side_effect=AssertionError("API must not run"))
    @patch("sources.remotive.get_bytes")
    def test_one_category_failure_does_not_abort_or_trigger_api(self, mocked_get, _mocked_json):
        provider = RemotiveProvider()
        provider.category_feeds = (
            ("Marketing", "https://remotive.test/marketing"),
            ("Sales", "https://remotive.test/sales"),
        )
        mocked_get.side_effect = lambda url, headers=None: (
            REMOTIVE_RSS if url.endswith("marketing")
            else (_ for _ in ()).throw(ProviderError("Sales unavailable"))
        )
        jobs = list(provider.full_feed())
        self.assertEqual(len(jobs), 2)
        self.assertEqual(provider.active_source, "category-rss")
        self.assertEqual(provider.successful_feed_count, 1)
        self.assertEqual(provider.failed_feed_count, 1)
        self.assertIn("Sales unavailable", provider.feed_results[1]["error"])

    @patch("sources.remotive.get_json", return_value={"jobs": [REMOTIVE_JOB]})
    @patch("sources.remotive.get_bytes", side_effect=ProviderError("RSS unavailable"))
    def test_full_feed_falls_back_to_cached_api(self, mocked_bytes, mocked_json):
        provider = RemotiveProvider()
        provider.category_feeds = (
            ("Marketing", "https://remotive.test/marketing"),
            ("Sales", "https://remotive.test/sales"),
        )
        first = list(provider.full_feed())
        second = list(provider.full_feed())
        self.assertEqual([job.source_job_id for job in first], ["123456"])
        self.assertEqual(second, first)
        self.assertEqual(provider.active_source, "api-fallback")
        self.assertEqual(provider.rss_count, 0)
        self.assertEqual(provider.api_count, 1)
        self.assertIn("Marketing: RSS unavailable", provider.rss_error)
        self.assertEqual(mocked_bytes.call_count, 2)
        mocked_json.assert_called_once()

    @patch("sources.remotive.get_bytes", return_value=b'''<rss><channel><item>
        <title>Role</title><company>Example</company>
        <link>https://remotive.com/remote-jobs/marketing/role-without-numeric-id</link>
        <description>Details</description>
    </item></channel></rss>''')
    def test_rss_uses_stable_derived_id_when_job_id_is_absent(self, _mocked_get):
        first_provider = RemotiveProvider()
        first_provider.category_feeds = (("Marketing", "https://remotive.test/marketing"),)
        second_provider = RemotiveProvider()
        second_provider.category_feeds = (("Marketing", "https://remotive.test/marketing"),)
        first = first_provider.category_pool()[0]
        second = second_provider.category_pool()[0]
        self.assertTrue(first.source_job_id.startswith("rss-"))
        self.assertEqual(first.source_job_id, second.source_job_id)

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
            category="Marketing", tags=["Marketing", "Sales"],
        ))

        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                job_id = store.save(adzuna)
                store.merge(job_id, remotive)
                saved = store.get(job_id)

        remotive_links = [link for link in saved.source_links if link["source"] == "remotive"]
        self.assertEqual(len(remotive_links), 1)
        self.assertEqual(remotive_links[0]["url"], REMOTIVE_JOB["url"])
        self.assertEqual(saved.tags, ["Marketing", "Sales"])

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

    @patch("sources.remotive.get_bytes", return_value=REMOTIVE_RSS)
    def test_full_feed_scores_and_retains_below_threshold_jobs(self, _mocked_get):
        provider = RemotiveProvider()
        provider.category_feeds = (("Marketing", "https://remotive.test/marketing"),)

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
        self.assertEqual(summary.rss_retrieved, 2)
        self.assertEqual(summary.api_retrieved, 0)
        self.assertEqual(summary.rss_unique, 2)
        self.assertEqual(summary.successful_feeds, 1)
        self.assertEqual(summary.failed_feeds, 0)
        self.assertEqual(summary.source_backend, "category-rss")
        self.assertEqual(summary.normalized, 2)
        self.assertEqual(summary.scored, 2)
        self.assertEqual(summary.added, 2)
        self.assertEqual(summary.updated, 0)
        self.assertEqual(len(saved), 2)
        self.assertTrue(any(job.match_score < 80 for job in saved))
        self.assertEqual({job.source for job in saved}, {"remotive"})
        self.assertEqual({job.url for job in saved}, {
            REMOTIVE_JOB["url"],
            "https://remotive.com/remote-jobs/software-dev/backend-engineer-999999",
        })
        self.assertEqual(rerun.added, 0)
        self.assertEqual(rerun.updated, 2)
        self.assertEqual(rerun.duplicates, 2)


class RemotiveDiagnosticTests(unittest.TestCase):
    def test_feed_diagnostic_compares_category_pool_and_api(self):
        class FakeRemotive:
            api_endpoint = "https://remotive.com/api/remote-jobs"
            feed_results = [{
                "category": "Marketing", "url": "https://remotive.test/marketing",
                "success": True, "jobs": 2, "error": "",
            }]
            successful_feed_count = 1
            failed_feed_count = 0
            rss_raw_count = 2
            rss_duplicate_count = 0

            def category_pool(self):
                return [
                    RawListing("remotive", "1", "https://remotive.com/jobs/1", "One", "A"),
                    RawListing("remotive", "2", "https://remotive.com/jobs/2", "Two", "B"),
                ]

            def api_feed(self):
                yield RawListing("remotive", "2", "https://remotive.com/jobs/2", "Two", "B")
                yield RawListing("remotive", "3", "https://remotive.com/jobs/3", "Three", "C")

        output = io.StringIO()
        with patch("scout.RemotiveProvider", return_value=FakeRemotive()), redirect_stdout(output):
            result = diagnose_remotive_feeds(argparse.Namespace(), None, None)
        report = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(report["raw_rss_records"], 2)
        self.assertEqual(report["unique_rss_jobs"], 2)
        self.assertEqual(report["successful_category_feeds"], 1)
        self.assertEqual(report["api_jobs_retrieved"], 2)
        self.assertEqual(report["shared_source_ids"], 1)

    def test_old_rss_diagnostic_alias_uses_category_diagnostic(self):
        with patch("scout.diagnose_remotive_feeds", return_value=0) as delegated:
            result = diagnose_remotive_rss(argparse.Namespace(), None, None)
        self.assertEqual(result, 0)
        delegated.assert_called_once()

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
