"""Regression checks for target errors, admission and free exact ATS evidence."""
from datetime import datetime, timezone, timedelta
import io
import json
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sources.base import ProviderError
from sources import http
from sources.firecrawl import target_failure
from firecrawl_postings import reject_result, public_listing
from firecrawl_search import _payload
from firecrawl_discovery import ZONE


class RepairTests(TestCase):
    def test_generic_pages_and_old_urls_are_rejected_before_scraping(self):
        cutoff = datetime(2026, 10, 18, tzinfo=timezone.utc)
        for url in ['https://www.indeed.com/q-digital-marketing-manager-l-utah-jobs.html',
                    'https://www.glassdoor.com/Job/digital-marketing-jobs-SRCH.htm',
                    'https://jmjphillip.com/jobs/2023/09/09/digital-marketing-manager/',
                    'https://jobs.lever.co/acme']:
            self.assertTrue(reject_result(url, 'Digital Marketing Manager', cutoff), url)
        self.assertFalse(reject_result('https://jobs.lever.co/acme/abc', 'Digital Marketing Manager', cutoff))

    def test_search_payload_targets_employer_detail_sources(self):
        now = datetime.now(timezone.utc)
        data = _payload('Paid Search Manager job remote', 20, now - timedelta(hours=96), now, ZONE)
        self.assertIn('site:jobs.lever.co', data['query'])
        self.assertLessEqual(len(data['query']), 500)
        self.assertNotIn('scrapeOptions', data)

    def test_http_error_retains_redacted_provider_detail(self):
        body = {'code': 'SCRAPE_NOT_ALLOWED', 'error': 'This website is not supported'}
        failure = HTTPError('https://api.firecrawl.dev/v2/scrape', 403, 'Forbidden', {}, io.BytesIO(json.dumps(body).encode()))
        with patch.object(http, 'urlopen', side_effect=failure):
            with self.assertRaises(ProviderError) as context:
                http.post_json('https://api.firecrawl.dev/v2/scrape', {})
        self.assertTrue(target_failure(context.exception, 'scrape'))
        self.assertFalse(target_failure(context.exception, 'search'))
        unknown = ProviderError('HTTP 403'); unknown.http_status = 403
        self.assertFalse(target_failure(unknown, 'scrape'))

    def test_greenhouse_original_date_and_employer_from_free_api(self):
        url = 'https://job-boards.greenhouse.io/acme/jobs/123'
        payload = {'id': 123, 'title': 'Paid Search Manager', 'company_name': 'Acme',
                   'content': '<p>Complete original employer description</p>',
                   'location': {'name': 'Remote, US'}, 'first_published': '2026-10-21T10:00:00Z',
                   'updated_at': '2026-10-22T10:00:00Z'}
        with patch('firecrawl_postings.get_json', return_value=payload):
            data, raw, evidence, final = public_listing(url)
        self.assertEqual(raw.company, 'Acme')
        self.assertEqual(raw.date_posted, payload['first_published'])
        self.assertIn('public_api', data)
        self.assertIn('original posting', evidence)
        del payload['first_published']
        with patch('firecrawl_postings.get_json', return_value=payload):
            self.assertEqual(public_listing(url)[1].date_posted, '')

    def test_free_endpoint_access_failure_is_not_bypassed(self):
        with patch('firecrawl_postings.get_json', side_effect=ProviderError('HTTP 403')):
            with self.assertRaises(ProviderError):
                public_listing('https://job-boards.greenhouse.io/acme/jobs/123')

    def test_html_with_script_closer_in_description_normalizes_safely(self):
        payload = {'id': 123, 'title': 'Paid Search Manager', 'company_name': 'Acme',
                   'content': '<p>Full description</p><script>ignored</script><p>Requirements</p>',
                   'location': {'name': 'Remote, US'}, 'first_published': '2026-10-21T10:00:00Z'}
        with patch('firecrawl_postings.get_json', return_value=payload):
            result = public_listing('https://job-boards.greenhouse.io/acme/jobs/123')
        self.assertEqual(result[1].title, 'Paid Search Manager')
        self.assertEqual(result[1].metadata['_retrieved_via'], 'public-ats-api')
