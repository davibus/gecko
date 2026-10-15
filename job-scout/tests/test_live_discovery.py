"""Standalone live discovery contracts tested with isolated sources and Sheets."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
import tempfile
import io
import json
from contextlib import redirect_stdout,redirect_stderr
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from models import RawListing
from normalize import normalize,posting_identity
from service import discover_listings
from google_tracker import GoogleTracker,Config
from sources.base import ProviderError,SearchRequest
from sources.acquisition import acquire
from test_google_tracker import FakeSheets,SCOUT
from urllib.error import HTTPError,URLError
from io import BytesIO
import sources.http as http

def raw(number=1):
    return RawListing('test',str(number),f'https://example.test/job/{number}',
                      'Paid Search Manager','Example',location='Remote',description='Current listing')

class LiveDiscoveryTests(unittest.TestCase):
    def test_live_canonical_search_writes_only_discovery_and_never_runs_other_workflows(self):
        import scout
        from storage import JobStore
        class Provider:
            name='test'
            def configured(self):return True
            def full_feed(self):return [raw(100)]
        class Validator:
            require_verified=True
            def check_existing(self,jobs,workers=4):return []
            def check(self,job):return SimpleNamespace(status='valid',reason='Listing loaded')
        fake=FakeSheets();fake.data['Job List']=fake.data.pop('Job Scout')
        tracker=GoogleTracker(Config('test',Path('unused'),'Job Tracker','Job List'),fake)
        args=scout.build_parser().parse_args(['search','--source','all','--results','50'])
        console=io.StringIO()
        with tempfile.TemporaryDirectory() as directory,JobStore(Path(directory)/'jobs.sqlite3') as store:
            args.audit_dir=Path(directory)/'evidence'
            with (patch('scout.GoogleTracker',return_value=tracker),
                  patch('scout.providers',return_value={'test':Provider()}),
                  patch('scout.load_source_config',return_value={'providers':{'test':{}},'max_workers':1,'max_results_per_source':0}),
                  patch('scout.DailyLinkValidator',Validator),
                  patch('scout.process_rejected_rows',side_effect=AssertionError('cleanup prohibited')),
                  patch('scout._daily_resume_runner',side_effect=AssertionError('resumes prohibited')),
                  patch('scout._daily_gmail_response_runner',side_effect=AssertionError('Gmail prohibited')),
                  redirect_stdout(io.StringIO()),redirect_stderr(console)):
                result=scout.search(args,store,scout.load_preferences())
            self.assertEqual(result,0)
            self.assertEqual(args.tracker_summary['added'],1)
            self.assertEqual(len(fake.data['Job List']),3)
            self.assertEqual(dict(zip(SCOUT,fake.data['Job List'][2]))['ID'],43)
            self.assertFalse(any('deleteDimension' in request for request in fake.structural))
            self.assertIn('New unique jobs saved locally: 1',console.getvalue())
            self.assertIn('Job List readback verified: added=1',console.getvalue())
            self.assertNotIn('New qualified jobs written:',console.getvalue())
            self.assertTrue((args.audit_dir/'tracker-before-write.json').exists())
            self.assertTrue((args.audit_dir/'tracker-after-write.json').exists())
            with self.assertRaisesRegex(RuntimeError,'already completed'):
                scout.sync_discovery(args,store,{})
    def test_standalone_search_never_runs_rejection_cleanup(self):
        import scout
        args=scout.build_parser().parse_args(['search','--source','all','--results','50'])
        self.assertTrue(args.safe_discovery);self.assertFalse(args.dry_run)
        self.assertEqual(args.function,scout.search)

    def test_recovery_sync_uses_only_saved_verified_candidate_identities(self):
        import scout
        from normalize import normalize
        job=normalize(raw(100));job.id=43;job.url_verification_status='verified';job.authoritative_url=job.url
        store=Mock();store.get.return_value=job
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            (folder/'discovery-reconciliation.json').write_text(json.dumps({'source_pipeline':{'test':{}},'new_job_ids':[43],'existing_job_ids':[]}))
            (folder/'test.json').write_text(json.dumps({'record_decisions':[{'reason':'new unique','job_id':43,'url':job.url}]}))
            args=scout.build_parser().parse_args(['sync-discovery','--audit-dir',directory])
            with patch('scout.sync_tracker',return_value={'added':1,'updated':0}) as sync,redirect_stdout(io.StringIO()):
                self.assertEqual(scout.sync_discovery(args,store,{}),0)
            self.assertEqual(sync.call_args.kwargs['jobs'],[job]);store.all.assert_not_called()
            job.authoritative_url='https://example.test/job/unverified'
            with patch('scout.sync_tracker') as sync:
                with self.assertRaisesRegex(RuntimeError,'no longer matches'):
                    scout.sync_discovery(args,store,{})
                sync.assert_not_called()

    def test_provider_reported_failure_is_not_a_successful_empty_page(self):
        class Provider:
            name='test';errors=[]
            def search(self,request):
                self.errors.append('HTTP Error 402: CREDIT_EXHAUSTED')
                return []
        provider=Provider()
        rows,errors=acquire(provider,[SearchRequest('marketing','remote',1,50)])
        self.assertEqual(rows,[]);self.assertTrue(errors)
        self.assertEqual(provider.acquisition_events[0]['status'],'failed')

    def test_transient_http_failure_is_retried_once(self):
        http._BILLING_FAILURES.clear()
        class Response:
            status=200;headers=SimpleNamespace(get_content_type=lambda:'application/json')
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return 'https://example.test/feed'
            def read(self,n):return b'{"jobs":[]}'
        opener=Mock();opener.open.side_effect=[URLError('timeout'),Response()]
        with patch('sources.http.build_opener',return_value=opener),patch('sources.http.time.sleep') as sleep:
            result=http.get_document('https://example.test/feed')
        self.assertEqual(opener.open.call_count,2);sleep.assert_called_once();self.assertTrue(result.body)

    def test_billing_failure_is_not_retried_or_secret_logged(self):
        http._BILLING_FAILURES.clear()
        error=HTTPError('https://example.test/feed?api_key=SECRET_VALUE',402,'Payment Required',{},BytesIO(b'{"error":{"code":"INSUFFICIENT_CREDITS"}}'))
        opener=Mock();opener.open.side_effect=error
        with patch('sources.http.build_opener',return_value=opener),patch('sources.http.time.sleep') as sleep:
            for _ in range(2):
                with self.assertRaises(ProviderError) as raised:
                    http.get_document('https://example.test/feed?api_key=SECRET_VALUE')
                self.assertNotIn('SECRET_VALUE',str(raised.exception))
        self.assertEqual(opener.open.call_count,1);sleep.assert_not_called();http._BILLING_FAILURES.clear()
    def test_review_url_is_not_saved_or_importable(self):
        store=Mock();store.all.return_value=[]
        validator=SimpleNamespace(require_verified=True,check=lambda job:SimpleNamespace(status='temporary_failure',reason='HTTP 403'))
        result=discover_listings([raw()],store,link_validator=validator)
        self.assertEqual(result.url_review_excluded,1);store.save.assert_not_called()
        self.assertEqual(result.new_job_ids,[])

    def test_verified_source_does_not_launch_enrichment_or_resume_work(self):
        store=Mock();store.all.return_value=[];store.save.return_value=99
        validator=SimpleNamespace(require_verified=True,check=lambda job:SimpleNamespace(status='valid',reason='Listing loaded'))
        with patch('service._capture_full_description',side_effect=AssertionError('out of scope')):
            result=discover_listings([raw()],store,link_validator=validator)
        self.assertEqual(result.new_job_ids,[99]);self.assertEqual(result.url_validated,1)

    def test_partial_page_records_survive_page_failure(self):
        class Source:
            name='test';has_more=False
            def search(self,request):
                yield raw();raise ProviderError('temporary parsing failure')
        rows,errors=acquire(Source(),[SearchRequest('marketing')])
        self.assertEqual(len(rows),1);self.assertEqual(len(errors),1)

    def test_posting_aliases_have_equal_stable_identity(self):
        self.assertEqual(posting_identity('http://boards.greenhouse.io/a/jobs/123'),
                         posting_identity('https://job-boards.greenhouse.io/a/jobs/123'))
        self.assertEqual(posting_identity('https://apply.workable.com/account/j/ABC/'),
                         posting_identity('https://apply.workable.com/j/ABC'))

    def test_discovery_writer_preserves_manual_fields_notes_and_x(self):
        fake=FakeSheets();headers,row=fake.data['Job Scout']
        for field,value in {'Apply?':' No ','Resume Created':' X ','Resume Link':'file:///C:/existing.docx',
                            'Applied':'X','Response':'Manual response','Notes':'Manual note','Cost':''}.items():
            row[headers.index(field)]=value
        headers.append('Custom');row.append('=1+1')
        before=dict(zip(headers,row))
        tracker=GoogleTracker(Config('test',Path('unused'),'Job Tracker','Job Scout'),fake)
        job=normalize(raw());job.id=42;job.url='https://example.test/job';job.canonical_url=job.url
        result=tracker.upsert_scout([job],discovery_notes={42:'Gecko verified this listing'})
        after=dict(zip(headers,row))
        for field in ['Apply?','Resume Created','Resume Link','Applied','Response','Cost','Custom']:
            self.assertEqual(before[field],after[field])
        self.assertEqual(after['Notes'],'Manual note\nGecko verified this listing')
        self.assertEqual(result['updated'],1);self.assertEqual(result['added'],0)
        self.assertTrue(result['readback_verified'])

    def test_new_insert_has_21_pixel_height_and_no_cleanup(self):
        fake=FakeSheets();tracker=GoogleTracker(Config('test',Path('unused'),'Job Tracker','Job Scout'),fake)
        job=normalize(raw(200));job.id=200
        result=tracker.upsert_scout([job],discovery_notes={200:'Verified'})
        self.assertEqual(result['added'],1)
        self.assertTrue(any(r.get('updateDimensionProperties',{}).get('properties',{}).get('pixelSize')==21 for r in fake.structural))
        self.assertFalse(any('deleteDimension' in r or 'addSheet' in r for r in fake.structural))

    def test_formula_update_is_skipped_and_reported(self):
        fake=FakeSheets();row=fake.data['Job Scout'][1];row[SCOUT.index('Salary')]='=1+1'
        tracker=GoogleTracker(Config('test',Path('unused'),'Job Tracker','Job Scout'),fake)
        job=normalize(raw());job.id=42;job.url='https://example.test/job';job.canonical_url=job.url;job.salary='New salary'
        result=tracker.upsert_scout([job],discovery_notes={42:'Verified'})
        self.assertEqual(row[SCOUT.index('Salary')],'=1+1')
        self.assertTrue(any(s.get('field')=='Salary' for s in result['skipped']))

if __name__=='__main__':unittest.main()
