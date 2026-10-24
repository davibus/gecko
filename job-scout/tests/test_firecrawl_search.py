"""Adaptive coverage/expansion uses mocked responses and the real shared ledger."""
from datetime import timedelta
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import test_firecrawl_discovery as fixtures
from firecrawl_search import next_work
from firecrawl_state import estimated_cost
from sources.base import ProviderError
import firecrawl_discovery as discovery
import firecrawl_state as state
from sources import firecrawl as api


class AdaptiveSearchTests(unittest.TestCase):
    setUp = fixtures.SmartDiscoveryTests.setUp
    client = fixtures.SmartDiscoveryTests.client
    run_pipeline = fixtures.SmartDiscoveryTests.run_pipeline

    def test_installed_limits_and_configured_category_coverage(self):
        settings = state.config()
        self.assertGreaterEqual(settings['max_queries_per_day'], 16)
        self.assertEqual(settings['results_per_query'], 50)
        self.assertEqual(settings['max_scrapes_per_day'], 100)
        self.assertEqual(settings['max_unknown_date_verifications_per_day'], 60)
        self.patches[0].stop()
        self.settings['max_queries_per_day'] = 16
        queries = [{'key': str(i), 'query': f'configured marketing category {i} remote'} for i in range(16)]
        def empty(url, payload, *args, **kwargs):
            return {'success': True, 'creditsUsed': estimated_cost('search', payload, self.settings), 'data': {'web': []}}
        with patch.object(discovery, 'build_queries', return_value=queries), patch.object(api, 'post_json', side_effect=empty) as post:
            report = self.run_pipeline()
        self.assertEqual(post.call_count, 16)
        self.assertEqual(report['query_coverage']['completed'], 16)
        self.assertEqual(report['query_coverage']['uncovered_queries'], [])
        self.assertLessEqual(report['total_credits_accounted'], 100)
        self.assertTrue(all(1 <= call.args[1]['limit'] <= 50 for call in post.call_args_list))

    def test_productive_saturated_query_expands_then_duplicate_only_stops(self):
        self.settings['max_queries_per_day'] = 2
        queries = discovery.build_queries(self.preferences)[:1]
        def respond(url, payload, *args, **kwargs):
            if url.endswith('/search'):
                return {'success': True, 'creditsUsed': estimated_cost('search', payload, self.settings),
                        'data': {'web': [{'title': 'Paid Search Manager - Remote', 'url': fixtures.URL + f'?utm_source={i}'} for i in range(payload['limit'])]}}
            return {'success': True, 'creditsUsed': 1, 'data': fixtures.page()}
        with patch.object(discovery, 'build_queries', return_value=queries), \
             patch.object(api, 'post_json', side_effect=respond) as post:
            report = self.run_pipeline()
            again = self.run_pipeline()
        searches = [call.args[1] for call in post.call_args_list if call.args[0].endswith('/search')]
        self.assertEqual([s['limit'] for s in searches], [50, 100])
        self.assertEqual(report['pagination']['expansion_requests'], 1)
        self.assertFalse(report['pagination']['supported'])
        self.assertEqual(report['new_qualified'], 1)
        self.assertGreater(report['duplicate_rate'], 0)
        self.assertEqual(again['status'], 'already_complete')

    def test_domain_expansion_uses_supported_exclusions_after_limit_100(self):
        self.settings['max_queries_per_day'] = 2
        query = {'key': 'root', 'query': 'paid search remote'}
        payload = {'query': query['query'], 'limit': 100, 'sources': ['web']}
        with self.history.connect() as con:
            con.execute("INSERT INTO queries VALUES(?,?,?,'complete',?,?)", ('2026-10-21', 'root', query['query'], json.dumps([{'url': fixtures.URL}] * 100), json.dumps({'parent_key': 'root', 'depth': 1, 'requested_limit': 100, 'new_candidates': 1, 'search_credits': 20, 'payload': payload})))
            con.execute("INSERT INTO candidates(key,canonical_url,original_url,first_at,last_at,verification_status,query_key,qualified_at,search_json) VALUES('c',?,?,?,?,'validated','root',?,'{}')", (fixtures.URL, fixtures.URL, fixtures.NOW.isoformat(), fixtures.NOW.isoformat(), fixtures.NOW.isoformat()))
        work = next_work(self.history, [query], '2026-10-21', fixtures.NOW - timedelta(hours=96), fixtures.NOW, discovery.ZONE)
        self.assertEqual(work['kind'], 'domain_expansion')
        self.assertEqual(work['payload']['excludeDomains'], ['jobs.lever.co'])
        self.assertEqual(work['payload']['limit'], 50)
        self.assertNotIn('offset', work['payload'])
        estimated_cost('search', work['payload'], self.settings)

    def test_daily_query_limit_stops_new_paid_requests_with_categories_remaining(self):
        self.patches[0].stop()
        self.settings['max_queries_per_day'] = 2
        queries = [{'key': str(i), 'query': f'marketing category {i} remote'} for i in range(4)]
        def empty(url, payload, *args, **kwargs):
            return {'success': True, 'creditsUsed': estimated_cost('search', payload, self.settings),
                    'data': {'web': []}}
        with patch.object(discovery, 'build_queries', return_value=queries), \
             patch.object(api, 'post_json', side_effect=empty) as post:
            result = self.run_pipeline()
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result['status'], 'budget_limited')
        self.assertEqual(len(result['query_coverage']['uncovered_queries']), 2)

    def test_interrupted_cached_query_resumes_without_new_query_at_limit(self):
        self.settings['max_queries_per_day'] = 1
        query = {'key': 'root', 'query': 'paid search remote'}
        payload = {'query': query['query'], 'limit': 10, 'sources': ['web']}
        with self.history.connect() as con:
            con.execute("INSERT INTO queries VALUES(?,?,?,'retrieved',?,?)", (
                '2026-10-21', 'root', query['query'], '[]', json.dumps({'payload': payload})))
        work = next_work(self.history, [query], '2026-10-21',
                         fixtures.NOW - timedelta(hours=96), fixtures.NOW, discovery.ZONE)
        self.assertEqual(work['key'], 'root')
        self.assertEqual(work['payload'], payload)

    def test_price_increase_reduces_depth_and_unsupported_pagination_is_rejected(self):
        query = {'key': 'root', 'query': 'paid search remote'}
        self.settings['pricing']['search_per_10_results'] = 40
        work = next_work(self.history, [query], '2026-10-21', fixtures.NOW - timedelta(hours=96), fixtures.NOW, discovery.ZONE)
        self.assertEqual(work['payload']['limit'], 10)
        with self.assertRaises(ProviderError):
            estimated_cost('search', {**work['payload'], 'offset': 50}, self.settings)

    def test_mandatory_fee_is_preserved_but_not_counted_as_qualified(self):
        with patch.object(api, 'post_json', side_effect=fixtures.SmartDiscoveryTests.transport(self, fixtures.page(applicationFee={'required': True, 'value': 25}))):
            report = self.run_pipeline()
        self.assertEqual(report['new_qualified'], 0)
        self.assertTrue(self.store.all()[0].details['fields']['application_fee_required'])

    def test_incomplete_description_stays_review_without_extra_scrapes(self):
        data = fixtures.page(); data['markdown'] += '\nRead more'
        with patch.object(api, 'post_json', side_effect=fixtures.SmartDiscoveryTests.transport(self, data)) as post:
            report = self.run_pipeline(); self.run_pipeline()
        self.assertEqual(report['new_qualified'], 0); self.assertEqual(post.call_count, 2)
        self.assertEqual(self.store.all(), [])
        with self.history.connect() as con:
            row = con.execute('SELECT verification_status,raw_json FROM candidates').fetchone()
        self.assertEqual(row['verification_status'], 'review')
        self.assertIn('Read more', row['raw_json'])


if __name__ == '__main__': unittest.main()
