"""Real discovery/dedup/writer orchestration with isolated stores and fake APIs."""
from contextlib import nullcontext, redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.append(str(Path(__file__).resolve().parents[2] / 'scripts'))
import scout
import unified_search as unified
from tests import test_firecrawl_discovery as fixtures
from tests.test_google_tracker import FakeSheets
from google_tracker import GoogleTracker, Config
from models import RawListing
from normalize import normalize, posting_aliases, posting_identity
from sources.base import ProviderError
import gecko


INTERNAL = 'https://careers.acme.example/jobs/internal-1'


class Provider:
    def __init__(self, listings): self.listings = listings; self.calls = 0
    def configured(self): return True
    def search(self, request): self.calls += 1; return self.listings


class UnifiedTests(unittest.TestCase):
    client = fixtures.SmartDiscoveryTests.client

    def setUp(self):
        fixtures.SmartDiscoveryTests.setUp(self)
        self.fake = FakeSheets()
        self.fake.data['Job List'] = self.fake.data.pop('Job Scout')
        for row in self.fake.data['Job List']:
            row.extend(['Found Using', 'Job Description', 'Company Website'] if row is self.fake.data['Job List'][0] else ['Referral', '', ''])
        self.remote = GoogleTracker(Config('test', Path('unused'), 'Job Tracker', 'Job List'), self.fake)
        self.providers = {'lever': Provider([RawListing('lever', 'internal-1', INTERNAL, 'Paid Search Manager', 'Acme', location='Remote', remote_type='remote', description=fixtures.DESCRIPTION)]),
                          'greenhouse': Provider([])}
        validator = Mock(require_verified=True)
        validator.check.return_value = SimpleNamespace(status='valid', reason='verified')
        self.report_writer = Mock(return_value=(3, 10))
        # Keep the report date on the same day as the mocked credit ledger.
        clock = Mock(wraps=fixtures.datetime)
        clock.now.return_value = fixtures.NOW.astimezone(unified.ZONE)
        patches = [patch.object(unified, 'PENDING', self.root / 'pending.json'),
                   patch.object(unified, 'datetime', clock),
                   patch.object(unified, 'REPORTS', self.root / 'reports'),
                   patch.object(unified, 'DATABASE', self.history.path),
                   patch.object(unified, 'History', return_value=self.history),
                   patch.object(unified, 'config', return_value=self.settings),
                   patch.object(unified, 'GoogleTracker', return_value=self.remote),
                   patch.object(scout, 'GoogleTracker', return_value=self.remote),
                   patch.object(scout, 'providers', return_value=self.providers),
                   patch.object(scout, 'DailyLinkValidator', return_value=validator),
                   patch.object(scout, 'PROJECT_ROOT', self.root),
                   patch('sheet_sync.sync', return_value={}), patch('sheet_sync.ensure_frozen_headers'),
                   patch('run_gecko.run_lock', side_effect=nullcontext),
                   patch('daily_run_history.write_history', self.report_writer),
                   patch.object(scout, '_daily_resume_runner', side_effect=AssertionError('No resume workflow')),
                   patch.object(scout, '_daily_gmail_response_runner', side_effect=AssertionError('No Gmail workflow')),
                   patch.object(unified, 'flush_pending', side_effect=lambda **kwargs: fixtures.discovery.flush_pending(history=self.history, **kwargs))]
        for p in patches: p.start(); self.addCleanup(p.stop)

    def run_search(self, **overrides):
        args = scout.build_parser().parse_args(['search', '--source', 'all', '--unified', '--broad-discovery'])
        for k,v in overrides.items(): setattr(args,k,v)
        with redirect_stdout(io.StringIO()): return scout.search(args, self.store, self.preferences)

    def smart(self, store, preferences, **kwargs):
        return fixtures.discovery.run_discovery(store, preferences, history=self.history,
                  client=self.client(), now=fixtures.NOW, **kwargs)

    def test_complete_unified_path_merges_sources_preserves_data_and_reports_once(self):
        def respond(url, payload, *unused, **kwargs):
            if url.endswith('/search'):
                return {'success': True, 'creditsUsed': 2, 'data': {'web': [
                    {'title': 'Paid Search Manager - Remote', 'url': INTERNAL},
                    {'title': 'Paid Search Manager - Remote', 'url': fixtures.URL}]}}
            return {'success': True, 'creditsUsed': 1, 'data': fixtures.page(hiringOrganization={'name': 'BrightCo'}, workHours='35 hours per week')}
        with patch.object(unified, 'run_discovery', side_effect=self.smart), patch.object(fixtures.api, 'post_json', side_effect=respond) as paid:
            self.assertEqual(self.run_search(), 0)
            self.assertEqual(self.run_search(sync_only=True), 0)
        self.assertEqual(paid.call_count, 2)
        self.assertTrue(all(p.calls for p in self.providers.values()))
        rows = [v for _,v in self.remote.scout().rows]
        jobs = [v for v in rows if v['Company'] in {'Acme','BrightCo'}]
        self.assertEqual(len(jobs), 2)
        self.assertEqual({v['Company']:v['Found Using'] for v in jobs}, {'Acme':'Gecko','BrightCo':'Firecrawl'})
        for row in jobs: self.assertEqual(row['Job Description'], fixtures.DESCRIPTION + ('\n\n## Work hours\n\n35 hours per week' if row['Company']=='BrightCo' else ''))
        bright = next(j for j in self.store.all() if j.company=='BrightCo')
        self.assertEqual(bright.details['fields']['work_hours'], '35 hours per week')
        self.assertEqual(self.report_writer.call_count, 1)
        fields = self.report_writer.call_args.args[1]
        self.assertEqual(fields['New Unique Jobs'], 2)
        self.assertEqual(fields['Run Date'], fixtures.NOW.astimezone(unified.ZONE).date().isoformat())
        self.assertEqual(json.loads(fields['Firecrawl Discovery'])['provider_confirmed_credits'], 3)
        self.assertTrue(all(not isinstance(v,(dict,list)) for k,v in fields.items() if k!='Jobs by Source'))

    def test_disabled_firecrawl_does_not_block_all_internal_providers(self):
        self.settings.update(enabled=False, daily_enabled=False)
        with patch.object(unified, 'run_discovery') as smart:
            self.assertEqual(self.run_search(), 0)
        smart.assert_not_called()
        self.assertTrue(all(p.calls for p in self.providers.values()))
        self.assertEqual(len(self.remote.scout().rows), 2)

    def test_unavailable_firecrawl_keeps_internal_jobs_and_reports_failure(self):
        with patch.object(unified, 'run_discovery', side_effect=ProviderError('Firecrawl unavailable')):
            self.assertEqual(self.run_search(), 0)
        self.assertEqual(len(self.remote.scout().rows), 2)
        self.assertEqual(json.loads(self.report_writer.call_args.args[1]['Firecrawl Discovery'])['status'], 'unavailable')

    def test_manual_values_survive_while_blank_description_is_enriched(self):
        row = self.fake.data['Job List'][1]; headers=self.fake.data['Job List'][0]
        row[headers.index('Job URL')] = INTERNAL
        row[headers.index('Company')] = 'Acme'
        row[headers.index('Job Title')] = 'Paid Search Manager'
        row[headers.index('Salary')] = 'Manual salary'
        row[headers.index('Notes')] = 'Keep manual notes'
        self.settings.update(enabled=False, daily_enabled=False)
        self.assertEqual(self.run_search(), 0)
        values = dict(self.remote.scout().rows)[2]
        self.assertEqual(values['Salary'], 'Manual salary')
        self.assertEqual(values['Notes'], 'Keep manual notes')
        self.assertEqual(values['Found Using'], 'Referral')
        self.assertEqual(values['Job Description'], fixtures.DESCRIPTION)
        self.assertEqual(len(self.remote.scout().rows), 1)
        self.assertEqual(self.store.all()[0].id, 42)
        self.assertEqual(self.report_writer.call_args.args[1]['New Unique Jobs'], 0)

    def test_sheet_outage_retains_pending_and_sync_only_retries_without_spending(self):
        self.settings.update(enabled=False, daily_enabled=False)
        deliver = unified.deliver
        with patch.object(unified, 'deliver', side_effect=OSError('Sheets unavailable')):
            self.assertEqual(self.run_search(), 0)
        self.assertTrue(unified._pending()['job_ids'])
        calls = sum(p.calls for p in self.providers.values())
        with patch.object(unified, 'run_discovery', side_effect=AssertionError('No Firecrawl retry')):
            self.assertEqual(self.run_search(sync_only=True), 0)
        self.assertEqual(sum(p.calls for p in self.providers.values()), calls)
        self.assertEqual(unified._pending(), {'job_ids': [], 'reports': []})

    def test_primary_source_url_matches_saved_posting_after_employer_redirect(self):
        self.settings.update(enabled=False, daily_enabled=False)
        headers = self.fake.data['Job List'][0]
        row = self.fake.data['Job List'][1]
        row[headers.index('Job URL')] = INTERNAL
        row[headers.index('Company')] = 'Acme'
        row[headers.index('Job Title')] = 'Paid Search Manager'
        saved = normalize(self.providers['lever'].listings[0])
        saved.url = saved.canonical_url = 'https://employer.example/jobs/redirected'
        self.store.save(saved, job_id=42)
        with patch.object(unified, 'run_discovery'):
            self.assertEqual(self.run_search(), 0)
        self.assertEqual([job.id for job in self.store.all()], [42])
        self.assertEqual(self.report_writer.call_args.args[1]['New Unique Jobs'], 0)
        self.assertEqual(len(self.remote.scout().rows), 1)

    def test_primary_id_conflict_still_rejects_unrelated_posting(self):
        self.settings.update(enabled=False, daily_enabled=False)
        headers = self.fake.data['Job List'][0]
        self.fake.data['Job List'][1][headers.index('Job URL')] = INTERNAL
        other = RawListing('lever', 'different', 'https://other.example/jobs/different',
                           'Paid Search Manager', 'Other', location='Remote',
                           description=fixtures.DESCRIPTION)
        self.store.save(normalize(other), job_id=42)
        with self.assertRaisesRegex(RuntimeError, 'Primary ID 42 conflicts'):
            self.run_search()
        self.assertEqual(self.store.get(42).company, 'Other')
        self.report_writer.assert_not_called()

    def test_publication_preserves_successful_description_source_alias(self):
        self.settings.update(enabled=False, daily_enabled=False)
        resolved = 'https://employer.example/jobs/verified-description'
        headers = self.fake.data['Job List'][0]
        row = self.fake.data['Job List'][1]
        row[headers.index('Job URL')] = resolved
        row[headers.index('Company')] = 'Acme'
        row[headers.index('Job Title')] = 'Paid Search Manager'
        saved = normalize(self.providers['lever'].listings[0])
        self.store.save(saved, job_id=42)
        saved.id = 42
        saved.enriched_source_url = resolved
        saved.enrichment_status = 'succeeded'
        self.store.save_enrichment(saved)
        self.assertEqual(self.run_search(), 0)
        self.assertEqual(dict(self.remote.scout().rows)[2]['Job URL'], resolved)
        self.assertEqual(unified._pending(), {'job_ids': [], 'reports': []})

    def test_failed_enrichment_url_does_not_establish_posting_identity(self):
        saved = normalize(self.providers['lever'].listings[0])
        saved.enriched_source_url = 'https://unverified.example/job'
        saved.enrichment_status = 'failed'
        self.assertNotIn(posting_identity(saved.enriched_source_url), posting_aliases(saved))

    def test_oversized_sheet_report_retains_audit_reference_without_mutating_original(self):
        fields = {'Run ID': 'search:example', 'New Unique Jobs': 10,
                  'Gecko Discovery': ('"\n' * 100000)}
        compact = unified._sheet_report_fields(fields)
        self.assertLessEqual(len(compact['Gecko Discovery']), 45000)
        self.assertEqual(compact['New Unique Jobs'], 10)
        summary = json.loads(compact['Gecko Discovery'])
        self.assertEqual(summary['original_characters'], 200000)
        self.assertEqual(summary['full_audit'], str(unified.REPORTS / 'search-example.json'))
        self.assertEqual(len(fields['Gecko Discovery']), 200000)

    def test_incomplete_context_uses_existing_enrichment_without_manual_overwrites(self):
        self.settings.update(enabled=False, daily_enabled=False)
        self.providers['lever'].listings[0].description = 'Short job description'
        def enrich(job, store):
            job.enriched_description=fixtures.DESCRIPTION; job.enrichment_status='succeeded'; store.save_enrichment(job)
        with patch('service._capture_full_description', side_effect=enrich) as enrich_call:
            self.assertEqual(self.run_search(), 0)
        enrich_call.assert_called_once()
        self.assertEqual(dict(self.remote.scout().rows)[3]['Job Description'], fixtures.DESCRIPTION)

    def test_router_forwards_all_source_unified_and_preserves_legacy_parser(self):
        with patch.object(scout, 'main', return_value=0) as route:
            self.assertEqual(gecko.main(['job','search','--dry-run']), 0)
        self.assertEqual(route.call_args.args[0], ['search','--source','all','--unified','--results','20','--dry-run'])
        self.assertFalse(scout.build_parser().parse_args(['search']).unified)
        self.assertEqual(self.settings['daily_soft_credits'], 100)
        self.assertEqual(self.settings['daily_hard_credits'], 2000)
        self.assertEqual(self.settings['posting_window_hours'], 96)

    def test_plan_never_opens_store_or_calls_discovery(self):
        with patch.object(scout, 'JobStore', side_effect=AssertionError('No database')), patch.object(unified, 'run_discovery', side_effect=AssertionError('No discovery')), redirect_stdout(io.StringIO()):
            self.assertEqual(scout.main(['search','--unified','--dry-run']), 0)

    def test_repeated_unified_run_does_not_count_cached_firecrawl_jobs_as_new(self):
        with patch.object(unified, 'run_discovery', side_effect=self.smart), patch.object(fixtures.api, 'post_json', side_effect=fixtures.SmartDiscoveryTests.transport(self, fixtures.page(hiringOrganization={'name':'BrightCo'}))) as paid:
            self.assertEqual(self.run_search(), 0)
            self.assertEqual(self.run_search(), 0)
        self.assertEqual(paid.call_count, 2)
        self.assertEqual(len(self.remote.scout().rows), 3)
        self.assertEqual(self.report_writer.call_args.args[1]['New Unique Jobs'], 0)

    def test_concurrent_manual_salary_is_not_overwritten_by_blank_enrichment(self):
        self.settings.update(enabled=False, daily_enabled=False)
        headers = self.fake.data['Job List'][0]; row=self.fake.data['Job List'][1]
        row[headers.index('Job URL')] = INTERNAL
        row[headers.index('Salary')] = ''
        self.providers['lever'].listings[0].salary = 'USD 90000 per year'
        prepare = self.remote._prepare_writes
        def type_manual(*args, **kwargs):
            row[headers.index('Salary')] = 'Typed during discovery'
            return prepare(*args, **kwargs)
        with patch.object(self.remote, '_prepare_writes', side_effect=type_manual):
            self.assertEqual(self.run_search(), 0)
        self.assertEqual(dict(self.remote.scout().rows)[2]['Salary'], 'Typed during discovery')


if __name__ == '__main__': unittest.main()
