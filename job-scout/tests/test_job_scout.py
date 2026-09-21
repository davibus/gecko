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


SCOUT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCOUT_ROOT))

from deduplicate import duplicate_confidence, find_duplicate
from enrichment import enrich_and_rescore, enrich_listing
from models import RawListing
from normalize import canonicalize_url, normalize
from preferences import load_preferences
from review import build_review_queue, queue_to_json
from role_filter import is_relevant_role
from scoring import score_job
from scoring import WEIGHTS
from service import discover
from sources.base import JobSource, SearchRequest
from sources.base import ProviderError
from sources.http import FetchedDocument
from sources.jooble import JoobleProvider
from storage import JobStore
from handoff import archive_listing
from scout import build_parser, daily, load_local_environment


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

    def test_provider_alias_accepts_jooble(self):
        args = build_parser().parse_args(["search", "--provider", "jooble"])
        self.assertEqual(args.source, "jooble")

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

    @patch("scout.review_jobs", return_value=0)
    @patch("scout.search", return_value=0)
    def test_daily_searches_all_core_providers(self, mocked_search, _mocked_review):
        args = build_parser().parse_args(["daily"])
        daily(args, None, {})
        search_args = mocked_search.call_args.args[0]
        self.assertEqual(search_args.source, "core")

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
                with patch("scout.search", side_effect=fake_search), redirect_stdout(output):
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
        with patch("scout.search", side_effect=fake_search), redirect_stdout(output):
            result = daily(args, object(), {})
        self.assertEqual(result, 0)
        self.assertIn("No new qualifying jobs", output.getvalue())


class RoleFilterTests(unittest.TestCase):
    def test_target_and_similar_senior_marketing_roles_are_retained(self):
        titles = [
            "Performance Marketing Manager", "Director of Digital Marketing",
            "Marketing Analytics Manager", "Demand Generation Manager",
            "Senior Paid Search Strategist", "Head of Growth Marketing",
        ]
        self.assertTrue(all(is_relevant_role(title) for title in titles))

    def test_unrelated_role_families_are_excluded(self):
        titles = [
            "Senior Software Engineer", "DevOps Engineer", "QA Analyst",
            "IT Support Specialist", "Generative AI Engineer", ".NET Developer",
            "React Developer", "Rails Engineer", "Data Scientist",
            "Customer Service Representative", "Administrative Assistant",
            "Account Executive", "Technical Writer",
        ]
        self.assertTrue(all(not is_relevant_role(title) for title in titles))

    def test_marketing_analytics_data_science_exception_is_retained(self):
        self.assertTrue(is_relevant_role("Data Scientist, Marketing Analytics"))


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


class ScoringTests(unittest.TestCase):
    def test_weights_total_100(self):
        self.assertEqual(sum(WEIGHTS.values()), 100)

    def test_strong_evidence_scores_above_default_threshold(self):
        result = score_job(normalize(raw()), load_preferences())
        self.assertGreaterEqual(result.total, 80)
        self.assertEqual(set(result.dimensions), set(WEIGHTS))

    def test_junior_role_is_penalized(self):
        listing = raw()
        listing.title = "Junior Paid Search Intern"
        result = score_job(normalize(listing), load_preferences())
        self.assertEqual(result.dimensions["years/seniority/scope"], 0)
        self.assertEqual(result.evidence_levels["years/seniority/scope"], "true mismatch")

    def score_adzuna(self, title, description, employment_type="full_time"):
        listing = raw(source="adzuna")
        listing.title = title
        listing.description = description
        listing.employment_type = employment_type
        return score_job(normalize(listing), load_preferences(), DESCRIPTION)

    def test_intern_does_not_match_internet(self):
        result = self.score_adzuna(
            "Paid Search Specialist - Internet Advertising",
            "Manage paid search advertising campaigns for clients.",
        )
        self.assertNotEqual(result.evidence_levels["years/seniority/scope"], "true mismatch")

    def test_cro_does_not_match_across(self):
        result = self.score_adzuna(
            "Growth Marketing Manager",
            "Build growth programs across channels and collaborate with the team.",
        )
        self.assertEqual(
            result.evidence_levels["analytics/measurement"],
            "unknown because source text is incomplete",
        )

    def test_ppc_requires_advertising_context(self):
        advertising = self.score_adzuna(
            "PPC Manager", "Lead PPC advertising and paid search campaign strategy."
        )
        production = self.score_adzuna(
            "Manager, Quality, PPC - Surgery",
            "Ensure regulatory compliance for Production and Process Control and supplier quality.",
        )
        self.assertEqual(advertising.evidence_levels["paid media/performance marketing"], "direct match")
        self.assertEqual(production.evidence_levels["paid media/performance marketing"], "true mismatch")
        self.assertEqual(production.evidence_levels["role/domain relevance"], "true mismatch")

    def test_gtm_disambiguates_tag_manager_from_go_to_market(self):
        tag_manager = self.score_adzuna(
            "Marketing Analytics Manager", "Own analytics tracking with Google Tag Manager (GTM)."
        )
        go_to_market = self.score_adzuna(
            "Growth Marketing Manager", "Build the go-to-market (GTM) strategy and demand program."
        )
        self.assertEqual(tag_manager.evidence_levels["analytics/measurement"], "direct match")
        self.assertNotEqual(go_to_market.evidence_levels["analytics/measurement"], "direct match")

    def test_paid_social_receives_paid_media_credit(self):
        result = self.score_adzuna(
            "Performance Marketing Manager, Paid Social", "Own paid social acquisition campaigns."
        )
        self.assertEqual(result.dimensions["paid media/performance marketing"], 14)

    def test_marketing_analytics_receives_analytics_credit(self):
        result = self.score_adzuna("Marketing Analytics Manager", "Lead the marketing analytics team.")
        self.assertEqual(result.dimensions["analytics/measurement"], 11)

    def test_seo_receives_transferable_digital_credit(self):
        result = self.score_adzuna("SEO Digital Marketing Analyst", "Own technical SEO and on-page SEO.")
        self.assertEqual(result.dimensions["e-commerce/SEO/transferable digital marketing"], 10)

    def test_ecommerce_receives_ecommerce_credit(self):
        result = self.score_adzuna("E-Commerce Marketing Manager", "Own ecommerce growth on Shopify.")
        self.assertEqual(result.dimensions["e-commerce/SEO/transferable digital marketing"], 10)

    def test_abbreviated_unknown_receives_neutral_credit(self):
        result = self.score_adzuna("Digital Marketing Manager", "Lead the digital marketing function.")
        name = "paid media/performance marketing"
        self.assertEqual(result.evidence_levels[name], "unknown because source text is incomplete")
        self.assertEqual(result.dimensions[name], 7)

    def test_remote_eligibility_affects_scoring_without_filtering(self):
        usa = raw(source="remotive")
        usa.location = "Worldwide"
        usa.remote_type = "remote"
        europe = raw(source="remotive")
        europe.location = "Europe only"
        europe.remote_type = "remote"

        usa_result = score_job(normalize(usa), load_preferences(), DESCRIPTION)
        europe_result = score_job(normalize(europe), load_preferences(), DESCRIPTION)

        self.assertGreater(
            usa_result.dimensions["location/work arrangement"],
            europe_result.dimensions["location/work arrangement"],
        )
        self.assertIn(
            "Remote eligibility appears to exclude the candidate's US location.",
            europe_result.weaknesses,
        )


class DeduplicationTests(unittest.TestCase):
    def test_merges_repost_and_preserves_new_link(self):
        original = normalize(raw())
        original.id = 1
        repost = normalize(raw("another-board", "xyz", "https://board.test/jobs/xyz"))
        self.assertGreaterEqual(duplicate_confidence(original, repost), .76)
        self.assertEqual(find_duplicate(repost, [original]).id, 1)


class ReviewQueueTests(unittest.TestCase):
    @staticmethod
    def job(job_id, score, confidence, *, provisional=False, status="new", posted="2026-09-01"):
        listing = raw(source_id=str(job_id), url=f"https://example.test/jobs/{job_id}")
        listing.title = f"Paid Search Manager {job_id}"
        listing.company = f"Company {job_id}"
        listing.date_posted = posted
        job = normalize(listing)
        job.id = job_id
        job.match_score = score
        job.evidence_confidence = confidence
        job.provisional = provisional
        job.status = status
        job.match_strengths = ["one", "two", "three", "four"]
        job.match_weaknesses = ["a", "b", "c", "d"]
        return job

    def test_confirmed_and_provisional_are_separate(self):
        queue = build_review_queue([
            self.job(1, 90, 80),
            self.job(2, 88, 40, provisional=True),
            self.job(3, 76, 70),
        ])
        self.assertEqual([job.id for job in queue["confirmed"]], [1])
        self.assertEqual([job.id for job in queue["provisional"]], [2])
        self.assertEqual([job.id for job in queue["near_matches"]], [3])

    def test_minimum_score_filters_all_sections(self):
        queue = build_review_queue([
            self.job(1, 82, 80), self.job(2, 76, 70), self.job(3, 74, 70),
        ], minimum_score=75)
        self.assertEqual([job.id for job in queue["confirmed"]], [1])
        self.assertEqual([job.id for job in queue["near_matches"]], [2])

    def test_closed_statuses_are_excluded_unless_requested(self):
        jobs = [
            self.job(1, 90, 90, status="applied"),
            self.job(2, 89, 90, status="rejected"),
            self.job(3, 88, 90, status="ignored"),
            self.job(4, 87, 90, status="new"),
        ]
        self.assertEqual([job.id for job in build_review_queue(jobs)["confirmed"]], [4])
        self.assertEqual(
            [job.id for job in build_review_queue(jobs, include_closed=True)["confirmed"]],
            [1, 2, 3, 4],
        )

    def test_sorting_uses_score_confidence_then_newest_date(self):
        jobs = [
            self.job(1, 90, 80, posted="2026-09-01"),
            self.job(2, 91, 65, posted="2026-09-01"),
            self.job(3, 90, 90, posted="2026-08-01"),
            self.job(4, 90, 90, posted="2026-09-10"),
        ]
        self.assertEqual([job.id for job in build_review_queue(jobs)["confirmed"]], [2, 4, 3, 1])

    def test_limit_is_applied_in_section_priority_order(self):
        jobs = [
            self.job(1, 90, 90), self.job(2, 85, 80),
            self.job(3, 84, 40, provisional=True), self.job(4, 79, 70),
        ]
        queue = build_review_queue(jobs, limit=3)
        self.assertEqual([job.id for job in queue["confirmed"]], [1, 2])
        self.assertEqual([job.id for job in queue["provisional"]], [3])
        self.assertEqual(queue["near_matches"], [])

    def test_json_output_has_sections_and_review_fields(self):
        payload = json.loads(queue_to_json(build_review_queue([self.job(1, 90, 90)])))
        self.assertEqual(set(payload), {"confirmed", "provisional", "near_matches"})
        self.assertEqual(payload["confirmed"][0]["job_id"], 1)
        self.assertEqual(payload["confirmed"][0]["top_strengths"], ["one", "two", "three"])
        self.assertEqual(payload["confirmed"][0]["employment_type"], "full-time")
        self.assertIn("best_job_url", payload["confirmed"][0])


class StorageAndServiceTests(unittest.TestCase):
    def test_discovery_persists_scored_listing_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "jobs.sqlite3"
            with JobStore(database) as store:
                summary = discover(
                    FakeProvider(), [SearchRequest("paid search")], store,
                    load_preferences(), "Google Ads GA4 SQL Python Bachelor degree management",
                )
                self.assertEqual(summary.strong, 0)
                self.assertEqual(summary.provisional, 1)
                jobs = store.all(retained_only=True)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0].status, "new")
                store.update_status(jobs[0].id, "reviewing")
                self.assertEqual(store.get(jobs[0].id).status, "reviewing")

    def test_filter_runs_before_scoring_and_keeps_relevant_marketing_role(self):
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
                    load_preferences(), DESCRIPTION,
                )
                saved = store.all()

        self.assertEqual(summary.fetched, 2)
        self.assertEqual(summary.filtered_before_scoring, 1)
        self.assertEqual(summary.scored, 1)
        self.assertEqual([job.title for job in saved], ["Paid Search Manager"])

    def test_daily_discovery_identifies_existing_without_mutating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                first = discover(
                    FakeProvider(), [SearchRequest("paid search")], store,
                    load_preferences(), DESCRIPTION,
                )
                job_id = first.new_job_ids[0]
                before = store.get(job_id).to_dict()
                preexisting_ids = {job_id}
                rerun = discover(
                    FakeProvider(), [SearchRequest("paid search")], store,
                    load_preferences(), DESCRIPTION, preserve_existing=True,
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
            job.match_score = 91
            job.match_strengths = ["Strong paid-search alignment."]
            path = archive_listing(job, root)
            self.assertTrue(path.is_file())
            self.assertTrue((root / "scratch" / "Example-Co+abc").is_dir())
            self.assertIn("## Full job description", path.read_text(encoding="utf-8"))
            self.assertFalse((root / "output").exists())


class EnrichmentTests(unittest.TestCase):
    @staticmethod
    def provisional_job():
        listing = raw(source="adzuna", source_id="enrich-1", url="https://adzuna.test/redirect")
        listing.description = "Lead paid social and paid search growth campaigns."
        job = normalize(listing)
        job.match_score = 85
        job.evidence_confidence = 37
        job.provisional = True
        return job

    def test_successful_enrichment_preserves_original_and_confirms_full_evidence(self):
        detailed = (DESCRIPTION + " Own paid social, SEO, Shopify, Salesforce, automation, "
                    "JavaScript, machine learning, reporting, attribution, and team leadership. ") * 12
        payload = json.dumps({
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Paid Search Manager",
            "description": detailed,
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
                job = self.provisional_job()
                job.id = store.save(job, retained=True)
                enriched = enrich_and_rescore(job, store, load_preferences(), DESCRIPTION, fetch=fetch)
                saved = store.get(enriched.id)
                self.assertEqual(saved.original_description, "Lead paid social and paid search growth campaigns.")
                self.assertEqual(saved.original_match_score, 85)
                self.assertEqual(saved.original_evidence_confidence, 37)
                self.assertEqual(saved.original_url, "https://adzuna.test/redirect")
                self.assertEqual(saved.enrichment_status, "succeeded")
                self.assertGreater(len(saved.enriched_description), len(saved.original_description))
                self.assertEqual(saved.enriched_source_url, "https://careers.example.test/jobs/paid-search-manager")
                self.assertGreaterEqual(saved.enriched_evidence_confidence, 65)
                self.assertGreaterEqual(saved.enriched_match_score, 80)
                self.assertFalse(saved.provisional)

    def test_failed_enrichment_keeps_job_provisional(self):
        def fetch(_url):
            raise ProviderError("public page unavailable")

        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                job = self.provisional_job()
                job.id = store.save(job, retained=True)
                failed = enrich_and_rescore(job, store, load_preferences(), DESCRIPTION, fetch=fetch)
                saved = store.get(failed.id)
                self.assertEqual(saved.enrichment_status, "failed")
                self.assertIn("unavailable", saved.enrichment_error)
                self.assertEqual(saved.match_score, 85)
                self.assertEqual(saved.evidence_confidence, 37)
                self.assertTrue(saved.provisional)
                self.assertEqual(saved.original_match_score, 85)

    def test_official_greenhouse_structured_fallback(self):
        detailed = (DESCRIPTION + " Paid social SEO Shopify automation leadership. ") * 10

        def fetch(url):
            if "boards-api.greenhouse.io" in url:
                payload = {"jobs": [{
                    "title": "Paid Search Manager",
                    "content": detailed,
                    "absolute_url": "https://careers.example.test/positions/123",
                }]}
                return FetchedDocument(json.dumps(payload).encode(), url, "application/json")
            company_page = 'COINBASE_PUBLIC_GREENHOUSE_BOARD_ID":"example"'
            return FetchedDocument(company_page.encode(), "https://careers.example.test", "text/html")

        result = enrich_listing(self.provisional_job(), fetch=fetch)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.source_url, "https://careers.example.test/positions/123")
        self.assertGreater(len(result.description), 1000)


if __name__ == "__main__":
    unittest.main()
