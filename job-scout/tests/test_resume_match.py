import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

import resume_match as match
from models import RawListing
from normalize import normalize
from storage import JobStore
from service import discover_listings
from google_tracker import Config, GoogleTracker
from tests.test_google_tracker import FakeSheets


class ResumeMatchTests(unittest.TestCase):
    def test_spreadsheet_scores_are_numeric_and_unstated_stay_blank(self):
        review = {'status': 'reviewed', 'score': 80.25,
                  'category_percentages': {'responsibilities': 90, 'required': 75,
                                          'seniority': 0, 'industry': None, 'preferred': 100}}
        self.assertEqual(match.spreadsheet_scores(review), {
            'Match Score': 80.25, 'Responsibilities Match': 90, 'Required Skills Match': 75,
            'Seniority Match': 0, 'Preferred Skills Match': 100})
        self.assertEqual(match.spreadsheet_scores({'status': 'pending', 'score': None}), {})

    def test_new_rows_publish_score_columns_by_name(self):
        service = FakeSheets()
        headers = service.data['Job Scout'][0]
        headers.extend(reversed(['Match Score', *match.SCORE_COLUMNS.values()]))
        remote = GoogleTracker(Config('test', Path('unused'), 'Job Tracker', 'Job Scout'), service=service)
        job = normalize(RawListing('test','new','https://example.test/new','Paid Search Manager','Test',location='Remote'))
        job.id = 99
        review = {'accepted': True, 'status': 'reviewed', 'score': 91.47, 'reason': 'Supported',
                  'category_percentages': {'responsibilities': 89.29, 'required': 92.86,
                                          'seniority': 100, 'industry': None, 'preferred': 75}}
        with patch('resume_match.settings',return_value={'enabled': True}), patch('resume_match.assess',return_value={'0':review}):
            remote.upsert_scout([job])
        rows = service.data['Job Scout']
        added = next(dict(zip(rows[0], row)) for row in rows[1:] if str(row[0]) == '99')
        for name, value in match.spreadsheet_scores(review).items():
            self.assertEqual(float(added[name]), value)
        self.assertFalse(added.get('Industry Match'))

    def review(self, supports=(1, 1, 1, 1, 0)):
        names = list(match.WEIGHTS)
        return {'id': '1', 'sufficient': True, 'reason': 'Evidence comparison', 'blockers': [],
                'categories': {name: [{'requirement': name, 'support': support,
                    'evidence': ['Managed paid search'] if support else [], 'reason': 'Compared evidence'}]
                    for name, support in zip(names, supports)}}

    def item(self):
        return {'id': '1', 'title': 'Paid Search Manager', 'company': 'Test', 'url': 'https://example.test/new',
                'description': 'responsibilities required seniority industry preferred'}

    def test_threshold_and_core_floor(self):
        # 40 + 30 + 0 + 10 + 0 = exactly 80; accepted.
        good = match.validate(self.review((1,1,0,1,0)), self.item(), 'Managed paid search')
        self.assertEqual(good['score'], 80)
        self.assertTrue(good['accepted'])
        below = match.validate(self.review((1,1,0,.5,0)), self.item(), 'Managed paid search')
        self.assertEqual(below['score'], 75)
        self.assertFalse(below['accepted'])
        # 85 overall cannot conceal only 50% required-skills alignment.
        weak = match.validate(self.review((1,.5,1,1,1)), self.item(), 'Managed paid search')
        self.assertEqual(weak['score'], 85)
        self.assertFalse(weak['accepted'])

    def test_fabricated_evidence_and_duplicate_requirements_rejected(self):
        bad = self.review()
        bad['categories']['required'][0]['evidence'] = ['Invented credential']
        with self.assertRaises(ValueError): match.validate(bad, self.item(), 'Managed paid search')
        bad = self.review()
        bad['categories']['required'] = copy.deepcopy(bad['categories']['responsibilities'])
        with self.assertRaises(ValueError): match.validate(bad, self.item(), 'Managed paid search')

    def test_incomplete_and_blocked_never_admitted(self):
        for key, value in [('sufficient', False), ('blockers', ['required'])]:
            review = self.review((1,1,1,1,1)); review[key] = value
            self.assertFalse(match.validate(review, self.item(), 'Managed paid search')['accepted'])

    def test_cache_reused_but_master_change_invalidates(self):
        with TemporaryDirectory() as folder:
            source = Path(folder)/'master.docx'
            def write_master(text):
                with ZipFile(source, 'w') as package:
                    package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
            write_master('Managed paid search')
            client = Mock(); client.last_receipt = {}; client.complete.return_value = {'reviews':[self.review()]}
            options = {'client': client, 'cache_dir': Path(folder)/'cache', 'master_path': source}
            self.assertTrue(match.assess([self.item()], **options)['1']['accepted'])
            match.assess([self.item()], **options)
            self.assertEqual(client.complete.call_count, 1)
            write_master('Managed paid search and analytics')
            match.assess([self.item()], **options)
            self.assertEqual(client.complete.call_count, 2)
            client.complete.side_effect = RuntimeError('Offline')
            changed = {**self.item(), 'title':'Changed role'}
            result = match.assess([changed], **options)['1']
            self.assertFalse(result['accepted']); self.assertEqual(result['status'], 'pending')

    def test_discovery_filters_before_storage(self):
        with TemporaryDirectory() as folder, JobStore(Path(folder)/'test.db') as store:
            raw = RawListing('test','new','https://example.test/new','Paid Search Manager','Test',
                             location='Remote',description='Manage paid search campaigns. '*30)
            failure = {'accepted':False,'score':79,'status':'reviewed','reason':'Below cutoff'}
            with patch('resume_match.check',return_value=failure):
                summary = discover_listings([raw], store)
            self.assertEqual(summary.match_excluded,1)
            self.assertEqual(store.all(),[])

    def test_publication_blocks_low_scores_preserves_existing(self):
        remote = GoogleTracker(Config('test', Path('unused'), 'Job Tracker', 'Job Scout'),service=FakeSheets())
        new = normalize(RawListing('test','new','https://example.test/new','Paid Search Manager','Test',location='Remote'))
        new.id = 99
        fail = {'accepted':False,'score':79,'status':'reviewed','reason':'Below cutoff'}
        with patch('resume_match.settings', return_value={'enabled':True}), patch('resume_match.assess',return_value={'0':fail}):
            result = remote.upsert_scout([new])
        self.assertEqual(result['added'],0)
        self.assertEqual(result['match_excluded'][0]['job_id'],99)
        existing = normalize(RawListing('test','job','https://example.test/job','Role','Existing',location='Remote'))
        existing.id = 42
        with patch('resume_match.settings', return_value={'enabled':True}), patch('resume_match.assess',return_value={}) as assess:
            result = remote.upsert_scout([existing],append_only=True)
        assess.assert_called_once_with([])
        self.assertEqual(result['match_excluded'],[])

    def test_firecrawl_enforces_gate_before_storage(self):
        from tests.test_firecrawl_discovery import SmartDiscoveryTests, api
        case = SmartDiscoveryTests()
        case.setUp(); self.addCleanup(case.doCleanups)
        failure = {'accepted':False,'score':60,'status':'reviewed','reason':'Weak fit'}
        with patch.object(api, 'post_json', side_effect=case.transport()), patch('resume_match.check',return_value=failure):
            result = case.run_pipeline()
        self.assertEqual(result['new_qualified'], 0)
        self.assertEqual(case.store.all(), [])

    def test_optional_daily_scorer_reuses_canonical_match(self):
        from ai_evaluation import JobEvaluator
        job = normalize(RawListing('test','one','https://example.test/one','Paid Search Manager','Test'))
        job.id = 1
        store, legacy_client = Mock(), Mock()
        with patch('ai_evaluation.load_candidate_profile',return_value={'facts':'test'}):
            evaluator = JobEvaluator(store, {'ai_evaluation':{'triage_model':'test','scoring_model':'test'}}, client=legacy_client)
        review = {'accepted':True,'score':91.47,'status':'reviewed','reason':'Direct evidence',
                  'master_sha256':'test-hash','cached':True}
        with patch('resume_match.settings',return_value={'enabled':True}), patch('resume_match.assess',return_value={'1':review}):
            results, metrics = evaluator.evaluate([job])
        self.assertEqual(results[1].match_score,91.47)
        self.assertEqual(results[1].apply_decision,'Yes')
        self.assertEqual(metrics.cached_unchanged,1)
        legacy_client.complete.assert_not_called()

    def test_pending_publication_retains_retryable_jobs_only(self):
        from types import SimpleNamespace
        import unified_search
        jobs = {i: normalize(RawListing('test',str(i),'https://example.test/'+str(i),'Paid Search Manager','Test')) for i in (1,2)}
        for key, job in jobs.items(): job.id = key
        remote = SimpleNamespace(upsert_scout=Mock(return_value={'readback_verified':True,'skipped':[],
            'match_excluded':[{'job_id':1,'status':'reviewed'},{'job_id':2,'status':'pending'}]}),
            scout=lambda: SimpleNamespace(rows=[]))
        with TemporaryDirectory() as folder:
            pending = Path(folder)/'pending.json'
            pending.write_text(json.dumps({'job_ids':[1,2],'reports':[]}),encoding='utf-8')
            with patch.object(unified_search,'PENDING',pending), patch.object(unified_search,'flush_pending'), patch('sheet_sync.ensure_frozen_headers'):
                unified_search.deliver(SimpleNamespace(get=jobs.get),remote=remote)
            self.assertEqual(json.loads(pending.read_text())['job_ids'],[2])


if __name__ == '__main__':
    unittest.main()
