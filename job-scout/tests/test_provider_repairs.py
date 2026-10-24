import json
import os
from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources.base import ProviderError, SearchRequest
from sources.firecrawl import FirecrawlClient
from sources.http import FetchedDocument
from sources.search_discovery import SearchDiscoveryProvider
from sources.web import WebCareerProvider
from sources.ats import LeverProvider
from sources.remote_careers import RemoteCareersProvider


def document():
    item = {"@type": "JobPosting", "title": "Marketing Manager",
            "hiringOrganization": {"name": "Remote"}, "description": "Complete posting text",
            "identifier": "job-1", "jobLocationType": "TELECOMMUTE"}
    return '<script type="application/ld+json">' + json.dumps(item) + '</script>'


class ProviderRepairTests(unittest.TestCase):
    def client(self):
        from firecrawl_state import History, config, utcnow
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        settings = config(); settings['enabled'] = True
        history = History(Path(directory.name) / 'firecrawl.sqlite', settings)
        history.record_balance({'remainingCredits': 5000}, now=utcnow())
        return FirecrawlClient(history=history, settings=settings)

    @patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-secret"})
    @patch("sources.firecrawl.post_json")
    def test_public_html_is_cached_and_uses_basic_proxy(self, post):
        post.return_value = {"success": True, "data": {"rawHtml": document(), "metadata": {"statusCode": 200}}}
        client = self.client()
        self.assertEqual(client.document("https://example.com/job").body.decode(), document())
        client.document("https://example.com/job")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[1]["proxy"], "basic")
        self.assertEqual(post.call_args.args[1]["maxAge"], 86400000)
        self.assertEqual(post.call_args.args[1]['parsers'], [])

    @patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-secret"})
    @patch("sources.firecrawl.post_json", side_effect=ProviderError("Firecrawl HTTP 402"))
    def test_payment_failure_stops_repeated_requests(self, post):
        client = self.client()
        for number in range(3):
            with self.assertRaises(ProviderError):
                client.document(f"https://example.com/{number}")
        self.assertEqual(post.call_count, 1)

    @patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-secret"})
    @patch("sources.firecrawl.post_json")
    def test_failed_page_is_not_a_valid_document(self, post):
        post.return_value = {"success": True, "data": {"rawHtml": "Denied", "metadata": {"statusCode": 403}}}
        with self.assertRaisesRegex(ProviderError, "403"):
            self.client().document("https://example.com/job")

    @patch("sources.web.get_bytes", side_effect=ProviderError("HTTP Error 404"))
    def test_expired_individual_pages_are_excluded_and_cached(self, fetch):
        provider = WebCareerProvider()
        with patch.object(provider, "_result_urls", return_value=["https://example.com/expired"]), patch.object(type(provider), "backends", new_callable=lambda: property(lambda self: ["brave"])):
            list(provider.search(SearchRequest("marketing")))
            list(provider.search(SearchRequest("paid search")))
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(provider.errors)
        self.assertEqual(len(provider.exclusions), 2)

    @patch("sources.ats.get_json")
    def test_shared_lever_board_only_returns_oxylabs_team(self, fetch):
        fetch.return_value = [
            {"id": "1", "text": "Marketing", "categories": {"team": "Oxylabs"}},
            {"id": "2", "text": "Marketing", "categories": {"team": "Other"}},
        ]
        jobs = LeverProvider().fetch_company({"name": "Oxylabs", "site": "source.ai", "team": "Oxylabs"})
        self.assertEqual([job.source_job_id for job in jobs], ["1"])

    @patch("sources.remote_careers.get_document")
    def test_remote_feed_uses_employer_links_and_complete_schema(self, fetch):
        url = "https://apply.remote.com/jobs/010651de-9f5a-4443-9248-56bb8a2f6dc7"
        fetch.return_value = FetchedDocument(url.encode(), "https://remote.com/openings", "text/html")
        with patch.object(RemoteCareersProvider, "document", return_value=FetchedDocument(document().encode(), url, "text/html")):
            jobs = list(RemoteCareersProvider().full_feed())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source, "remote-careers")
        self.assertEqual(jobs[0].company, "Remote")

    def test_search_snippets_never_become_jobs(self):
        provider = SearchDiscoveryProvider("test", "site:example.com", "key")
        jobs = list(provider.extract(FetchedDocument(b"Search snippet", "https://example.com/job", "text/html"), "https://example.com/job"))
        self.assertEqual(jobs, [])
        self.assertTrue(provider.errors)


if __name__ == "__main__":
    unittest.main()
