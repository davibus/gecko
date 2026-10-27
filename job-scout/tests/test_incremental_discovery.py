"""Offline durable discovery contracts; all network and inference are mocked."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from incremental_discovery import Engine
from firecrawl_state import History, config
from models import RawListing
from normalize import normalize
from rejected_jobs import RejectedJob, RejectedJobsIndex
from sources.base import ProviderError
from storage import JobStore

NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)
TEXT = 'Responsibilities: Manage paid search campaigns and Google Ads budgets. Requirements: Marketing analytics and campaign optimization experience. ' * 10


def raw(key='one', description=TEXT, source='test', url=None):
    return RawListing(source, key, url or 'https://example.test/jobs/' + key,
                      'Paid Search Manager', 'Acme', location='Remote, United States',
                      remote_type='remote', description=description)


def page(candidate):
    item = {'@type': 'JobPosting', 'title': candidate.title,
            'hiringOrganization': {'name': candidate.company},
            'identifier': {'value': candidate.source_job_id},
            'url': candidate.url, 'description': TEXT,
            'jobLocationType': 'TELECOMMUTE'}
    return {'rawHtml': '<script type="application/ld+json">' + json.dumps(item) + '</script>',
            'markdown': TEXT, 'metadata': {'url': candidate.url, 'statusCode': 200}}


class IncrementalTests(unittest.TestCase):
    def greenhouse(self, posting, internal, tenant='acme'):
        item=raw(posting,source='greenhouse',url='https://job-boards.greenhouse.io/'+tenant+'/jobs/'+posting)
        item.metadata.update(ats_company=tenant,internal_job_id=internal)
        return item

    def test_verified_internal_requisition_variants_publish_once(self):
        self.run_candidates([self.greenhouse('11',101),self.greenhouse('12',101)])
        self.assertEqual(self.publish.call_count,1)
        self.assertEqual(self.paid.call_count,0)
        self.assertEqual(len(self.store.all()),1)

    def test_retained_posting_seeds_requisition_alias_before_new_variant(self):
        original=self.greenhouse('11',101)
        # Simulate a tracker predating requisition metadata persistence.
        job=normalize(raw('11',source='greenhouse',url=original.url));self.store.save(job)
        self.run_candidates([self.greenhouse('12',101),original])
        self.publish.assert_not_called();self.paid.assert_not_called();self.review.assert_not_called()

    def test_different_requisitions_and_tenants_remain_distinct(self):
        self.run_candidates([self.greenhouse('11',101),self.greenhouse('12',102),self.greenhouse('13',101,'other')])
        self.assertEqual(self.publish.call_count,3)

    def test_new_eligible_variant_is_not_hidden_by_older_location_exclusion(self):
        outside=self.greenhouse('11',101);outside.remote_type='';outside.location='London, United Kingdom'
        self.run_candidates([outside])
        self.assertEqual(self.publish.call_count,0)
        self.run_candidates([self.greenhouse('12',101)])
        self.assertEqual(self.publish.call_count,1);self.paid.assert_not_called()

    def test_reused_public_id_with_new_internal_requisition_is_new(self):
        self.run_candidates([self.greenhouse('11',101)])
        self.run_candidates([self.greenhouse('11',102)])
        # The identity is new even when the canonical writer holds the reused
        # URL for reconciliation. Admission must not hide the new requisition.
        with self.history.connect() as con:count=con.execute('SELECT COUNT(*) FROM daily_candidates').fetchone()[0]
        self.assertEqual(count,2)

    def test_manual_pending_hold_survives_days_and_new_evidence_can_recover(self):
        engine=self.engine();key=next(iter(engine.ingest([raw(description='snippet')],{},self.rejections)))
        engine.pending(key,'Missing verified source evidence',retry=False)
        self.run_candidates([],now=NOW+timedelta(days=100))
        self.free.assert_not_called();self.paid.assert_not_called();self.review.assert_not_called()
        self.run_candidates([raw()],now=NOW+timedelta(days=101))
        self.assertEqual(self.publish.call_count,1)

    def test_new_requisition_variants_do_not_inherit_a_reused_old_public_id(self):
        self.run_candidates([self.greenhouse('11',101)])
        self.run_candidates([self.greenhouse('11',102),self.greenhouse('12',102)])
        with self.history.connect() as con:
            rows=con.execute('SELECT raw_json,published,gecko_id FROM daily_candidates').fetchall()
        newer=[r for r in rows if json.loads(r['raw_json'])['metadata']['internal_job_id']==102]
        self.assertEqual(len(newer),1)
        self.assertTrue(newer[0]['published']);self.assertNotEqual(newer[0]['gecko_id'],1)

    def test_structured_foreign_remote_and_hybrid_conflicts_hold_before_review(self):
        for candidate in [self.greenhouse('11',101),self.greenhouse('12',102)]:
            candidate.metadata.update(country='GB' if candidate.source_job_id=='11' else 'US',workplaceType='Remote' if candidate.source_job_id=='11' else 'Hybrid')
            candidate.location='London' if candidate.source_job_id=='11' else 'New York, United States'
            self.run_candidates([candidate])
        self.review.assert_not_called();self.free.assert_not_called();self.paid.assert_not_called()
        with self.history.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM daily_candidates WHERE state='pending' AND retry_mode='manual'").fetchone()[0],2)

    def test_new_country_evidence_releases_hold_without_description_change(self):
        candidate=self.greenhouse('11',101);candidate.metadata['country']='GB'
        self.run_candidates([candidate]);self.review.assert_not_called()
        candidate.metadata['country']='US'
        self.run_candidates([candidate])
        self.assertEqual(self.publish.call_count,1);self.free.assert_not_called();self.paid.assert_not_called()

    def setUp(self):
        temp = TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.settings = deepcopy(config())
        self.settings.update(enabled=True, require_balance=False, daily_soft_credits=200,
                             daily_hard_credits=200)
        self.history = History(self.root/'history.sqlite', settings=self.settings)
        self.store = JobStore(self.root/'jobs.sqlite'); self.addCleanup(self.store.close)
        self.tracker = SimpleNamespace(scout=lambda: SimpleNamespace(rows=[]))
        self.rejections = RejectedJobsIndex()
        self.free = Mock(return_value=None)
        self.review = Mock(return_value={'accepted': True, 'status': 'reviewed', 'reason': 'Evidence matched'})
        self.publish = Mock()
        self.paid = Mock(side_effect=self.charge)
        blocker = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden'))
        blocker.start(); self.addCleanup(blocker.stop)

    def charge(self, candidate, history):
        payload = {'url': candidate.url, 'formats': ['rawHtml', 'markdown'], 'proxy': 'basic', 'parsers': []}
        ident = history.reserve('scrape', payload, now=NOW)
        response = page(candidate)
        history.settle(ident, response={'success': True, 'creditsUsed': 1, 'data': response}, now=NOW)
        return response

    def engine(self, **kwargs):
        return Engine(self.history, self.store, {'target_roles': ['Paid Search Manager'], 'preferred_locations': ['Utah', 'Remote']},
                      review=self.review, free=self.free, paid=self.paid, publish=self.publish,
                      now=kwargs.pop('now', NOW), **kwargs)

    def run_candidates(self, rows, **kwargs):
        return self.engine(**kwargs).run(rows, tracker=self.tracker, rejections=self.rejections)

    def test_identical_second_daily_run_zero_paid_and_no_review(self):
        first = self.run_candidates([raw(description='snippet')])
        second = self.run_candidates([raw(description='snippet')], now=NOW+timedelta(days=1))
        self.assertEqual(first['paid_requests'], 1)
        self.assertEqual(second['paid_requests'], 0)
        self.assertEqual(second['known_jobs_skipped_before_retrieval'], 1)
        self.assertEqual(self.paid.call_count, 1)
        self.assertEqual(self.review.call_count, 1)
        self.assertEqual(len(self.store.all()), 1)

    def test_known_verified_cross_source_alias_skipped_without_fetch(self):
        job = normalize(raw())
        job.source_links.append({'source': 'partner', 'source_job_id': 'other', 'url': 'https://partner.test/post/other'})
        self.store.save(job)
        result = self.run_candidates([raw('other', 'snippet', 'partner', 'https://partner.test/post/other?utm_source=x')])
        self.assertEqual(result['known_jobs_skipped_before_retrieval'], 1)
        self.free.assert_not_called(); self.paid.assert_not_called(); self.review.assert_not_called()

    def test_complete_new_source_description_no_firecrawl(self):
        result = self.run_candidates([raw()])
        self.assertEqual(result['new_jobs_added'], 1)
        self.free.assert_not_called(); self.paid.assert_not_called()

    def test_paid_content_survives_restart_and_pending_review(self):
        self.review.return_value = {'accepted': False, 'status': 'pending', 'reason': 'Inference unavailable'}
        self.run_candidates([raw(description='snippet')])
        self.store.close()
        self.store = JobStore(self.root/'jobs.sqlite'); self.addCleanup(self.store.close)
        self.history = History(self.root/'history.sqlite', settings=self.settings)
        self.review.return_value = {'accepted': True, 'status': 'reviewed'}
        result = self.run_candidates([raw(description='snippet')], now=NOW+timedelta(days=8))
        self.assertEqual(result['new_jobs_added'], 1)
        self.assertEqual(self.paid.call_count, 1)
        self.assertEqual(result['paid_requests'], 0)

    def test_unresolved_paid_failure_never_auto_repeated(self):
        def fail(candidate, history):
            history.reserve('scrape', {'url':candidate.url, 'formats':['markdown'], 'proxy':'basic', 'parsers':[]}, now=NOW)
            raise TimeoutError('Unknown bill')
        self.paid.side_effect = fail
        self.run_candidates([raw(description='snippet')])
        self.run_candidates([raw(description='snippet')], now=NOW+timedelta(days=1))
        self.run_candidates([raw(description='snippet')], now=NOW+timedelta(days=90))
        self.assertEqual(self.paid.call_count, 1)
        self.assertEqual(self.free.call_count, 1)
        self.review.assert_not_called()
        from zoneinfo import ZoneInfo
        self.assertEqual(self.history.usage(NOW.astimezone(ZoneInfo('America/Denver')).date().isoformat())['estimated_or_reserved_credits'], 3)
        # Fresh complete free evidence can rescue the posting without another bill.
        result = self.run_candidates([raw()], now=NOW+timedelta(days=91))
        self.assertEqual(result['new_jobs_added'], 1)
        self.assertEqual(self.paid.call_count, 1)

    def test_free_failure_cooldown_and_eventual_recovery(self):
        self.free.side_effect = OSError('temporary outage')
        self.run_candidates([raw(description='snippet')])
        self.run_candidates([raw(description='snippet')], now=NOW+timedelta(days=1))
        self.assertEqual(self.free.call_count, 1)
        self.free.side_effect = None
        self.free.return_value = {'description':TEXT, 'url':raw().url}
        result = self.run_candidates([], now=NOW+timedelta(days=8))
        self.assertEqual(result['new_jobs_added'], 1)
        self.paid.assert_not_called()

    def test_all_source_aliases_deduped_before_paid(self):
        result = self.run_candidates([raw(description='snippet'), raw('partner', TEXT, 'partner', raw().url+'?utm_source=board')])
        self.assertEqual(result['new_jobs_added'], 1)
        self.paid.assert_not_called()

    def test_same_company_title_different_requisition_is_new(self):
        self.run_candidates([raw('first')])
        result = self.run_candidates([raw('second')])
        self.assertEqual(result['new_jobs_added'], 1)
        self.assertEqual(len(self.store.all()), 2)

    def test_pending_publication_recovered_with_reserved_id(self):
        self.publish.side_effect = OSError('Sheet unavailable')
        first = self.run_candidates([raw()])
        self.publish.side_effect = None
        result = self.run_candidates([])
        self.assertEqual(result['published_job_ids'], first['new_job_ids'])
        self.assertEqual(len(self.store.all()), 1)
        self.assertEqual(self.review.call_count, 1)

    def test_rejections_and_existing_fields_untouched(self):
        job = normalize(raw('kept'))
        job.status = 'resume-created'
        job_id = self.store.save(job)
        before = self.store.get(job_id).to_dict()
        self.rejections = RejectedJobsIndex([RejectedJob(source='test',job_id='no',original_url=raw('no').url)])
        self.run_candidates([raw('kept', 'changed text'), raw('no', 'snippet')])
        self.assertEqual(self.store.get(job_id).to_dict(), before)
        self.assertEqual(len(self.store.all()), 1)
        self.publish.assert_not_called(); self.review.assert_not_called(); self.paid.assert_not_called()

    def test_concurrent_process_lock_prevents_double_paid_and_rows(self):
        entered, finish = Event(), Event()
        def paid(candidate, history):
            entered.set()
            self.assertTrue(finish.wait(5))
            return self.charge(candidate, history)
        self.paid.side_effect = paid
        def first_worker():
            with JobStore(self.root/'jobs.sqlite') as store:
                engine = self.engine(); engine.store = store
                return engine.run([raw(description='snippet')], tracker=self.tracker, rejections=self.rejections)
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(first_worker)
            self.assertTrue(entered.wait(5))
            try:
                with self.assertRaises(ProviderError):
                    self.run_candidates([raw(description='snippet')])
            finally:
                finish.set()
            future.result()
        self.run_candidates([raw(description='snippet')])
        self.assertEqual(self.paid.call_count, 1)
        self.assertEqual(self.publish.call_count, 1)
        self.assertEqual(len(self.store.all()), 1)

    def test_filters_run_before_retrieval_and_unknown_stays_pending(self):
        outside = raw('outside', 'snippet'); outside.location='London'; outside.remote_type='on-site'
        irrelevant = raw('other', 'snippet'); irrelevant.title='Registered Nurse'
        unknown = raw('unknown'); unknown.location=''; unknown.remote_type=''
        self.run_candidates([outside, irrelevant, unknown])
        self.free.assert_not_called(); self.paid.assert_not_called(); self.review.assert_not_called()
        with self.history.connect() as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM daily_candidates WHERE state='pending'").fetchone()[0], 1)

    def test_expired_distinct_from_failed_pending(self):
        closed = raw(); closed.metadata['isListed']=False
        self.run_candidates([closed])
        with self.history.connect() as con:
            self.assertEqual(con.execute('SELECT state FROM daily_candidates').fetchone()[0], 'expired')
        self.paid.assert_not_called(); self.review.assert_not_called()

    def test_transport_cache_reused_after_ttl_without_free_or_paid(self):
        candidate = raw(description='snippet')
        self.charge(candidate, self.history)
        result = self.run_candidates([candidate], now=NOW+timedelta(days=30))
        self.assertEqual(result['new_jobs_added'], 1)
        self.assertEqual(result['paid_requests'], 0)
        self.free.assert_not_called(); self.paid.assert_not_called()

    def test_crash_after_transport_settlement_recovers_without_repeat(self):
        candidate = raw(description='snippet')
        engine = self.engine()
        key = next(iter(engine.ingest([candidate], {}, self.rejections)))
        engine.update(key, state='pending', paid_state='dispatched')
        self.charge(candidate, self.history)
        result = self.run_candidates([], now=NOW+timedelta(days=8))
        self.assertEqual(result['new_jobs_added'], 1)
        self.free.assert_not_called(); self.paid.assert_not_called()

    def test_controlled_limit_retains_work_for_next_run(self):
        result = self.run_candidates([raw('one'),raw('two')], max_new_candidates=1)
        self.assertEqual(result['new_jobs_added'], 1)
        self.assertEqual(result['pending'], 1)
        result = self.run_candidates([])
        self.assertEqual(result['new_jobs_added'], 1)
        self.assertEqual(len(self.store.all()), 2)

    def test_configured_source_limit_defers_without_discarding(self):
        result = self.run_candidates([raw('one'),raw('two')], source_limits={'test':1})
        self.assertEqual(result['new_jobs_added'], 1)
        self.assertEqual(result['pending'], 1)
        result = self.run_candidates([], source_limits={'test':1})
        self.assertEqual(result['new_jobs_added'], 1)
        self.assertEqual(len(self.store.all()), 2)

    def test_new_complete_source_evidence_rescues_changed_pending_metadata(self):
        candidate = raw(); candidate.location=''; candidate.remote_type=''
        self.run_candidates([candidate])
        # A shorter complete source description and newly explicit location are
        # evidence, not a reason to keep the old pending decision indefinitely.
        fresh = raw(description=TEXT[:900])
        result = self.run_candidates([fresh], now=NOW+timedelta(days=1))
        self.assertEqual(result['new_jobs_added'], 1)
        self.paid.assert_not_called()

    def test_pending_missing_title_can_recover_from_an_incomplete_feed(self):
        candidate = raw(description='snippet'); candidate.title=''
        self.run_candidates([candidate])
        self.free.return_value={'description':TEXT, 'url':raw().url}
        result = self.run_candidates([raw(description='updated source snippet')], now=NOW+timedelta(days=1))
        self.assertEqual(result['new_jobs_added'], 1)
        self.paid.assert_not_called()

    def test_publication_only_never_retries_pending_retrieval(self):
        candidate = raw(description='snippet')
        engine = self.engine()
        engine.ingest([candidate], {}, self.rejections)
        result = engine.run([], tracker=self.tracker, rejections=self.rejections, publish_only=True)
        self.assertEqual(result['new_jobs_added'], 0)
        self.free.assert_not_called(); self.paid.assert_not_called(); self.review.assert_not_called()

    def test_default_search_routes_incremental_and_broad_is_explicit(self):
        import scout
        args = scout.build_parser().parse_args(['search'])
        with patch('incremental_discovery.run', return_value=0) as incremental, patch('unified_search.run') as broad:
            self.assertEqual(scout.search(args, self.store, {}), 0)
        incremental.assert_called_once(); broad.assert_not_called()
        args = scout.build_parser().parse_args(['search','--broad-discovery'])
        with patch('incremental_discovery.run') as incremental, patch('unified_search.run', return_value=0) as broad:
            self.assertEqual(scout.search(args, self.store, {}), 0)
        broad.assert_called_once(); incremental.assert_not_called()

    def test_known_rejection_does_not_hide_distinct_new_source_id(self):
        self.rejections = RejectedJobsIndex([RejectedJob(source='test',job_id='old',original_url=raw('old').url)])
        candidate = raw('new', url=raw('old').url)
        result = self.run_candidates([candidate])
        self.assertEqual(result['new_jobs_added'], 1)

    def test_canonical_writer_preserves_reordered_manual_formula_resume_cells(self):
        from tests.test_google_tracker import FakeSheets
        from google_tracker import GoogleTracker, Config
        from incremental_discovery import publish_verified
        fake = FakeSheets()
        rows = fake.data['Job Scout']
        rows[0].extend(['Query Used to Find','Custom field'])
        rows[1].extend(['manual original query','=A2+1'])
        for field, value in {'Resume Created':' X ', 'Resume Link':'file:///protected.docx',
                             'Notes':'Manual notes', 'Applied':True}.items():
            rows[1][rows[0].index(field)] = value
        for row in rows:
            row.reverse()
        before = deepcopy(rows[1])
        remote = GoogleTracker(Config('test',Path('unused'),'Job Tracker','Job Scout'),service=fake)
        remote._sheet_properties = Mock(return_value=[{'title':title,'sheetId':index,
            'gridProperties':{'frozenRowCount':2}} for index,title in enumerate(fake.data)])
        job = normalize(raw()); job.id = 99
        with patch('resume_match.settings',return_value={'enabled':False}), \
             patch('query_provenance.query_for_job',return_value='Actual recorded query'):
            publish_verified(remote, job)
        self.assertEqual(rows[1], before)
        saved = next(v for _,v in remote.scout().rows if str(v['Scout ID'])=='99')
        self.assertEqual(saved['Query Used to Find'], 'Actual recorded query')
        self.assertFalse(any('frozenRowCount' in str(r) for r in fake.structural))

    def test_missing_provenance_header_stops_before_tracker_write(self):
        from tests.test_google_tracker import FakeSheets
        from google_tracker import GoogleTracker, Config
        from incremental_discovery import publish_verified
        fake = FakeSheets()
        remote = GoogleTracker(Config('test',Path('unused'),'Job Tracker','Job Scout'),service=fake)
        job = normalize(raw()); job.id=99
        with patch('query_provenance.query_for_job',return_value='Observed query'):
            with self.assertRaisesRegex(RuntimeError, 'missing Query Used'):
                publish_verified(remote, job)
        self.assertFalse(fake.writes)


if __name__ == '__main__':
    unittest.main()
