"""Availability checks and pre-scoring rejection tests."""

from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from link_validation import DailyLinkValidator, LinkResult, validate_url
from models import RawListing
from service import discover
from sources.base import SearchRequest
from storage import JobStore

URL = "https://jobs.example.test/posting/123"


class FakeResponse:
    status = 200

    def __init__(self, body=b"<h1>Paid Search Manager</h1>", final_url=URL):
        self.body, self.final_url = body, final_url

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return self.final_url

    def read(self, _limit):
        return self.body


class FakeOpener:
    def __init__(self, result):
        self.result = result

    def open(self, *_args, **_kwargs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class LinkValidationTests(unittest.TestCase):
    def check(self, response):
        with patch("link_validation.build_opener", return_value=FakeOpener(response)):
            return validate_url(URL)

    def test_200_valid_listing_and_redirect(self):
        self.assertEqual(self.check(FakeResponse()).status, "valid")
        final = "https://company.example.test/careers/123"
        result = self.check(FakeResponse(final_url=final))
        self.assertEqual((result.status, result.final_url), ("valid", final))

    def test_404_410_and_explicit_expiry_are_dead(self):
        for status in (404, 410):
            with self.subTest(status=status):
                result = self.check(HTTPError(URL, status, "gone", {}, None))
                self.assertEqual((result.status, result.http_status), ("dead", status))
        self.assertEqual(self.check(FakeResponse(body=b"This job is no longer available")).status, "dead")

    def test_transient_and_bot_failures_are_preserved(self):
        for status in (403, 429, 500):
            self.assertEqual(self.check(HTTPError(URL, status, "temporary", {}, None)).status,
                             "temporary_failure")
        for failure in (TimeoutError(), URLError("DNS unavailable")):
            self.assertEqual(self.check(failure).status, "temporary_failure")
        self.assertEqual(self.check(FakeResponse(body=b"Cloudflare: checking your browser")).status,
                         "temporary_failure")

    def test_official_ats_api_absence_is_dead(self):
        lever = "https://jobs.lever.co/example/abc123"
        with patch("link_validation._request", return_value=LinkResult("dead", lever, http_status=404)):
            self.assertIn("Official ATS API", validate_url(lever).reason)

    def test_new_dead_listing_is_rejected_before_scoring_and_storage(self):
        class Provider:
            def search(self, _request):
                return [RawListing(source="test", source_job_id="new-dead", url=URL,
                                   title="Paid Search Manager", company="Dead Co",
                                   description="Manage Google Ads campaigns.")]

        with TemporaryDirectory() as temp, JobStore(Path(temp) / "jobs.sqlite3") as store:
            with patch("link_validation.validate_job", return_value=LinkResult("dead", URL, http_status=404)), \
                 patch("service.score_job", side_effect=AssertionError("scored before validation")):
                result = discover(Provider(), [SearchRequest("paid search", "Remote")], store,
                                  {"minimum_score": 80}, "master resume", link_validator=DailyLinkValidator())
            self.assertEqual(result.scored, 0)
            self.assertEqual(store.all(), [])


if __name__ == "__main__":
    unittest.main()
