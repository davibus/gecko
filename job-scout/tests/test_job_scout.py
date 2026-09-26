from __future__ import annotations

import sys
import tempfile
import unittest
import os
import json
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit


SCOUT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCOUT_ROOT))

from deduplicate import duplicate_confidence, find_duplicate
from enrichment import enrich_and_store, enrich_listing
from models import RawListing
from normalize import canonicalize_url, normalize
from preferences import load_preferences
from review import build_review_queue, queue_to_json
from role_filter import is_relevant_role
from service import SearchSummary, discover
from sources.base import JobSource, SearchRequest
from sources.base import ProviderError
from sources.http import FetchedDocument
from sources.jooble import JoobleProvider
from sources.web import WebCareerProvider
from storage import JobStore
from handoff import archive_listing
from scout import CORE_PROVIDERS, build_parser, daily, load_local_environment, search


DESCRIPTION = """
We need a manager with 7+ years of experience to lead a team and own Google Ads,
Bing Ads, paid search and PPC. Build reporting with GA4, GTM, SQL, Python,
Tableau and Looker Studio. HubSpot and Magento experience preferred. Bachelor's
degree required. This is a full-time role.
"""


def raw(source="test", source_id="abc", url="https://example.test/jobs/abc?utm_source=x"):
    return RawListing(
        source=source, source_job_id=source_id, url=url,
        title="Paid Search Manager", company="Example Co", location="Remote - Utah",
        description=DESCRIPTION, employment_type="Full-time",
    )


class FakeProvider(JobSource):
    name = "fake"

    def configured(self):
        return True

    def search(self, request):
        yield raw()


class NormalizeTests(unittest.TestCase):
    def test_normalizes_common_contract_and_url(self):
        job = normalize(raw())
        self.assertEqual(job.work_arrangement, "remote")
        self.assertEqual(job.canonical_url, "https://example.test/jobs/abc")
        self.assertEqual(job.source_links[0]["source_job_id"], "abc")

    def test_url_keeps_identity_parameters(self):
        value = canonicalize_url("https://indeed.test/viewjob?jk=123&utm_medium=email")
        self.assertEqual(value, "https://indeed.test/viewjob?jk=123")

    def test_normalizes_adzuna_full_time(self):
        listing = raw()
        listing.employment_type = "full_time"
        self.assertEqual(normalize(listing).employment_type, "full-time")


class EnvironmentTests(unittest.TestCase):
    @staticmethod
    def queue_result():
        return SimpleNamespace(
            snapshot=SimpleNamespace(pending=[], already_created=[]), recovered=0,
            created=0, failures=[], successes=[], exit_code=0,
        )
    def test_local_environment_loads_without_overriding_shell(self):
        name_from_file = "GECKO_TEST_FROM_FILE"
        name_from_shell = "GECKO_TEST_FROM_SHELL"
        old_file = os.environ.pop(name_from_file, None)
        old_shell = os.environ.get(name_from_shell)
        os.environ[name_from_shell] = "shell-value"
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / ".env.local"
                path.write_text(
                    f'{name_from_file}="file-value"\n{name_from_shell}=file-value\n',
                    encoding="utf-8",
                )
                load_local_environment(path)
                self.assertEqual(os.environ[name_from_file], "file-value")
                self.assertEqual(os.environ[name_from_shell], "shell-value")
        finally:
            os.environ.pop(name_from_file, None)
            if old_file is not None:
                os.environ[name_from_file] = old_file
            if old_shell is None:
                os.environ.pop(name_from_shell, None)
            else:
                os.environ[name_from_shell] = old_shell

    def test_search_defaults_to_adzuna_only(self):
        args = build_parser().parse_args(["search"])
        self.assertEqual(args.source, "adzuna")

    def test_provider_alias_rejects_jooble(self):
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["search", "--provider", "jooble"])

    def test_enrich_command_accepts_id_or_provisional_flag(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["enrich", "62"]).job_id, 62)
        self.assertTrue(parser.parse_args(["enrich", "--provisional"]).provisional)

    def test_resolve_url_command_accepts_id_or_bounded_jooble_batch(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["resolve-url", "329"]).job_id, 329)
        batch = parser.parse_args(["resolve-url", "--jooble", "--limit", "5"])
        self.assertTrue(batch.jooble)
        self.assertEqual(batch.limit, 5)

    def test_review_command_options(self):
        args = build_parser().parse_args([
            "review", "--confirmed-only", "--minimum-score", "75", "--limit", "5", "--json",
        ])
        self.assertTrue(args.confirmed_only)
        self.assertEqual(args.minimum_score, 75)
        self.assertEqual(args.limit, 5)
        self.assertTrue(args.json)

    def test_daily_command_defaults(self):
        args = build_parser().parse_args(["daily"])
        self.assertEqual(args.results, 20)
        self.assertEqual(args.minimum_score, 70)
        self.assertEqual(args.limit, 20)
        self.assertFalse(args.dry_run)

    def test_daily_dry_run_uses_temporary_database_and_skips_resume_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "jobs.sqlite3"
            with JobStore(database) as store:
                def fake_search(search_args, target_store, _preferences):
                    job = normalize(raw(source_id="dry-run", url="https://example.test/dry-run"))
                    job.match_score = 90
                    job.evidence_confidence = 80
                    job_id = target_store.save(job)
                    search_args.run_result = {"new_job_ids": [job_id], "fetched": 1}
                    return 0

                args = build_parser().parse_args(["daily", "--dry-run"])
                with (patch("scout.search", side_effect=fake_search),
                      patch("scout.sheet_only_active_jobs", return_value=[]),
                      patch("scout.protected_job_ids", return_value=set()),
                      patch("scout.DailyLinkValidator.check_existing", return_value=[]),
                      patch("scout._daily_resume_runner") as runner,
                      redirect_stdout(io.StringIO())):
                    result = daily(args, store, load_preferences())
                self.assertEqual(store.all(), [])
        self.assertEqual(result, 0)
        runner.assert_not_called()

    def test_daily_search_dry_run_never_synchronizes_google_sheets(self):
        provider = unittest.mock.Mock()
        provider.name = "adzuna"
        provider.configured.return_value = True
        args = SimpleNamespace(
            source="adzuna", query=None, location=None, page=1, results=1,
            minimum_score=None, limit=1, daily_mode=True, link_validator=None,
            dry_run=True,
        )
        store = unittest.mock.Mock()
        store.all.return_value = []
        with (patch("scout.providers", return_value={"adzuna": provider}),
              patch("scout.extract_resume_text", return_value="resume"),
              patch("scout.discover", return_value=SearchSummary()),
              patch("scout.sync_tracker") as sync):
            result = search(args, store, load_preferences())
        self.assertEqual(result, 0)
        sync.assert_not_called()

    def test_core_provider_set_includes_web_careers(self):
        self.assertEqual(
            CORE_PROVIDERS,
            ("adzuna", "remotive", "web-careers"),
        )

    @patch("scout._daily_resume_runner", return_value=queue_result.__func__())
    @patch("scout.search", return_value=0)
    def test_daily_searches_all_core_providers(self, mocked_search, _mocked_runner):
        args = build_parser().parse_args(["daily"])
        daily(args, None, {})
        search_args = mocked_search.call_args.args[0]
        self.assertEqual(search_args.source, "core")

    def test_daily_invokes_web_careers_provider(self):
        class StubProvider:
            def __init__(self, name):
                self.name = name
                self.backend = "brave" if name == "web-careers" else ""

            def configured(self):
                return True

            def diagnostics(
                self, *, jobs_added=0, backend_qualifying=None, backend_added=None,
            ):
                return {
                    "configured": True, "backend": "brave", "brave_used": True,
                    "brave_search_results_returned": 0, "pages_fetched": 0,
                    "valid_job_postings_extracted": 0, "jobs_added": jobs_added,
                    "google_cse": {
                        "configured": True, "used": True, "results_fetched": 1,
                        "qualifying": 1, "added": 1, "errors": [],
                    },
                    "errors": [],
                }

        available = {name: StubProvider(name) for name in CORE_PROVIDERS}
        store = unittest.mock.Mock()
        store.all.return_value = []
        store.get.return_value = None
        args = build_parser().parse_args(["daily"])
        output = io.StringIO()
        with (
            patch("scout.providers", return_value=available),
            patch("scout.extract_resume_text", return_value="resume"),
            patch("scout.discover", return_value=SearchSummary()) as mocked_discover,
            patch("scout.discover_remotive_full_feed", return_value=SearchSummary()),
            patch("scout.sync_tracker"),
            patch("scout.build_review_queue", return_value={}),
            patch("scout._daily_resume_runner", return_value=self.queue_result()),
            redirect_stdout(output),
        ):
            result = daily(args, store, load_preferences())

        invoked = [call.args[0].name for call in mocked_discover.call_args_list]
        daily_summary, _ = json.JSONDecoder().raw_decode(output.getvalue())
        self.assertEqual(result, 0)
        self.assertIn("web-careers", invoked)
        self.assertTrue(daily_summary["source_diagnostics"]["web-careers"]["configured"])
        self.assertEqual(daily_summary["source_backends"]["web-careers"], "brave")
        self.assertTrue(daily_summary["google_cse"]["used"])

    def test_provider_alias_accepts_remotive(self):
        args = build_parser().parse_args([
            "search", "--provider", "remotive", "--limit", "100",
        ])
        self.assertEqual(args.source, "remotive")
        self.assertEqual(args.limit, 100)

    def test_remotive_rss_diagnostic_command_is_available(self):
        args = build_parser().parse_args(["diagnose-remotive-rss"])
        self.assertEqual(args.command, "diagnose-remotive-rss")

    def test_remotive_feeds_diagnostic_command_is_available(self):
        args = build_parser().parse_args(["diagnose-remotive-feeds"])
        self.assertEqual(args.command, "diagnose-remotive-feeds")

    def test_sync_sheets_command_is_available(self):
        args = build_parser().parse_args(["sync-sheets"])
        self.assertEqual(args.command, "sync-sheets")

    def test_daily_review_contains_only_ids_discovered_in_current_run(self):
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                old_job = normalize(raw(source_id="old", url="https://example.test/old"))
                old_job.title = "Old Paid Search Manager"
                old_job.match_score = 95
                old_job.evidence_confidence = 90
                old_id = store.save(old_job)
                new_job = normalize(raw(source_id="new", url="https://example.test/new"))
                new_job.title = "New Performance Marketing Manager"
                new_job.match_score = 91
                new_job.evidence_confidence = 85
                new_id = store.save(new_job)

                def fake_search(search_args, _store, _preferences):
                    search_args.run_result = {
                        "new_job_ids": [new_id], "existing_job_ids": [old_id],
                    }
                    return 0

                output = io.StringIO()
                args = build_parser().parse_args(["daily"])
                with (patch("scout.search", side_effect=fake_search),
                      patch("scout.sheet_only_active_jobs", return_value=[]),
                      patch("scout.protected_job_ids", return_value=set()),
                      patch("scout.DailyLinkValidator.check_existing", return_value=[]),
                      patch("scout._daily_resume_runner", return_value=self.queue_result()),
                      redirect_stdout(output)):
                    result = daily(args, store, load_preferences())

        self.assertEqual(result, 0)
        self.assertIn("New Performance Marketing Manager", output.getvalue())
        self.assertNotIn("Old Paid Search Manager", output.getvalue())

    def test_daily_review_clearly_reports_zero_new_qualifying_jobs(self):
        def fake_search(search_args, _store, _preferences):
            search_args.run_result = {"new_job_ids": [], "existing_job_ids": [1]}
            return 0

        output = io.StringIO()
        args = build_parser().parse_args(["daily"])
        with (patch("scout.search", side_effect=fake_search),
              patch("scout._daily_resume_runner", return_value=self.queue_result()),
              redirect_stdout(output)):
            result = daily(args, object(), {})
        self.assertEqual(result, 0)
        self.assertIn("No new qualifying jobs", output.getvalue())


class WebCareerDiagnosticsTests(unittest.TestCase):
    def test_brave_backend_reports_acquisition_and_extraction_counts(self):
        job_page = b'''<script type="application/ld+json">{
            "@type": "JobPosting",
            "title": "Paid Search Manager",
            "description": "Own paid search strategy.",
            "hiringOrganization": {"name": "Example Co"},
            "url": "https://example.test/jobs/1"
        }</script>'''
        environment = {
            "BRAVE_SEARCH_API_KEY": "brave-secret",
            "GOOGLE_CSE_ENABLED": "true",
            "GOOGLE_CSE_API_KEY": "google-secret",
            "GOOGLE_CSE_ID": "google-cx",
        }
        with (
            patch.dict(os.environ, environment),
            patch("sources.web.get_json", return_value={"web": {"results": [
                {"url": "https://example.test/jobs/1"},
                {"url": "https://example.test/jobs/2"},
            ]}}),
            patch("sources.web.get_bytes", return_value=job_page),
        ):
            provider = WebCareerProvider()
            listings = list(provider.search(SearchRequest("paid search", "Remote")))

        diagnostics = provider.diagnostics(jobs_added=1)
        self.assertEqual(len(listings), 2)
        self.assertTrue(diagnostics["configured"])
        self.assertEqual(diagnostics["backend"], "brave")
        self.assertTrue(diagnostics["brave_used"])
        self.assertEqual(diagnostics["brave_search_results_returned"], 2)
        self.assertEqual(diagnostics["pages_fetched"], 2)
        self.assertEqual(diagnostics["valid_job_postings_extracted"], 2)
        self.assertEqual(diagnostics["jobs_added"], 1)
        self.assertEqual(diagnostics["errors"], [])

    def test_both_configured_backends_run_the_same_existing_query(self):
        calls = []

        def search_api(url, headers=None):
            calls.append((url, headers))
            if "api.search.brave.com" in url:
                return {"web": {"results": [{"url": "https://example.test/brave"}]}}
            return {"items": [{"link": "https://example.test/google"}]}

        job_page = b'''<script type="application/ld+json">{
            "@type": "JobPosting", "title": "Paid Search Manager",
            "description": "Own paid search strategy.",
            "hiringOrganization": {"name": "Example Co"}
        }</script>'''
        environment = {
            "BRAVE_SEARCH_API_KEY": "brave-secret",
            "GOOGLE_CSE_ENABLED": "true",
            "GOOGLE_CSE_API_KEY": "google-secret",
            "GOOGLE_CSE_ID": "google-cx",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("sources.web.get_json", side_effect=search_api),
            patch("sources.web.get_bytes", return_value=job_page),
        ):
            provider = WebCareerProvider()
            listings = list(provider.search(SearchRequest("paid search", "Remote")))

        api_queries = [parse_qs(urlsplit(url).query)["q"][0] for url, _ in calls]
        expected = (
            "paid search jobs "
            "(site:jobs.lever.co OR site:boards.greenhouse.io OR inurl:careers) Remote"
        )
        self.assertEqual(api_queries, [expected, expected])
        self.assertEqual(len(listings), 2)
        self.assertEqual({listing.source for listing in listings}, {"web-careers"})
        self.assertEqual(
            {tuple(listing.metadata["_web_search_backends"]) for listing in listings},
            {("brave",), ("google-cse",)},
        )
        diagnostics = provider.diagnostics()
        self.assertTrue(diagnostics["google_cse_configured"])
        self.assertTrue(diagnostics["google_cse_used"])
        self.assertEqual(diagnostics["google_cse"]["results_fetched"], 1)

    def test_google_listing_uses_shared_deduplication_and_backend_counts(self):
        def search_api(url, headers=None):
            if "api.search.brave.com" in url:
                return {"web": {"results": [{"url": "https://example.test/brave"}]}}
            return {"items": [{"link": "https://example.test/google"}]}

        job_page = b'''<script type="application/ld+json">{
            "@type": "JobPosting", "title": "Paid Search Manager",
            "description": "Own paid search strategy and reporting.",
            "hiringOrganization": {"name": "Example Co"},
            "identifier": {"value": "shared-job-123"},
            "jobLocation": {"address": {"addressLocality": "Remote"}}
        }</script>'''
        environment = {
            "BRAVE_SEARCH_API_KEY": "brave-secret",
            "GOOGLE_CSE_ENABLED": "true",
            "GOOGLE_CSE_API_KEY": "google-secret",
            "GOOGLE_CSE_ID": "google-cx",
        }
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.dict(os.environ, environment, clear=True),
                patch("sources.web.get_json", side_effect=search_api),
                patch("sources.web.get_bytes", return_value=job_page),
            ):
                provider = WebCareerProvider()
                with JobStore(Path(directory) / "jobs.sqlite3") as store:
                    summary = discover(
                        provider, [SearchRequest("paid search", "Remote")], store,
                        load_preferences(), DESCRIPTION, minimum_score=101,
                    )

        self.assertEqual(summary.fetched, 2)
        self.assertEqual(summary.added, 1)
        self.assertEqual(summary.duplicates, 1)
        self.assertEqual(summary.backend_qualifying, {"brave": 1, "google-cse": 1})
        self.assertEqual(summary.backend_added, {"brave": 1})

    def test_google_cse_error_is_visible_and_does_not_expose_credentials(self):
        secret = "do-not-print-google-key"
        with (
            patch.dict(os.environ, {
                "GOOGLE_CSE_ENABLED": "true",
                "GOOGLE_CSE_API_KEY": secret, "GOOGLE_CSE_ID": "google-cx",
            }, clear=True),
            patch(
                "sources.web.get_json",
                side_effect=ProviderError(f"Google rejected key {secret}"),
            ),
        ):
            provider = WebCareerProvider()
            listings = list(provider.search(SearchRequest("paid search", "Remote")))

        diagnostics = provider.diagnostics()
        self.assertEqual(listings, [])
        self.assertTrue(diagnostics["google_cse"]["used"])
        self.assertEqual(len(diagnostics["google_cse"]["errors"]), 1)
        self.assertNotIn(secret, json.dumps(diagnostics))
        self.assertIn("[REDACTED]", diagnostics["google_cse"]["errors"][0]["error"])

    def test_google_cse_is_disabled_by_default_even_with_credentials(self):
        environment = {
            "BRAVE_SEARCH_API_KEY": "brave-secret",
            "GOOGLE_CSE_API_KEY": "legacy-google-key",
            "GOOGLE_CSE_ID": "legacy-google-cx",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch("sources.web.get_json", return_value={"web": {"results": []}}) as get_json,
        ):
            provider = WebCareerProvider()
            listings = list(provider.search(SearchRequest("paid search", "Remote")))

        diagnostics = provider.diagnostics()
        self.assertEqual(listings, [])
        self.assertEqual(get_json.call_count, 1)
        self.assertIn("api.search.brave.com", get_json.call_args.args[0])
        self.assertEqual(provider.backends, ["brave"])
        self.assertTrue(diagnostics["google_cse"]["configured"])
        self.assertFalse(diagnostics["google_cse"]["enabled"])
        self.assertFalse(diagnostics["google_cse"]["used"])
        self.assertTrue(diagnostics["google_cse"]["skipped"])
        self.assertEqual(diagnostics["google_cse"]["skip_reason"], "disabled")
        self.assertEqual(diagnostics["google_cse"]["errors"], [])

    def test_brave_api_error_is_reported_without_exposing_key(self):
        secret = "do-not-print-this-key"
        with (
            patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": secret}, clear=True),
            patch(
                "sources.web.get_json",
                side_effect=ProviderError(f"Brave request rejected token {secret}"),
            ),
        ):
            provider = WebCareerProvider()
            listings = list(provider.search(SearchRequest("paid search", "Remote")))

        diagnostics = provider.diagnostics()
        self.assertEqual(listings, [])
        self.assertEqual(diagnostics["backend"], "brave")
        self.assertEqual(len(diagnostics["errors"]), 1)
        self.assertNotIn(secret, json.dumps(diagnostics))
        self.assertIn("[REDACTED]", diagnostics["errors"][0]["error"])


class RoleFilterTests(unittest.TestCase):
    def test_target_and_similar_senior_marketing_roles_are_retained(self):
        titles = [
            "Performance Marketing Manager", "Director of Digital Marketing",
            "Marketing Analytics Manager", "Demand Generation Manager",
            "Senior Paid Search Strategist", "Head of Growth Marketing",
            "Marketing Manager", "Ecommerce Manager", "Email Marketing Manager",
            "Digital Marketing Project Manager", "Marketing Account Director",
        ]
        self.assertTrue(all(is_relevant_role(title) for title in titles))

    def test_unrelated_role_families_are_excluded(self):
        titles = [
            "Senior Software Engineer", "DevOps Engineer", "QA Analyst",
            "IT Support Specialist", "Generative AI Engineer", ".NET Developer",
            "React Developer", "Rails Engineer", "Data Scientist",
            "Customer Service Representative", "Administrative Assistant",
            "Account Executive", "Technical Writer",
            "Assistant Production Manager", "Asst. Production Manager", "Senior Contracts Manager",
            "Project Manager", "Media Production Specialist", "Field Office Manager",
        ]
        self.assertTrue(all(not is_relevant_role(title) for title in titles))

    def test_marketing_analytics_data_science_exception_is_retained(self):
        self.assertTrue(is_relevant_role("Data Scientist, Marketing Analytics"))

    def test_fluent_spanish_title_is_excluded_even_for_target_role(self):
        self.assertFalse(is_relevant_role("Paid Search Manager - Fluent Spanish"))
        self.assertFalse(is_relevant_role("Spanish Fluent Performance Marketing Manager"))


class JoobleProviderTests(unittest.TestCase):
    @patch("sources.jooble.post_json")
    def test_maps_official_api_response_to_common_raw_listing(self, mocked_post):
        mocked_post.return_value = {"jobs": [{
            "id": 123,
            "title": "Paid Search Manager",
            "company": "Example Co",
            "location": "Salt Lake City, UT",
            "snippet": "Own Google Ads, Bing Ads, testing, and reporting.",
            "salary": "$90,000",
            "type": "Full-time",
            "link": "https://example.test/jobs/123?utm_source=jooble",
            "updated": "2026-09-19T12:00:00Z",
        }]}
        provider = JoobleProvider(api_key="secret-value")
        jobs = list(provider.search(SearchRequest("paid search", "Utah", results_per_page=5)))
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].source, "Jooble")
        self.assertEqual(jobs[0].source_job_id, "123")
        self.assertEqual(jobs[0].employment_type, "Full-time")
        self.assertEqual(jobs[0].salary, "$90,000")
        args, kwargs = mocked_post.call_args
        self.assertEqual(kwargs["error_label"], "Jooble API")
        self.assertNotIn("secret-value", repr(kwargs))

    def test_requires_api_key(self):
        provider = JoobleProvider(api_key="")
        with patch.dict(os.environ, {"JOOBLE_API_KEY": ""}, clear=False):
            provider = JoobleProvider(api_key="")
            self.assertFalse(provider.configured())
            with self.assertRaisesRegex(ProviderError, "JOOBLE_API_KEY"):
                list(provider.search(SearchRequest("paid search")))


class DeduplicationTests(unittest.TestCase):
    def test_merges_repost_and_preserves_new_link(self):
        original = normalize(raw())
        original.id = 1
        repost = normalize(raw("another-board", "xyz", "https://board.test/jobs/xyz"))
        self.assertGreaterEqual(duplicate_confidence(original, repost), .76)
        self.assertEqual(find_duplicate(repost, [original]).id, 1)


class ReviewQueueTests(unittest.TestCase):
    @staticmethod
    def job(job_id, *, status="new", posted="2026-09-01"):
        job = normalize(raw(source_id=str(job_id)))
        job.id = job_id
        job.status = status
        job.date_posted = posted
        return job

    def test_review_is_newest_first_and_has_no_evaluation_fields(self):
        queue = build_review_queue([
            self.job(1, posted="2026-09-01"),
            self.job(2, posted="2026-09-03"),
            self.job(3, status="rejected", posted="2026-09-04"),
        ])
        self.assertEqual([job.id for job in queue["jobs"]], [2, 1])
        payload = json.loads(queue_to_json(queue))
        self.assertEqual(set(payload), {"jobs"})
        self.assertFalse({"match_score", "evidence_confidence", "match_status"} & set(payload["jobs"][0]))

class StorageAndServiceTests(unittest.TestCase):
    def test_jooble_source_and_jooble_destination_are_excluded_before_storage(self):
        class MixedProvider(JobSource):
            name = "mixed"

            def configured(self):
                return True

            def search(self, _request):
                yield raw(source="Jooble", source_id="blocked-source",
                          url="https://example.test/jobs/blocked-source")
                yield raw(source="web-careers", source_id="blocked-url",
                          url="https://www.jooble.org/jobs/blocked-url")
                yield raw(source="web-careers", source_id="allowed",
                          url="https://careers.example.test/jobs/allowed")

        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                summary = discover(
                    MixedProvider(), [SearchRequest("paid search")], store,
                )
                saved = store.all()

        self.assertEqual(summary.fetched, 3)
        self.assertEqual(summary.jooble_excluded, 2)
        self.assertEqual([job.source_job_id for job in saved], ["allowed"])

    def test_discovery_persists_listing_and_status_without_evaluation_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "jobs.sqlite3"
            with JobStore(database) as store:
                summary = discover(
                    FakeProvider(), [SearchRequest("paid search")], store,
                )
                jobs = store.all()
                self.assertEqual(len(jobs), 1)
                self.assertFalse({"match_score", "evidence_confidence", "match_status"} & set(jobs[0].to_dict()))
                self.assertEqual(jobs[0].status, "new")
                store.update_status(jobs[0].id, "reviewing")
                self.assertEqual(store.get(jobs[0].id).status, "reviewing")

    def test_role_filter_keeps_relevant_marketing_role(self):
        class MixedProvider(JobSource):
            name = "mixed"

            def configured(self):
                return True

            def search(self, _request):
                engineering = raw(source="mixed", source_id="eng")
                engineering.title = "Senior DevOps Engineer"
                yield engineering
                yield raw(source="mixed", source_id="marketing")

        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                summary = discover(
                    MixedProvider(), [SearchRequest("anything")], store,
                )
                saved = store.all()

        self.assertEqual(summary.fetched, 2)
        self.assertEqual(summary.filtered_by_role, 1)
        self.assertEqual([job.title for job in saved], ["Paid Search Manager"])

    def test_daily_discovery_identifies_existing_without_mutating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                first = discover(
                    FakeProvider(), [SearchRequest("paid search")], store,
                )
                job_id = first.new_job_ids[0]
                before = store.get(job_id).to_dict()
                preexisting_ids = {job_id}
                rerun = discover(
                    FakeProvider(), [SearchRequest("paid search")], store,
                    preserve_existing=True,
                    preexisting_ids=preexisting_ids,
                )
                after = store.get(job_id).to_dict()

        self.assertEqual(rerun.new_job_ids, [])
        self.assertEqual(rerun.existing_job_ids, [job_id])
        self.assertEqual(rerun.updated, 0)
        self.assertEqual(after, before)

    def test_selection_handoff_archives_only_description(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            job = normalize(raw())
            path = archive_listing(job, root)
            self.assertTrue(path.is_file())
            self.assertTrue((root / "scratch" / "Example-Co+abc").is_dir())
            self.assertIn("## Full job description", path.read_text(encoding="utf-8"))
            self.assertFalse((root / "output").exists())


class EnrichmentTests(unittest.TestCase):
    @staticmethod
    def job():
        listing = raw(source="adzuna", source_id="enrich-1", url="https://adzuna.test/redirect")
        listing.description = "Lead paid social and paid search growth campaigns."
        return normalize(listing)

    def test_successful_enrichment_preserves_original_without_rating_data(self):
        detailed = (DESCRIPTION + " Own paid social, SEO, Shopify, reporting, attribution, and team leadership. ") * 12
        payload = json.dumps({
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": "Paid Search Manager", "description": detailed,
            "url": "https://careers.example.test/jobs/paid-search-manager",
        })

        def fetch(_url):
            return FetchedDocument(
                body=f'<script type="application/ld+json">{payload}</script>'.encode(),
                final_url="https://careers.example.test/jobs/paid-search-manager",
                content_type="text/html",
            )

        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                job = self.job()
                job.id = store.save(job)
                enriched = enrich_and_store(job, store, fetch=fetch)
                saved = store.get(enriched.id)
                self.assertEqual(saved.original_description, "Lead paid social and paid search growth campaigns.")
                self.assertEqual(saved.original_url, "https://adzuna.test/redirect")
                self.assertEqual(saved.enrichment_status, "succeeded")
                self.assertGreater(len(saved.enriched_description), len(saved.original_description))
                self.assertFalse({"match_score", "evidence_confidence", "match_status"} & set(saved.to_dict()))

    def test_official_greenhouse_structured_fallback(self):
        detailed = (DESCRIPTION + " Paid social SEO Shopify automation leadership. ") * 10

        def fetch(url):
            if "boards-api.greenhouse.io" in url:
                payload = {"jobs": [{
                    "title": "Paid Search Manager", "content": detailed,
                    "absolute_url": "https://careers.example.test/positions/123",
                }]}
                return FetchedDocument(json.dumps(payload).encode(), url, "application/json")
            return FetchedDocument(b'COINBASE_PUBLIC_GREENHOUSE_BOARD_ID":"example"',
                                   "https://careers.example.test", "text/html")

        result = enrich_listing(self.job(), fetch=fetch)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.source_url, "https://careers.example.test/positions/123")
        self.assertGreater(len(result.description), 1000)

if __name__ == "__main__":
    unittest.main()


