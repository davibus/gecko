"""All Firecrawl, balance and Sheets responses are mocked; no paid calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import firecrawl_discovery as discovery
import firecrawl_state as state
import query_provenance
from firecrawl_state import History, estimated_cost, request_key
from sources import firecrawl as api
from sources.base import ProviderError
from models import RawListing
from normalize import normalize
from storage import JobStore
from tests.test_google_tracker import FakeSheets
from google_tracker import GoogleTracker, Config

NOW = datetime(2026, 10, 21, 15, tzinfo=timezone.utc)
URL = 'https://jobs.lever.co/acme/abc-123'
DESCRIPTION = ' '.join(['Manage paid search campaigns, PPC advertising budgets, Google Ads optimization, marketing analytics and performance reporting.'] * 30)
SEARCH = {'query': 'paid search jobs remote', 'limit': 10, 'sources': ['web']}
SCRAPE = {'url': URL, 'formats': ['rawHtml', 'markdown'], 'proxy': 'basic', 'parsers': []}


def page(posted=None, **overrides):
    item = {'@type': 'JobPosting', 'title': 'Paid Search Manager',
            'hiringOrganization': {'name': 'Acme'}, 'identifier': {'value': 'abc-123'},
            'jobLocationType': 'TELECOMMUTE', 'jobLocation': {'address': {'addressCountry': 'US'}},
            'employmentType': 'FULL_TIME', 'description': DESCRIPTION,
            'datePosted': posted if posted is not None else (NOW - timedelta(hours=12)).isoformat()}
    item.update(overrides)
    return {'rawHtml': '<script type="application/ld+json">' + json.dumps(item) + '</script>',
            'markdown': DESCRIPTION, 'metadata': {'statusCode': 200, 'url': URL}}


class SmartDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings = deepcopy(state.config())
        self.settings.update(enabled=True, daily_enabled=True, max_queries_per_day=1, daily_soft_credits=100)
        self.history = History(self.root / 'history.sqlite', self.settings)
        self.history.record_balance({'remainingCredits': 5000}, now=NOW)
        self.store = JobStore(self.root / 'jobs.sqlite'); self.addCleanup(self.store.close)
        self.preferences = {'target_roles': ['Paid Search Manager', 'PPC Manager'], 'preferred_locations': ['Utah', 'remote']}
        build = discovery.build_queries
        remember_queries = query_provenance.remember
        lookup_query = query_provenance.query_for_job
        self.patches = [patch.object(discovery, 'build_queries', side_effect=lambda p: build(p)[:self.settings['max_queries_per_day']]),
                        patch.object(query_provenance, 'remember', side_effect=lambda rows: remember_queries(rows, path=self.root/'queries.sqlite')),
                        patch.object(query_provenance, 'query_for_job', side_effect=lambda job: lookup_query(job, path=self.root/'queries.sqlite')),
                        patch.object(discovery, 'public_listing', return_value=None),
                        patch.dict(os.environ, FIRECRAWL_API_KEY='test-only'),
                        patch.object(state, 'utcnow', return_value=NOW),
                        patch.object(api, 'MIN_INTERVAL', 0), patch.object(api, '_NEXT_REQUEST', 0),
                        patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')),
                        patch.object(api, 'get_json', return_value={'success': True, 'data': {'remainingCredits': 5000}})]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)

    def client(self):
        return api.FirecrawlClient(history=self.history, settings=self.settings)

    def transport(self, scrape=None, urls=None):
        def respond(url, payload, *args, **kwargs):
            if url.endswith('/search'):
                return {'success': True, 'creditsUsed': 2, 'id': 'search-id', 'data': {'web': [
                    {'title': 'Paid Search Manager at Acme - Remote', 'url': u, 'description': 'Remote job'}
                    for u in (urls or [URL])]}}
            return {'success': True, 'creditsUsed': 1, 'data': page() if scrape is None else scrape}
        return respond

    def run_pipeline(self, **kwargs):
        return discovery.run_discovery(self.store, self.preferences, history=self.history,
                                       client=self.client(), now=NOW, publish=False, **kwargs)

    def test_search_first_valid_job_and_found_using(self):
        with patch.object(api, 'post_json', side_effect=self.transport()) as post:
            result = self.run_pipeline()
        self.assertEqual(result['new_qualified'], 1)
        self.assertEqual(post.call_count, 2)
        self.assertNotIn('scrapeOptions', post.call_args_list[0].args[1])
        self.assertIn('cdr:1', post.call_args_list[0].args[1]['tbs'])
        self.assertEqual(self.store.all()[0].found_using, 'Firecrawl')
        self.assertEqual(result['provider_confirmed_credits'], 3)

    def test_alias_urls_are_deduplicated_before_scraping(self):
        urls = [URL + '?utm_source=x', URL + '/apply', URL + '#details']
        with patch.object(api, 'post_json', side_effect=self.transport(urls=urls)) as post:
            result = self.run_pipeline()
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result['new_qualified'], 1)
        self.assertEqual(result['previously_seen'], 2)

    def test_gecko_and_firecrawl_keep_original_and_skip_extraction(self):
        existing = normalize(RawListing('lever', 'abc-123', URL, 'Paid Search Manager', 'Acme', location='Remote', description=DESCRIPTION))
        ident = self.store.save(existing)
        with patch.object(api, 'post_json', side_effect=self.transport()) as post:
            result = self.run_pipeline()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['new_qualified'], 0)
        self.assertEqual(self.store.get(ident).found_using, 'Gecko')

    def test_four_day_window_includes_exact_cutoff(self):
        cutoff = NOW - timedelta(hours=96)
        self.assertEqual(discovery.posting_date(cutoff.isoformat(), NOW, cutoff)[0], 'recent')
        self.assertEqual(discovery.posting_date((cutoff - timedelta(microseconds=1)).isoformat(), NOW, cutoff)[0], 'old')

    def test_old_job_is_not_added(self):
        with patch.object(api, 'post_json', side_effect=self.transport(page((NOW - timedelta(hours=97)).isoformat()))):
            result = self.run_pipeline()
        self.assertEqual(result['excluded_age'], 1)
        self.assertEqual(self.store.all(), [])

    def test_missing_invalid_modified_and_future_dates_stay_review(self):
        for value in ('', 'invalid', (NOW + timedelta(days=1)).isoformat()):
            with self.subTest(value=value):
                self.assertEqual(discovery.posting_date(value, NOW, NOW - timedelta(hours=96))[0], 'unknown')
        with patch.object(api, 'post_json', side_effect=self.transport(page('', dateModified=NOW.isoformat()))):
            result = self.run_pipeline()
        self.assertEqual(result['new_qualified'], 0)
        with self.history.connect() as con:
            self.assertEqual(con.execute('SELECT verification_status FROM candidates').fetchone()[0], 'review')

    def test_date_only_cutoff_day_is_not_fabricated(self):
        cutoff = NOW - timedelta(hours=96)
        self.assertEqual(discovery.posting_date(cutoff.date().isoformat(), NOW, cutoff)[0], 'unknown')

    def test_reposted_old_identity_survives_tracker_reset(self):
        discovery.remember(self.history, URL, 'old_applied_archive')
        # No current jobs or tracker rows exist, yet the identity survives.
        with patch.object(api, 'post_json', side_effect=self.transport()) as post:
            result = self.run_pipeline()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['new_qualified'], 0)

    def test_completed_daily_run_and_resume_attempt_do_not_repeat_spending(self):
        with patch.object(api, 'post_json', side_effect=self.transport()) as post:
            first = self.run_pipeline()
            second = self.run_pipeline()
            # A separate caller asking for the same extraction reuses the cache.
            payload = post.call_args_list[-1].args[1]
            self.client().call('scrape', payload)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(second['status'], 'already_complete')
        self.assertEqual(first['new_job_ids'], second['new_job_ids'])

    def test_interruption_after_paid_response_reuses_cached_search(self):
        original = discovery.remember
        with patch.object(api, 'post_json', side_effect=self.transport()) as post:
            with patch.object(discovery, 'remember', side_effect=RuntimeError('simulated crash')):
                with self.assertRaises(RuntimeError):
                    self.run_pipeline()
            result = self.run_pipeline()
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result['new_qualified'], 1)

    def test_restart_with_pending_unknown_candidates_uses_no_repeated_search(self):
        self.settings['max_unknown_date_verifications_per_day'] = 0
        with patch.object(api, 'post_json', side_effect=self.transport()) as post:
            self.run_pipeline()
            # Simulate interrupted day, with saved candidates and complete query.
            with self.history.connect() as con:
                con.execute("UPDATE runs SET status='paused'")
            self.settings['max_unknown_date_verifications_per_day'] = 1
            result = self.run_pipeline()
        self.assertEqual(post.call_count, 2)
        self.assertEqual(result['new_qualified'], 1)

    def test_soft_budget_stops_without_priority_and_hard_never_intentionally_exceeded(self):
        self.settings.update(daily_soft_credits=4, daily_hard_credits=6)
        self.history.reserve('search', SEARCH, now=NOW)
        with self.assertRaisesRegex(ProviderError, 'hard daily'):
            self.history.reserve('scrape', SCRAPE, now=NOW)
        self.settings['daily_hard_credits'] = 20
        with self.assertRaisesRegex(ProviderError, 'soft target'):
            self.history.reserve('scrape', SCRAPE, now=NOW)

    def test_concurrent_reservations_use_one_transactional_budget(self):
        self.settings.update(daily_soft_credits=20, daily_hard_credits=20)
        def reserve(index):
            history = History(self.history.path, self.settings)
            try:
                return history.reserve('scrape', {**SCRAPE, 'url': URL + str(index)}, now=NOW)
            except ProviderError:
                return None
        with ThreadPoolExecutor(max_workers=10) as pool:
            accepted = list(pool.map(reserve, range(20)))
        self.assertEqual(sum(v is not None for v in accepted), 6)
        self.assertEqual(self.history.usage('2026-10-21')['total_credits_accounted'], 18)

    def test_same_request_is_not_reserved_by_two_workers(self):
        self.history.reserve('scrape', SCRAPE, now=NOW)
        with self.assertRaisesRegex(ProviderError, 'in flight'):
            self.history.reserve('scrape', SCRAPE, now=NOW)

    def test_failure_keeps_reservation_and_does_not_retry(self):
        with patch.object(api, 'post_json', side_effect=ProviderError('HTTP 429')) as post:
            for _ in range(2):
                with self.assertRaises(ProviderError):
                    self.client().call('search', SEARCH)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(self.history.usage('2026-10-21')['estimated_or_reserved_credits'], 4)

    def test_uncertain_inflight_reservation_survives_restart_and_midnight(self):
        self.history.reserve('search', SEARCH, now=NOW)
        restarted = History(self.history.path, self.settings)
        with self.assertRaises(ProviderError):
            restarted.reserve('search', SEARCH, now=NOW + timedelta(days=1))
        self.assertEqual(restarted.usage('2026-10-21')['estimated_or_reserved_credits'], 4)

    def test_missing_provider_usage_retains_conservative_cost(self):
        with patch.object(api, 'post_json', return_value={'success': True, 'data': {}}):
            self.client().call('search', SEARCH)
        result = self.history.usage('2026-10-21')
        self.assertFalse(result['billing_complete'])
        self.assertEqual(result['total_credits_accounted'], 4)
        self.assertEqual(result['provider_confirmed_credits'], 0)

    def test_pricing_changes_are_used_before_reservation(self):
        self.settings['pricing']['search_per_10_results'] = 7
        self.assertEqual(estimated_cost('search', {**SEARCH, 'limit': 11}, self.settings), 14)
        ident = self.history.reserve('search', SEARCH, now=NOW)
        with self.history.connect() as con:
            self.assertEqual(con.execute('SELECT reserved FROM requests WHERE id=?', (ident,)).fetchone()[0], 9)

    def test_unexpected_provider_charge_blocks_future_requests(self):
        ident = self.history.reserve('search', SEARCH, now=NOW)
        self.history.settle(ident, {'success': True, 'creditsUsed': 12, 'data': {}}, now=NOW)
        self.history.record_balance({'remainingCredits': 4988}, now=NOW)
        with self.assertRaisesRegex(ProviderError, 'pricing needs review'):
            self.history.reserve('scrape', SCRAPE, now=NOW)

    def test_account_allocation_does_not_override_lower_live_balance(self):
        self.history.record_balance({'remainingCredits': 1}, now=NOW)
        with self.assertRaisesRegex(ProviderError, 'account balance'):
            self.history.reserve('scrape', SCRAPE, now=NOW)

    def test_incomplete_account_balance_fails_closed(self):
        with self.assertRaises(ProviderError):
            self.history.record_balance({'planCredits': 5000}, now=NOW)

    def test_costly_endpoints_and_options_are_rejected_before_post(self):
        for endpoint, payload in [('crawl', {}), ('search', {**SEARCH, 'scrapeOptions': {}}),
                                  ('scrape', {**SCRAPE, 'proxy': 'auto'}),
                                  ('scrape', {**SCRAPE, 'formats': [{'type': 'json'}]})]:
            with self.subTest(endpoint=endpoint, payload=payload), patch.object(api, 'post_json') as post:
                with self.assertRaises((ProviderError, TypeError)):
                    self.client().call(endpoint, payload)
                post.assert_not_called()

    def test_publishing_retry_and_inserted_columns_preserve_existing_data(self):
        with patch.object(api, 'post_json', side_effect=self.transport()) as post:
            self.run_pipeline()
            fake = FakeSheets()
            for row in fake.data['Job Scout']:
                is_header = row is fake.data['Job Scout'][0]
                row.insert(0, 'Job Description' if is_header else 'Manual description')
                row.insert(5, 'Found Using' if is_header else 'Manual source')
            before = list(fake.data['Job Scout'][1])
            remote = GoogleTracker(Config('test', Path('unused'), 'Job Tracker', 'Job Scout'), fake)
            with patch('sheet_sync.ensure_frozen_headers'):
                failed = Mock(); failed.scout.side_effect = RuntimeError('Sheets offline')
                with self.assertRaises(RuntimeError):
                    discovery.flush_pending(history=self.history, remote=failed, store=self.store)
                published = discovery.flush_pending(history=self.history, remote=remote, store=self.store)
                discovery.flush_pending(history=self.history, remote=remote, store=self.store)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(published['jobs'], 1)
        self.assertEqual(len(remote.scout().rows), 2)
        self.assertEqual(remote.scout().rows[-1][1]['Found Using'], 'Firecrawl')
        self.assertEqual(remote.scout().rows[-1][1]['Job Description'], self.store.all()[0].description)
        self.assertEqual(fake.data['Job Scout'][1], before)

    def test_disabled_feature_never_opens_ledger_or_calls_api(self):
        settings = {**self.settings, 'enabled': False}
        with patch.object(discovery, 'config', return_value=settings), patch.object(discovery, 'History') as ledger:
            self.assertEqual(discovery.run_discovery(self.store, self.preferences)['status'], 'disabled')
            ledger.assert_not_called()

    def test_scraping_gecko_discovery_does_not_relabel_the_source(self):
        raw = RawListing('linkedin', '123', URL, 'Paid Search Manager', 'Acme',
                         metadata={'_discovered_via': 'brave', '_retrieved_via': 'firecrawl'})
        self.assertEqual(normalize(raw).found_using, 'Gecko')
        raw.metadata['_discovered_via'] = 'firecrawl-search'
        self.assertEqual(normalize(raw).found_using, 'Firecrawl')

    def test_archived_sheet_matrix_is_seeded_before_extraction(self):
        self.store.connection.execute('CREATE TABLE workspace_archive(payload_json TEXT)')
        self.store.connection.execute('INSERT INTO workspace_archive VALUES(?)', (json.dumps([['Job URL'], [URL]]),))
        self.store.connection.commit()
        with patch.object(api, 'post_json', side_effect=self.transport()) as post:
            result = self.run_pipeline()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['new_qualified'], 0)

    def test_structured_old_date_hint_skips_extraction(self):
        original = self.transport()
        def old_search(url, payload, *args, **kwargs):
            response = original(url, payload, *args, **kwargs)
            if url.endswith('/search'):
                response['data']['web'][0]['jobPosting'] = {'@type': 'JobPosting', 'datePosted': (NOW - timedelta(days=10)).isoformat()}
            return response
        with patch.object(api, 'post_json', side_effect=old_search) as post:
            result = self.run_pipeline()
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result['excluded_age'], 1)

    def test_cutoff_timestamp_is_used_when_ingesting(self):
        with patch.object(api, 'post_json', side_effect=self.transport(page((NOW - timedelta(hours=96)).isoformat()))):
            self.assertEqual(self.run_pipeline()['new_qualified'], 1)

    def test_explicit_employer_original_date_is_supported(self):
        data = page('')
        data['markdown'] += '\nOriginally posted on: 2026-10-20\n'
        raw, evidence, _ = discovery.extract_listing(data, URL)
        self.assertEqual(raw.date_posted, '2026-10-20')
        self.assertIn('Employer listing', evidence)

    def test_original_posting_microdata_is_supported_without_using_modified(self):
        data = page('invalid', dateModified=NOW.isoformat())
        data['rawHtml'] += '<meta itemprop="datePosted" content="2026-10-20">'
        raw, evidence, _ = discovery.extract_listing(data, URL)
        self.assertEqual(raw.date_posted, '2026-10-20')
        self.assertIn('microdata', evidence)

    def test_provider_routing_subtotal_is_not_mislabeled_as_total(self):
        ident = self.history.reserve('scrape', SCRAPE, now=NOW)
        response = {'success': True, 'data': {'metadata': {'provider': {'creditsCost': 20}}}}
        self.history.settle(ident, response, now=NOW)
        self.assertEqual(self.history.usage('2026-10-21')['provider_confirmed_credits'], 0)
        self.assertGreaterEqual(self.history.usage('2026-10-21')['total_credits_accounted'], 20)
        with self.assertRaisesRegex(ProviderError, 'routing cost'):
            self.history.reserve('search', SEARCH, now=NOW)

    def test_daily_report_is_queued_and_delivered_with_readback(self):
        import importlib.util
        path = Path(__file__).resolve().parents[2] / 'scripts/test_daily_report.py'
        spec = importlib.util.spec_from_file_location('firecrawl_report_fixture', path)
        fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
        from gecko_daily import counts_from_output, history_fields
        result = {'new_qualified': 2, 'provider_confirmed_credits': 4, 'estimated_or_reserved_credits': 3,
                  'queries': [{'query': 'paid search', 'credits': 4}]}
        counts = counts_from_output('Firecrawl efficiency: ' + json.dumps(result))
        fields = history_fields('smart-report', '2026-10-21', counts, {'lever': 2}, dry_run=False, exit_code=0)
        with patch.object(discovery, 'History', return_value=self.history):
            discovery.queue_report(fields)
        fake = fixture.FakeSheets()
        remote = SimpleNamespace(api=fake, config=SimpleNamespace(spreadsheet_id='test'),
                                 _sheet_properties=fake._sheet_properties)
        with patch('sheet_sync.ensure_frozen_headers'):
            first = discovery.flush_pending(history=self.history, remote=remote, store=self.store)
            second = discovery.flush_pending(history=self.history, remote=remote, store=self.store)
        self.assertEqual(first['reports'], 1)
        self.assertEqual(second['reports'], 0)
        actual = {r[0]: r[1] for r in fake.data['Daily Run'] if len(r) >= 2 and r[0]}
        self.assertEqual(actual['Firecrawl provider confirmed credits'], 4)
        self.assertEqual(actual['Firecrawl estimated or reserved credits'], 3)

    def test_daily_does_not_run_broad_paid_search_and_retains_resume_workflow(self):
        import scout
        from manual_indeed import ManualIndeedSummary
        events = []
        smart = {'status': 'complete', 'day': '2026-10-21', 'new_job_ids': [], 'new_qualified': 0}
        def smart_run(*args, **kwargs): events.append('smart'); return smart
        def ordinary(args, *unused):
            events.append('ordinary'); args.run_result = {'new_job_ids': []}; return 0
        queue = SimpleNamespace(snapshot=SimpleNamespace(pending=[], already_created=[]), created=0,
                                failures=[], successes=[], recovered=0, exit_code=0)
        args = scout.build_parser().parse_args(['daily'])
        fake_store = Mock()
        with patch.object(state, 'config', return_value=self.settings), \
                patch.object(discovery, 'run_discovery', side_effect=smart_run), \
                patch.object(scout, 'search', side_effect=ordinary), \
                patch.object(scout, 'GoogleTracker'), \
                patch.object(scout, 'process_manual_indeed_rows', return_value=ManualIndeedSummary()), \
                patch.object(scout, '_daily_resume_runner', return_value=queue) as resumes, \
                patch.object(scout, '_daily_gmail_response_runner', return_value=(None, '')), \
                patch.object(scout, '_print_daily_summary'):
            self.assertEqual(scout.daily(args, fake_store, self.preferences), 0)
        self.assertEqual(events, ['ordinary'])
        resumes.assert_called_once()

    def test_distinct_ats_requisitions_are_not_merged_by_shared_title(self):
        existing = normalize(RawListing('lever', 'different-id', 'https://jobs.lever.co/acme/different-id',
                                       'Paid Search Manager', 'Acme', location='US', remote_type='remote',
                                       description=DESCRIPTION))
        self.store.save(existing)
        with patch.object(api, 'post_json', side_effect=self.transport()):
            self.assertEqual(self.run_pipeline()['new_qualified'], 1)
        self.assertEqual(len(self.store.all()), 2)

    def test_idle_sync_delivers_outbox_and_updates_local_cache_without_paid_calls(self):
        import sheet_sync
        from sqlite_tracker import SCHEMA
        fake = FakeSheets()
        fake.data['Job List'] = fake.data.pop('Job Scout')
        for row in fake.data['Job List']:
            first = row is fake.data['Job List'][0]
            row.insert(5, 'Found Using' if first else '')
            row.append('Job Description' if first else '')
        remote = GoogleTracker(Config('test', Path('unused'), 'Job Tracker', 'Job List'), fake)
        tab = remote.scout()
        baseline = {h: tab.rows[0][1].get(h, '') for h in tab.header_values}
        self.store.connection.executescript(SCHEMA)
        self.store.connection.execute("INSERT INTO workspace_datasets(name,headers_json,source_id) VALUES('Job List',?,1)", (json.dumps(list(tab.header_values)),))
        self.store.connection.execute("INSERT INTO workspace_records(dataset,slot,values_json) VALUES('Job List',2,?)", (json.dumps(baseline),))
        self.store.connection.commit()
        state_path = self.root / 'sync-state.json'
        state_path.write_text(json.dumps({'spreadsheet_id': 'test', 'rows': {'42': baseline}}))
        with patch.object(api, 'post_json', side_effect=self.transport()) as post:
            result = self.run_pipeline()
            with patch.object(discovery, 'DATABASE', self.history.path), \
                    patch.object(state, 'DATABASE', self.history.path), \
                    patch.object(sheet_sync, 'DATABASE', self.store.path), \
                    patch.object(sheet_sync, 'STATE', state_path), \
                    patch.object(sheet_sync, 'STATUS', self.root / 'sync-status.json'), \
                    patch('google_tracker.GoogleTracker', return_value=remote), \
                    patch('storage.JobStore', side_effect=lambda: JobStore(self.store.path)), \
                    patch('google_tracker.Config.from_environment'), \
                    patch('google_tracker.load_environment'), \
                    patch.object(sheet_sync, 'ensure_frozen_headers'):
                sheet_sync.sync()
                sheet_sync.sync()
        self.assertEqual(post.call_count, 2)
        self.assertEqual(len(remote.scout().rows), 2)
        rows = self.store.connection.execute("SELECT values_json FROM workspace_records WHERE dataset='Job List'").fetchall()
        new = [json.loads(r[0]) for r in rows if str(json.loads(r[0])['ID']) == str(result['new_job_ids'][0])]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]['Found Using'], 'Firecrawl')
        self.assertTrue(new[0]['Job Description'])


if __name__ == '__main__':
    unittest.main()
