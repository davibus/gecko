from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SCOUT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCOUT_ROOT))

from description_retrieval import description_is_sufficient, retrieve_full_description
from models import RawListing
from normalize import normalize
from sources.base import ProviderError
from sources.http import FetchedDocument


def make_job(source="Jooble", url="https://jooble.org/away/123"):
    return normalize(RawListing(
        source=source,
        source_job_id="123",
        url=url,
        title="Growth Marketing Manager",
        company="Example Company",
        location="Remote",
        description="Short provider excerpt.",
    ), discovered="2026-09-25")


def full_page(url: str) -> FetchedDocument:
    description = (
        "Lead growth marketing strategy, paid search, lifecycle campaigns, analytics, "
        "experimentation, forecasting, reporting, and cross-functional planning. " * 8
    )
    payload = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Growth Marketing Manager",
        "hiringOrganization": {"name": "Example Company"},
        "url": url,
        "description": description,
    }
    html = f'<script type="application/ld+json">{json.dumps(payload)}</script>'
    return FetchedDocument(html.encode(), url, "text/html")


class DescriptionRetrievalTests(unittest.TestCase):
    def test_authoritative_source_succeeds_without_touching_blocked_jooble(self):
        job = make_job()
        job.authoritative_url = "https://careers.example.com/jobs/growth-marketing-manager"
        calls = []

        def fetch(url):
            calls.append(url)
            if "jooble.org" in url:
                raise ProviderError("HTTP Error 403: Forbidden")
            return full_page(url)

        result = retrieve_full_description(
            job, fetch=fetch, search_urls=lambda _job, _maximum: [],
            aggregator_urls=(job.url,),
        )
        self.assertEqual(result.status, "succeeded")
        self.assertTrue(description_is_sufficient(result.description))
        self.assertFalse(any("jooble.org" in url for url in calls))

    def test_adzuna_block_moves_to_employer_source(self):
        job = make_job("Adzuna", "https://www.adzuna.com/details/123")
        job.url_redirect_url = "https://jobs.example.com/growth-marketing-manager"

        def fetch(url):
            if "adzuna.com" in url:
                raise ProviderError("HTTP Error 403: Forbidden")
            return full_page(url)

        result = retrieve_full_description(
            job, fetch=fetch, search_urls=lambda _job, _maximum: [],
            aggregator_urls=(job.url,),
        )
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.source_url, job.url_redirect_url)

    def test_all_sources_failing_returns_diagnostics_and_no_description(self):
        job = make_job()
        job.authoritative_url = "https://careers.example.com/jobs/123"

        def blocked(_url):
            raise ProviderError("HTTP Error 403: Forbidden")

        result = retrieve_full_description(
            job, fetch=blocked, search_urls=lambda _job, _maximum: [],
            aggregator_urls=(job.url,),
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.description, "")
        self.assertTrue(any("403" in attempt.detail for attempt in result.attempts))

    def test_short_description_is_never_accepted(self):
        job = make_job()
        result = retrieve_full_description(
            job,
            fetch=lambda url: FetchedDocument(
                b"<main>Growth marketing manager with paid search experience.</main>", url, "text/html"
            ),
            search_urls=lambda _job, _maximum: [],
            aggregator_urls=(job.url,),
        )
        self.assertEqual(result.status, "failed")
        self.assertFalse(description_is_sufficient("A" * 599))

    def test_good_stored_description_avoids_network(self):
        job = make_job()
        job.enriched_description = "Complete marketing responsibilities and qualifications. " * 20
        called = False

        def fetch(_url):
            nonlocal called
            called = True
            raise AssertionError("network should not be used")

        result = retrieve_full_description(job, fetch=fetch)
        self.assertEqual(result.status, "succeeded")
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
