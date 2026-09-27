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
        )
        failed = dict(zip(SCOUT, self.fake.data["Job Scout"][2]))
        succeeded = dict(zip(SCOUT, self.fake.data["Job Scout"][3]))
        self.assertEqual((result.failures, result.processed), (1, 1))
        self.assertIn("manual review required", failed["Notes"])
        self.assertEqual(failed["Scout ID"], "")
        self.assertEqual(succeeded["Source"], "indeed")
        self.assertNotEqual(succeeded["Scout ID"], "")


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


if __name__ == "__main__":
    unittest.main()
