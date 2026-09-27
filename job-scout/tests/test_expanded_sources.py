"""Offline parser, configuration, and cross-source behavior tests."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deduplicate import find_duplicate
from models import RawListing
from normalize import canonicalize_url, normalize
from sources.ats import AshbyProvider, GreenhouseProvider, LeverProvider, WorkableProvider
from sources.base import ProviderError, SearchRequest
from sources.config import load_source_config
from sources.http import FetchedDocument
from sources.jobicy import JobicyProvider
from sources.remoteok import RemoteOkProvider
from sources.search_discovery import SearchDiscoveryProvider
from sources.themuse import TheMuseProvider
from sources.usajobs import UsaJobsProvider
from sources.weworkremotely import WeWorkRemotelyProvider
from storage import JobStore


class ApiProviderTests(unittest.TestCase):
    @patch("sources.jobicy.get_json")
    def test_jobicy_maps_optional_salary_and_metadata(self, mocked):
        mocked.return_value = {"jobs": [{
            "id": 10, "url": "https://jobicy.test/10", "jobTitle": "Paid Search Manager",
            "companyName": "Acme", "jobGeo": "USA", "jobDescription": "Lead PPC.",
            "jobType": ["full-time"], "jobIndustry": ["Marketing"],
            "salaryMin": 90000, "salaryMax": 120000, "salaryCurrency": "USD",
            "salaryPeriod": "yearly", "pubDate": "2026-09-20",
        }]}
        jobs = list(JobicyProvider().full_feed())
        self.assertEqual((jobs[0].source, jobs[0].source_job_id), ("jobicy", "10"))
        self.assertEqual(jobs[0].salary, "USD 90000 - 120000 per yearly")
        self.assertEqual(jobs[0].tags, ["Marketing"])

    @patch("sources.remoteok.get_json_value")
    def test_remoteok_skips_metadata_row_and_missing_optional_fields(self, mocked):
        mocked.return_value = [{"legal": "terms"}, {
            "id": "r1", "url": "https://remoteok.test/r1", "position": "SEM Manager",
            "company": "Remote Co", "description": "Own search", "tags": ["marketing"],
        }]
        jobs = list(RemoteOkProvider().full_feed())
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source, "remoteok")
        self.assertEqual(jobs[0].location, "Remote")

    @patch("sources.remoteok.get_json_value", return_value={"jobs": []})
    def test_remoteok_rejects_malformed_root(self, _mocked):
        with self.assertRaisesRegex(ProviderError, "unexpected response"):
            list(RemoteOkProvider().full_feed())

    def test_usajobs_missing_credentials_is_explicit(self):
        provider = UsaJobsProvider(api_key="", email="")
        self.assertFalse(provider.configured())
        with self.assertRaisesRegex(ProviderError, "USAJOBS_API_KEY"):
            list(provider.search(SearchRequest("marketing")))

    @patch("sources.usajobs.get_json")
    def test_usajobs_maps_official_search_result(self, mocked):
        mocked.return_value = {"SearchResult": {"SearchResultItems": [{
            "MatchedObjectId": "123", "MatchedObjectDescriptor": {
                "PositionID": "MKT-123", "PositionTitle": "Marketing Specialist",
                "PositionURI": "https://www.usajobs.gov/job/123",
                "OrganizationName": "Agency", "PositionLocationDisplay": "Remote",
                "PositionRemuneration": [{"MinimumRange": "80000", "MaximumRange": "100000"}],
                "PositionSchedule": ["Full-time"], "PublicationStartDate": "2026-09-20",
                "UserArea": {"Details": {"JobSummary": "Lead digital communications",
                                           "RemoteIndicator": True}},
            },
        }]}}
        job = list(UsaJobsProvider("key", "me@example.com").search(
            SearchRequest("marketing", "Remote")))[0]
        self.assertEqual(job.source, "usajobs")
        self.assertEqual(job.salary, "$80,000 - $100,000")
        self.assertEqual(job.remote_type, "remote")

    @patch("sources.themuse.get_json", return_value={"results": []})
    def test_themuse_empty_response_is_valid(self, _mocked):
        self.assertEqual(list(TheMuseProvider("key").search(SearchRequest("marketing"))), [])


class AtsProviderTests(unittest.TestCase):
    @patch("sources.ats.get_json")
    def test_greenhouse_parser(self, mocked):
        mocked.return_value = {"jobs": [{
            "id": 1, "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            "title": "Paid Media Manager", "location": {"name": "Remote"},
            "content": "Lead media", "updated_at": "2026-09-20",
        }]}
        job = list(GreenhouseProvider([{"name": "Acme", "token": "acme"}]).full_feed())[0]
        self.assertEqual((job.source, job.company), ("greenhouse", "Acme"))
        self.assertEqual(job.remote_type, "remote")

    @patch("sources.ats.get_json")
    def test_lever_parser(self, mocked):
        mocked.return_value = [{
            "id": "lev1", "hostedUrl": "https://jobs.lever.co/acme/lev1",
            "text": "Growth Marketing Manager", "descriptionPlain": "Lead growth",
            "categories": {"location": "Remote", "commitment": "Full-time", "team": "Marketing"},
            "workplaceType": "remote",
        }]
        job = list(LeverProvider([{"name": "Acme", "site": "acme"}]).full_feed())[0]
        self.assertEqual(job.source, "lever")
        self.assertEqual(job.category, "Marketing")

    @patch("sources.ats.get_json")
    def test_ashby_parser(self, mocked):
        mocked.return_value = {"jobs": [{
            "id": "ash1", "jobUrl": "https://jobs.ashbyhq.com/acme/ash1",
            "title": "Marketing Analytics Manager", "location": "USA",
            "descriptionHtml": "Analyze marketing", "isRemote": True,
            "employmentType": "FullTime", "publishedAt": "2026-09-20",
            "compensation": {"compensationTierSummary": "$100k-$120k"},
        }]}
        job = list(AshbyProvider([{"name": "Acme", "board": "acme"}]).full_feed())[0]
        self.assertEqual(job.source, "ashby")
        self.assertEqual(job.salary, "$100k-$120k")

    @patch("sources.ats.get_json")
    def test_workable_parser(self, mocked):
        mocked.return_value = {"jobs": [{
            "shortcode": "WK1", "url": "https://apply.workable.com/acme/j/WK1",
            "title": "Digital Marketing Manager", "description": "Own digital",
            "location": {"location_str": "Lehi, UT", "workplace_type": "hybrid"},
            "salary": {"salary_from": 90000, "salary_to": 110000, "salary_currency": "usd"},
        }]}
        job = list(WorkableProvider([{"name": "Acme", "account": "acme"}]).full_feed())[0]
        self.assertEqual(job.source, "workable")
        self.assertEqual(job.salary, "USD 90000 - 110000")
        self.assertEqual(job.remote_type, "hybrid")

    @patch("sources.ats.get_json", side_effect=ProviderError("one board failed"))
    def test_ats_board_failure_is_reported(self, _mocked):
        with self.assertRaisesRegex(ProviderError, "Every configured greenhouse employer failed"):
            list(GreenhouseProvider([{"name": "Acme", "token": "acme"}]).full_feed())


class FeedAndDiscoveryTests(unittest.TestCase):
    @patch("sources.weworkremotely.get_bytes")
    def test_weworkremotely_official_rss(self, mocked):
        mocked.return_value = b'''<rss><channel><item><title>Acme: PPC Manager</title>
        <link>https://weworkremotely.com/remote-jobs/acme-ppc</link>
        <description>Own paid search</description><region>USA</region>
        <pubDate>Sun, 20 Sep 2026 10:00:00 +0000</pubDate></item></channel></rss>'''
        job = list(WeWorkRemotelyProvider().full_feed())[0]
        self.assertEqual((job.source, job.company, job.title),
                         ("weworkremotely", "Acme", "PPC Manager"))

    @patch("sources.search_discovery.get_document")
    @patch("sources.search_discovery.get_json")
    def test_search_discovery_preserves_specific_source_label(self, search, fetch):
        search.return_value = {"web": {"results": [{"url": "https://linkedin.com/jobs/view/1"}]}}
        payload = {"@type": "JobPosting", "title": "Paid Search Manager",
                   "description": "Own PPC", "hiringOrganization": {"name": "Acme"},
                   "url": "https://linkedin.com/jobs/view/1"}
        fetch.return_value = FetchedDocument(
            ("<script type='application/ld+json'>" + json.dumps(payload) + "</script>").encode(),
            "https://linkedin.com/jobs/view/1", "text/html",
        )
        job = list(SearchDiscoveryProvider("linkedin", "site:linkedin.com/jobs/view", "key").search(
            SearchRequest("paid search", "Remote")))[0]
        self.assertEqual(job.source, "linkedin")
        self.assertEqual(job.metadata["_discovered_via"], "brave")

    @patch("sources.search_discovery.get_document")
    @patch("sources.search_discovery.get_json")
    def test_search_discovery_skips_off_domain_results(self, search, fetch):
        search.return_value = {"web": {"results": [{"url": "https://example.test/jobs/1"}]}}
        provider = SearchDiscoveryProvider("linkedin", "site:linkedin.com/jobs/view", "key")
        self.assertEqual(list(provider.search(SearchRequest("marketing", "Remote"))), [])
        fetch.assert_not_called()
        self.assertEqual(provider.errors[0]["error"], "off-domain discovery result skipped")


class ConfigurationAndDedupTests(unittest.TestCase):
    def test_source_enable_disable_and_jooble_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sources.json"
            path.write_text(json.dumps({"providers": {
                "adzuna": {"enabled": False}, "jooble": {"enabled": False},
            }}), encoding="utf-8")
            config = load_source_config(path)
            self.assertFalse(config["providers"]["adzuna"]["enabled"])
            path.write_text(json.dumps({"providers": {"jooble": {"enabled": True}}}),
                            encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Jooble cannot be enabled"):
                load_source_config(path)

    def test_canonical_url_removes_tracking_and_sorts_identity_params(self):
        left = canonicalize_url("https://example.test/job?b=2&utm_term=x&a=1&ref=mail")
        right = canonicalize_url("https://example.test/job?a=1&b=2")
        self.assertEqual(left, right)

    def test_exact_cross_source_identity_deduplicates_and_direct_ats_wins(self):
        aggregator = normalize(RawListing(
            "indeed", "i1", "https://indeed.com/viewjob?jk=i1", "Paid Search Manager",
            "Acme, Inc.", "Salt Lake City, UT", "Short aggregator copy",
        ))
        direct = normalize(RawListing(
            "greenhouse", "g1", "https://boards.greenhouse.io/acme/jobs/g1",
            "Paid Search Manager", "Acme Inc", "Salt Lake City UT",
            "Different direct employer description",
        ))
        aggregator.id = 1
        self.assertEqual(find_duplicate(direct, [aggregator]).id, 1)
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                job_id = store.save(aggregator)
                store.merge(job_id, direct)
                saved = store.get(job_id)
        self.assertEqual(saved.source, "greenhouse")
        self.assertEqual(saved.url, direct.url)
        self.assertEqual({link["source"] for link in saved.source_links}, {"indeed", "greenhouse"})


if __name__ == "__main__":
    unittest.main()
