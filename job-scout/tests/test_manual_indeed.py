"""Manual Indeed intake regression tests."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from google_tracker import Config, GoogleTracker
from manual_indeed import process_manual_indeed_rows
from models import RawListing
from sources.base import ProviderError
from sources.http import FetchedDocument
from sources.indeed import ManualIndeedProvider, extract_indeed_job_key
from sources.indeed import IndeedFallbackResult, ManualIndeedFallbackRetriever
from sources.web import SearchHit
from storage import JobStore
from test_google_tracker import FakeSheets, SCOUT


def manual_row(url: str, *, apply="") -> list:
    row = [""] * len(SCOUT)
    row[SCOUT.index("Apply?")] = apply
    row[SCOUT.index("Job URL")] = url
    return row


def raw(jk: str, *, title="Paid Search Manager", company="Acme, Inc.",
        location="Salt Lake City, UT") -> RawListing:
    return RawListing(
        source="Indeed", source_job_id=jk,
        url=f"https://www.indeed.com/viewjob?jk={jk}",
        title=title, company=company, location=location,
        description="Own paid search strategy, execution, reporting, and optimization.",
        employment_type="FULL_TIME", salary="$100,000", date_posted="2026-09-27",
    )


class FakeProvider:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def retrieve(self, url):
        self.calls.append(url)
        value = self.values[extract_indeed_job_key(url)]
        if isinstance(value, Exception):
            raise value
        return value


class FakeFallback:
    def __init__(self, values=None):
        self.values = values or {}
        self.calls = []

    def retrieve(self, url):
        self.calls.append(url)
        value = self.values.get(extract_indeed_job_key(url), IndeedFallbackResult(
            diagnostics=("Brave=no matching result", "employer lookup=no confirmed posting"),
        ))
        if isinstance(value, Exception):
            raise value
        return value


def recovered(jk: str, **kwargs) -> IndeedFallbackResult:
    listing = raw(jk, **kwargs)
    return IndeedFallbackResult(
        listing=listing,
        authoritative_url=f"https://careers.example.com/jobs/{jk}",
        destination_type="official_employer_domain",
        diagnostics=("employer lookup=confirmed posting",),
    )


class ManualIndeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.temp.name) / "jobs.sqlite3")
        self.fake = FakeSheets()
        self.tracker = GoogleTracker(
            Config("test-id", Path("unused.json"), "Job Tracker", "Job Scout"), self.fake,
        )

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_job_key_and_tracking_parameters_are_normalized(self):
        plain = "https://www.indeed.com/viewjob?jk=eda9b1ae87f489f2"
        tracked = plain + "&from=shareddesktop_copy&utm_source=something"
        self.assertEqual(extract_indeed_job_key(plain), "eda9b1ae87f489f2")
        self.assertEqual(extract_indeed_job_key(tracked), "eda9b1ae87f489f2")

    def test_new_url_populates_existing_row_and_preserves_formatting_and_url(self):
        url = "https://www.indeed.com/viewjob?jk=new123&from=shareddesktop_copy"
        self.fake.data["Job Scout"].append(manual_row(url, apply="Yes"))
        self.fake.formats[3] = {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}}
        provider = FakeProvider({"new123": raw("new123")})

        result = process_manual_indeed_rows(
            self.tracker, self.store, provider=provider, today="2026-09-27",
        )

        row = dict(zip(SCOUT, self.fake.data["Job Scout"][2]))
        self.assertEqual(result.new_job_ids, [43])
        self.assertEqual(row["Scout ID"], 43)
        self.assertEqual(row["Source"], "indeed")
        self.assertEqual(row["Company"], "Acme, Inc.")
        self.assertEqual(row["Job URL"], url)
        self.assertEqual(row["Apply?"], "Yes")
        self.assertEqual(self.store.get(43).source_job_id, "new123")
        self.assertEqual(self.fake.formats[3], {
            "userEnteredFormat": {"numberFormat": {"type": "TEXT"}},
        })
        self.assertEqual(self.fake.structural, [])

    def test_direct_success_does_not_invoke_fallback(self):
        url = "https://www.indeed.com/viewjob?jk=direct"
        self.fake.data["Job Scout"].append(manual_row(url))
        fallback = FakeFallback()
        result = process_manual_indeed_rows(
            self.tracker, self.store,
            provider=FakeProvider({"direct": raw("direct")}), fallback=fallback,
        )
        self.assertEqual(result.processed, 1)
        self.assertEqual(fallback.calls, [])

    def _assert_blocked_direct_falls_back(self, status):
        jk = f"blocked-{status}"
        url = f"https://www.indeed.com/viewjob?jk={jk}&from=shareddesktop_copy"
        self.fake.data["Job Scout"].append(manual_row(url))
        result = process_manual_indeed_rows(
            self.tracker, self.store,
            provider=FakeProvider({jk: ProviderError(f"HTTP Error {status}: blocked")}),
            fallback=FakeFallback({jk: recovered(jk)}),
        )
        row = dict(zip(SCOUT, self.fake.data["Job Scout"][2]))
        self.assertEqual(result.processed, 1)
        self.assertEqual(row["Scout ID"], 43)
        self.assertEqual(row["Job URL"], url)
        saved = self.store.get(43)
        self.assertEqual(saved.authoritative_url, f"https://careers.example.com/jobs/{jk}")
        self.assertEqual(saved.source, "Indeed")

    def test_direct_401_uses_fallback(self):
        self._assert_blocked_direct_falls_back(401)

    def test_direct_403_uses_fallback(self):
        self._assert_blocked_direct_falls_back(403)

    def test_direct_429_uses_fallback(self):
        self._assert_blocked_direct_falls_back(429)

    def test_same_indeed_job_key_is_flagged_without_retrieval_or_id(self):
        self.fake.data["Job Scout"].append(manual_row(
            "https://www.indeed.com/viewjob?jk=existing&from=shareddesktop_copy"
        ))
        self.fake.data["Job Scout"][1][SCOUT.index("Job URL")] = (
            "https://www.indeed.com/viewjob?jk=existing&utm_source=old"
        )
        provider = FakeProvider({})
        result = process_manual_indeed_rows(self.tracker, self.store, provider=provider)
        row = dict(zip(SCOUT, self.fake.data["Job Scout"][2]))
        self.assertEqual(result.duplicates, 1)
        self.assertEqual(provider.calls, [])
        self.assertEqual(row["Scout ID"], "")
        self.assertIn("Scout ID 42", row["Notes"])
        self.assertIn("Indeed JK", row["Notes"])

    def test_exact_company_title_location_deduplicates_across_sources(self):
        existing = self.fake.data["Job Scout"][1]
        existing[SCOUT.index("Source")] = "LinkedIn"
        existing[SCOUT.index("Company")] = "Acme Inc"
        existing[SCOUT.index("Job Title")] = "Paid Search Manager"
        existing[SCOUT.index("Location")] = "Salt Lake City UT"
        existing[SCOUT.index("Job URL")] = "https://linkedin.test/jobs/42"
        self.fake.data["Job Scout"].append(manual_row(
            "https://www.indeed.com/viewjob?jk=cross-source"
        ))

        result = process_manual_indeed_rows(
            self.tracker, self.store,
            provider=FakeProvider({"cross-source": raw("cross-source")}),
        )
        row = dict(zip(SCOUT, self.fake.data["Job Scout"][2]))
        self.assertEqual(result.duplicates, 1)
        self.assertIn("company/title/location", row["Notes"])
        self.assertEqual(row["Scout ID"], "")

    def test_different_job_at_same_company_is_not_rejected(self):
        existing = self.fake.data["Job Scout"][1]
        existing[SCOUT.index("Company")] = "Acme Inc"
        existing[SCOUT.index("Job Title")] = "SEO Manager"
        existing[SCOUT.index("Location")] = "Salt Lake City UT"
        existing[SCOUT.index("Job URL")] = "https://linkedin.test/jobs/42"
        self.fake.data["Job Scout"].append(manual_row(
            "https://www.indeed.com/viewjob?jk=different"
        ))

        result = process_manual_indeed_rows(
            self.tracker, self.store,
            provider=FakeProvider({"different": raw("different")}),
        )
        self.assertEqual(result.processed, 1)
        self.assertEqual(result.duplicates, 0)

    def test_ids_use_highest_value_and_high_water_mark_never_reuses_deleted_id(self):
        self.fake.data["Job Scout"][1][SCOUT.index("Scout ID")] = 900
        self.fake.data["Job Scout"].append(manual_row(
            "https://www.indeed.com/viewjob?jk=first"
        ))
        first = process_manual_indeed_rows(
            self.tracker, self.store, provider=FakeProvider({"first": raw("first")}),
        )
        self.assertEqual(first.new_job_ids, [901])
        self.store.delete_dead_unprotected(901)
        self.fake.data["Job Scout"][2][SCOUT.index("Scout ID")] = ""
        self.fake.data["Job Scout"][2][SCOUT.index("Job URL")] = (
            "https://www.indeed.com/viewjob?jk=second"
        )
        second = process_manual_indeed_rows(
            self.tracker, self.store, provider=FakeProvider({"second": raw("second")}),
        )
        self.assertEqual(second.new_job_ids, [902])

    def test_processed_and_duplicate_rows_are_idempotently_skipped(self):
        self.fake.data["Job Scout"].append(manual_row(
            "https://www.indeed.com/viewjob?jk=done"
        ))
        self.fake.data["Job Scout"][2][SCOUT.index("Scout ID")] = 43
        self.fake.data["Job Scout"].append(manual_row(
            "https://www.indeed.com/viewjob?jk=duplicate"
        ))
        self.fake.data["Job Scout"][3][SCOUT.index("Notes")] = "Duplicate — Scout ID 42"
        provider = FakeProvider({})
        result = process_manual_indeed_rows(self.tracker, self.store, provider=provider)
        self.assertEqual(result.skipped, 2)
        self.assertEqual(provider.calls, [])

    def test_retrieval_failure_does_not_stop_later_rows(self):
        self.fake.data["Job Scout"].append(manual_row(
            "https://www.indeed.com/viewjob?jk=blocked"
        ))
        self.fake.data["Job Scout"].append(manual_row(
            "https://www.indeed.com/viewjob?jk=works"
        ))
        result = process_manual_indeed_rows(
            self.tracker, self.store,
            provider=FakeProvider({
                "blocked": ProviderError("HTTP 403"),
                "works": raw("works", company="Other Co"),
            }),
            fallback=FakeFallback(),
        )
        failed = dict(zip(SCOUT, self.fake.data["Job Scout"][2]))
        succeeded = dict(zip(SCOUT, self.fake.data["Job Scout"][3]))
        self.assertEqual((result.failures, result.processed), (1, 1))
        self.assertIn("manual review required", failed["Notes"])
        self.assertEqual(failed["Scout ID"], "")
        self.assertEqual(succeeded["Source"], "indeed")
        self.assertNotEqual(succeeded["Scout ID"], "")

    def test_all_fallbacks_fail_without_consuming_scout_id(self):
        url = "https://www.indeed.com/viewjob?jk=nowhere"
        self.fake.data["Job Scout"].append(manual_row(url))
        result = process_manual_indeed_rows(
            self.tracker, self.store,
            provider=FakeProvider({"nowhere": ProviderError("HTTP Error 401")}),
            fallback=FakeFallback(),
        )
        row = dict(zip(SCOUT, self.fake.data["Job Scout"][2]))
        self.assertEqual((result.failures, row["Scout ID"]), (1, ""))
        self.assertIn("direct=401", row["Notes"])
        self.assertIn("Brave=no matching result", row["Notes"])
        self.assertIn("employer lookup=no confirmed posting", row["Notes"])
        self.assertEqual(self.store.highest_scout_id(), 0)

    def test_previously_failed_row_retries_fallback_before_direct(self):
        url = "https://www.indeed.com/viewjob?jk=retry-me"
        self.fake.data["Job Scout"].append(manual_row(url))
        self.fake.data["Job Scout"][2][SCOUT.index("Notes")] = (
            "Indeed retrieval failed â€” manual review required: direct=401"
        )
        provider = FakeProvider({"retry-me": ProviderError("direct must not run")})
        result = process_manual_indeed_rows(
            self.tracker, self.store, provider=provider,
            fallback=FakeFallback({"retry-me": recovered("retry-me")}),
        )
        row = dict(zip(SCOUT, self.fake.data["Job Scout"][2]))
        self.assertEqual(result.processed, 1)
        self.assertEqual(provider.calls, [])
        self.assertEqual(row["Notes"], "")
        self.assertEqual(row["Job URL"], url)


class ManualIndeedProviderTests(unittest.TestCase):
    def test_structured_job_posting_is_retrieved(self):
        payload = {
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": "Paid Search Manager",
            "description": "Own paid search strategy and execution.",
            "hiringOrganization": {"name": "Example Co"},
            "jobLocation": {"address": {
                "addressLocality": "Lehi", "addressRegion": "UT",
            }},
            "baseSalary": {"currency": "USD", "value": {
                "minValue": 90000, "maxValue": 110000, "unitText": "YEAR",
            }},
        }
        page = ("<script type='application/ld+json'>" + json.dumps(payload) + "</script>").encode()
        provider = ManualIndeedProvider(fetch=lambda _url: FetchedDocument(
            page, "https://www.indeed.com/viewjob?jk=abc", "text/html",
        ))
        listing = provider.retrieve("https://www.indeed.com/viewjob?jk=abc&utm_source=x")
        self.assertEqual(listing.source_job_id, "abc")
        self.assertEqual(listing.company, "Example Co")
        self.assertEqual(listing.location, "Lehi, UT")
        self.assertEqual(listing.salary, "USD 90000-110000 per YEAR")


class ManualIndeedFallbackTests(unittest.TestCase):
    class FakeSearch:
        brave_key = "configured"

        def __init__(self, employer_title="Paid Search Manager"):
            self.employer_title = employer_title
            self.queries = []

        def configured(self):
            return True

        def search_hits(self, query, *, maximum=8):
            self.queries.append(query)
            if "careers job" in query:
                return ([SearchHit(
                    "https://careers.acme.test/jobs/paid-search-manager",
                    self.employer_title, "Acme careers", "brave",
                )], [])
            return ([SearchHit(
                "https://www.indeed.com/viewjob?jk=blocked",
                "Paid Search Manager - Acme, Inc. - Salt Lake City, UT | Indeed.com",
                "Acme is hiring a Paid Search Manager in Salt Lake City.", "brave",
            )], [])

    @staticmethod
    def employer_page(title="Paid Search Manager"):
        payload = {
            "@context": "https://schema.org", "@type": "JobPosting",
            "title": title,
            "description": "Own paid search strategy, execution, reporting, and optimization.",
            "hiringOrganization": {"name": "Acme, Inc."},
            "jobLocation": {"address": {
                "addressLocality": "Salt Lake City", "addressRegion": "UT",
            }},
            "url": "https://careers.acme.test/jobs/paid-search-manager",
        }
        return FetchedDocument(
            ("<script type='application/ld+json'>" + json.dumps(payload) + "</script>").encode(),
            "https://careers.acme.test/jobs/paid-search-manager", "text/html",
        )

    def test_confident_employer_careers_page_is_used(self):
        search = self.FakeSearch()
        fallback = ManualIndeedFallbackRetriever(
            search=search, fetch=lambda _url: self.employer_page(),
        )
        result = fallback.retrieve("https://www.indeed.com/viewjob?jk=blocked")
        self.assertIsNotNone(result.listing)
        self.assertEqual(
            result.authoritative_url,
            "https://careers.acme.test/jobs/paid-search-manager",
        )
        self.assertEqual(result.listing.source_job_id, "blocked")

    def test_incorrect_employer_job_is_not_accepted(self):
        search = self.FakeSearch(employer_title="SEO Director")
        fallback = ManualIndeedFallbackRetriever(
            search=search, fetch=lambda _url: self.employer_page("SEO Director"),
        )
        result = fallback.retrieve("https://www.indeed.com/viewjob?jk=blocked")
        self.assertIsNone(result.listing)
        self.assertIn("employer lookup=no confirmed posting", result.diagnostics)


if __name__ == "__main__":
    unittest.main()
