from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCOUT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCOUT_ROOT))

from models import RawListing
from normalize import normalize
from sources.base import ProviderError
from sources.base import JobSource, SearchRequest
from sources.http import FetchedDocument
from storage import JobStore
from service import discover
from preferences import load_preferences
from url_resolution import (
    _default_search_urls,
    apply_resolution,
    best_job_url,
    classify_url,
    resolve_authoritative_url,
    url_status_label,
)


JOOBLE_URL = "https://jooble.org/away/-1765374300165839452?p=1"


def listing(source="Jooble", url=JOOBLE_URL):
    raw = RawListing(
        source=source,
        source_job_id="-1765374300165839452",
        url=url,
        title="Growth Marketing Manager",
        company="Unicity USA Inc",
        location="Provo, UT",
        description="Lead growth marketing, paid media, analytics, and reporting.",
        date_posted="2026-09-01",
    )
    job = normalize(raw, discovered="2026-09-02")
    job.match_score = 91
    job.evidence_confidence = 82
    return job


def job_page(url, *, title="Growth Marketing Manager", company="Unicity USA Inc", location="Provo, UT", valid_through="2026-12-31"):
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "hiringOrganization": {"@type": "Organization", "name": company},
        "jobLocation": {"address": {"addressLocality": location}},
        "datePosted": "2026-09-01",
        "validThrough": valid_through,
        "url": url,
        "description": "Lead growth marketing, paid media, analytics, and reporting.",
    }
    body = f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    return FetchedDocument(body.encode(), url, "text/html")


class URLResolutionTests(unittest.TestCase):
    def test_blocked_aggregators_fall_back_to_verified_employer_search(self):
        cases = (
            listing("Jooble", JOOBLE_URL),
            listing("Adzuna", "https://www.adzuna.com/details/123"),
        )
        for job in cases:
            with self.subTest(source=job.source):
                employer = "https://careers.unicity.com/jobs/growth-marketing-manager"

                def fetch(url):
                    if "jooble.org" in url or "adzuna.com" in url:
                        raise ProviderError("HTTP Error 403: Forbidden")
                    return job_page(employer)

                result = resolve_authoritative_url(
                    job, fetch=fetch, search_urls=lambda _job, _maximum: [employer],
                )
                self.assertEqual(result.status, "verified")
                self.assertEqual(result.authoritative_url, employer)

    def test_default_search_uses_each_backend_and_limits_results(self):
        provider = Mock()
        provider.configured.return_value = True
        provider.backends = ["brave", "google-cse"]
        provider._result_urls.side_effect = [
            ["https://example.com/1", "https://example.com/2"],
            ["https://example.com/3", "https://example.com/4"],
        ]
        with patch("url_resolution.WebCareerProvider", return_value=provider):
            urls = _default_search_urls(listing(), 3)

        self.assertEqual(urls, ["https://example.com/1", "https://example.com/2", "https://example.com/3"])
        first, second = provider._result_urls.call_args_list
        self.assertEqual(first.args[0], "brave")
        self.assertEqual(second.args[0], "google-cse")
        self.assertIs(first.args[1], second.args[1])
        self.assertEqual(first.args[1].results_per_page, 3)
        self.assertEqual(first.args[2], first.args[1].query)
        self.assertEqual(second.args[2], first.args[1].query)

    def test_default_search_continues_after_backend_error(self):
        provider = Mock()
        provider.configured.return_value = True
        provider.backends = ["brave", "google-cse"]
        provider._result_urls.side_effect = [
            ProviderError("brave unavailable"), ["https://example.com/working"],
        ]
        with patch("url_resolution.WebCareerProvider", return_value=provider):
            urls = _default_search_urls(listing(), 2)

        self.assertEqual(urls, ["https://example.com/working"])
        self.assertEqual(provider._result_urls.call_count, 2)

    def resolve_redirect(self, final_url):
        return resolve_authoritative_url(
            listing(),
            fetch=lambda _url: job_page(final_url),
            search_urls=lambda _job, _maximum: [],
        )

    def test_jooble_redirect_to_official_employer_page(self):
        result = self.resolve_redirect("https://careers.unicity.com/jobs/growth-marketing-manager")
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.destination_type, "official_employer_domain")

    def test_direct_employer_page_without_schema_is_verified_when_identity_is_exact(self):
        url = "https://careers.unicity.com/jobs/growth-marketing-manager"
        page = b"<main><h1>Growth Marketing Manager</h1><p>Unicity USA Inc - Provo, UT</p></main>"
        result = resolve_authoritative_url(
            listing(),
            fetch=lambda _url: FetchedDocument(page, url, "text/html"),
            search_urls=lambda _job, _maximum: [],
        )
        self.assertEqual((result.status, result.destination_type), ("verified", "direct_employer_listing"))

    def test_jooble_redirect_to_greenhouse(self):
        result = self.resolve_redirect("https://boards.greenhouse.io/unicity/jobs/123")
        self.assertEqual((result.status, result.destination_type), ("verified", "official_ats"))

    def test_jooble_redirect_to_lever(self):
        result = self.resolve_redirect("https://jobs.lever.co/unicity/123")
        self.assertEqual((result.status, result.destination_type), ("verified", "official_ats"))

    def test_jooble_redirect_to_workday(self):
        result = self.resolve_redirect("https://unicity.wd5.myworkdayjobs.com/jobs/123")
        self.assertEqual((result.status, result.destination_type), ("verified", "official_ats"))

    def test_jooble_redirect_to_fitly_is_rejected(self):
        result = self.resolve_redirect("https://fitly.work/jobs/growth-marketing-manager")
        self.assertEqual(result.status, "authoritative_url_not_found")
        self.assertFalse(result.authoritative_url)
        self.assertEqual(classify_url("https://fitly.work/jobs/1"), "aggregator_intermediary")

    def test_jooble_redirect_to_another_aggregator_is_rejected(self):
        result = self.resolve_redirect("https://www.indeed.com/viewjob?jk=123")
        self.assertEqual(result.status, "authoritative_url_not_found")
        self.assertFalse(result.authoritative_url)

    def test_dead_redirect_is_marked_unavailable(self):
        def dead(_url):
            raise ProviderError("HTTP 404")

        result = resolve_authoritative_url(
            listing(), fetch=dead, search_urls=lambda _job, _maximum: [],
        )
        self.assertEqual(result.status, "dead_unavailable")

    def test_authoritative_search_finds_exact_employer_title_match(self):
        official = "https://careers.unicity.com/jobs/growth-marketing-manager"

        def fetch(url):
            if "jooble.org" in url:
                return FetchedDocument(b"Fitly mirror", "https://fitly.work/jobs/123", "text/html")
            return job_page(official)

        result = resolve_authoritative_url(
            listing(), fetch=fetch, search_urls=lambda _job, _maximum: [official],
        )
        self.assertEqual(result.status, "verified")
        self.assertEqual(result.authoritative_url, official)

    def test_authoritative_search_finds_no_match(self):
        wrong = "https://careers.unicity.com/jobs/software-engineer"

        def fetch(url):
            if "jooble.org" in url:
                return FetchedDocument(b"Fitly mirror", "https://fitly.work/jobs/123", "text/html")
            return job_page(wrong, title="Software Engineer", company="Different Company")

        result = resolve_authoritative_url(
            listing(), fetch=fetch, search_urls=lambda _job, _maximum: [wrong],
        )
        self.assertEqual(result.status, "authoritative_url_not_found")
        self.assertFalse(result.authoritative_url)

    def test_ambiguous_exact_matches_do_not_replace_best_url(self):
        urls = [
            "https://careers.unicity.com/jobs/growth-marketing-manager-a",
            "https://jobs.unicity.com/jobs/growth-marketing-manager-b",
        ]

        def fetch(url):
            if "jooble.org" in url:
                return FetchedDocument(b"Fitly mirror", "https://fitly.work/jobs/123", "text/html")
            return job_page(url)

        result = resolve_authoritative_url(
            listing(), fetch=fetch, search_urls=lambda _job, _maximum: urls,
        )
        self.assertEqual(result.status, "authoritative_url_not_found")
        self.assertIn("ambiguous", result.error.lower())

    def test_exact_employer_careers_match_wins_over_exact_ats_match(self):
        employer = "https://careers.unicity.com/jobs/growth-marketing-manager"
        ats = "https://jobs.lever.co/unicity/123"

        def fetch(url):
            if "jooble.org" in url:
                return FetchedDocument(b"Fitly mirror", "https://fitly.work/jobs/123", "text/html")
            return job_page(url)

        result = resolve_authoritative_url(
            listing(), fetch=fetch, search_urls=lambda _job, _maximum: [ats, employer],
        )
        self.assertEqual(result.authoritative_url, employer)
        self.assertEqual(result.destination_type, "official_employer_domain")

    def test_verified_authoritative_url_becomes_best_url(self):
        job = listing()
        official = "https://jobs.lever.co/unicity/123"
        apply_resolution(job, self.resolve_redirect(official))
        self.assertEqual(best_job_url(job), official)
        self.assertEqual(url_status_label(job), "Verified - Official ATS")

    def test_stale_state_is_stored_without_changing_fit_score_or_source_history(self):
        job = listing()
        original_score = job.match_score
        result = resolve_authoritative_url(
            job,
            fetch=lambda _url: FetchedDocument(b"mirror", "https://fitly.work/jobs/123", "text/html"),
            search_urls=lambda _job, _maximum: [],
        )
        apply_resolution(job, result)
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                job.id = store.save(job)
                store.save_url_resolution(job)
                saved = store.get(job.id)
        self.assertEqual(saved.url_verification_status, "authoritative_url_not_found")
        self.assertEqual(saved.match_score, original_score)
        self.assertEqual(saved.source_links[0]["url"], JOOBLE_URL)

    def test_expired_matching_page_is_not_verified(self):
        expired = "https://careers.unicity.com/jobs/growth-marketing-manager"
        result = resolve_authoritative_url(
            listing(),
            fetch=lambda _url: job_page(expired, valid_through="2025-01-01"),
            search_urls=lambda _job, _maximum: [],
        )
        self.assertNotEqual(result.status, "verified")

    def test_cross_provider_merge_keeps_verified_url_and_one_row(self):
        jooble = listing()
        official = "https://jobs.lever.co/unicity/123"
        apply_resolution(jooble, self.resolve_redirect(official))
        adzuna = listing(source="Adzuna", url="https://www.adzuna.com/details/999")
        adzuna.source_job_id = "999"
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                jooble.id = store.save(jooble)
                store.save_url_resolution(jooble)
                store.merge(jooble.id, adzuna)
                jobs = store.all()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(best_job_url(jobs[0]), official)
        self.assertEqual({link["source"] for link in jobs[0].source_links}, {"Jooble", "Adzuna"})

    def test_jooble_duplicate_does_not_displace_existing_provider_url(self):
        adzuna = listing(source="Adzuna", url="https://www.adzuna.com/details/999")
        adzuna.source_job_id = "999"
        jooble = listing()
        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                job_id = store.save(adzuna)
                store.merge(job_id, jooble)
                saved = store.get(job_id)
        self.assertEqual(saved.url, "https://www.adzuna.com/details/999")
        self.assertTrue(any(link["source"] == "Jooble" for link in saved.source_links))

    @patch("service.resolve_and_store", side_effect=lambda job, _store: job)
    def test_discovery_pipeline_invokes_resolution_for_retained_jooble_job(self, mocked_resolve):
        class JoobleSource(JobSource):
            name = "jooble"

            def configured(self):
                return True

            def search(self, _request):
                yield RawListing(
                    source="Jooble", source_job_id="pipeline-1", url=JOOBLE_URL,
                    title="Growth Marketing Manager", company="Unicity USA Inc",
                    location="Provo, UT", description=(
                        "Lead growth marketing Google Ads paid search analytics GA4 SQL Python "
                        "reporting ecommerce CRO and a marketing team."
                    ),
                )

        with tempfile.TemporaryDirectory() as directory:
            with JobStore(Path(directory) / "jobs.sqlite3") as store:
                discover(
                    JoobleSource(), [SearchRequest("growth marketing")], store,
                    load_preferences(), "Google Ads GA4 SQL Python leadership", minimum_score=0,
                )
        mocked_resolve.assert_called_once()


if __name__ == "__main__":
    unittest.main()
