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

LOAD_SETTINGS = match.settings

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

    def policy(self):
        return {'enabled': True, 'minimum_score': 60,
                'minimum_responsibilities_match': 50, 'minimum_required_skills_match': 50}

    def boundary_cases(self):
        exact = self.review((.5,.5,1,1,0))  # 20 + 15 + 15 + 10 = 60.
        cases = [('exact', exact, self.item(), True)]
        for name, supports in [('industry', [1]*19+[.5]),
                               ('responsibilities', [.5]*99+[0]),
                               ('required', [.5]*99+[0])]:
            review = copy.deepcopy(exact) if name == 'industry' else self.review((1,1,1,1,1))
            item = self.item()
            review['categories'][name] = [
                {'requirement': f'{name} requirement {i:03}', 'support': support,
                 'evidence': ['Managed paid search'] if support else [], 'reason': 'Compared evidence'}
                for i, support in enumerate(supports)]
            item['description'] += '\n' + '\n'.join(e['requirement'] for e in review['categories'][name])
            cases.append((name, review, item, False))
        return cases

    def test_all_three_inclusive_thresholds_and_independent_failures(self):
        with patch('resume_match.settings', return_value=self.policy()):
            for name, review, item, accepted in self.boundary_cases():
                with self.subTest(name=name):
                    result = match.validate(review, item, 'Managed paid search')
                    self.assertEqual(result['accepted'], accepted)
                    if name == 'exact':
                        self.assertEqual(result['score'], 60)
                        self.assertEqual(result['category_percentages']['responsibilities'], 50)
                        self.assertEqual(result['category_percentages']['required'], 50)
                    elif name == 'industry':
                        self.assertEqual(result['score'], 59.75)
                        self.assertEqual(result['failed_rules'], ['Score below 60'])
                    else:
                        self.assertGreater(result['score'], 60)
                        self.assertEqual(result['category_percentages'][name], 49.5)
                        self.assertEqual(result['failed_rules'], [name+' alignment below 50%'])
                    explanation = match.explanation(result)
                    self.assertIn('overall >= 60/100', explanation)
                    self.assertIn('responsibilities >= 50%', explanation)
                    self.assertIn('required skills >= 50%', explanation)

    def test_threshold_configuration_rejects_invalid_values(self):
        with TemporaryDirectory() as folder:
            config = Path(folder)/'policy.json'
            with patch.object(match, 'CONFIG', config), patch.object(match, 'settings', LOAD_SETTINGS):
                config.write_text(json.dumps(self.policy()), encoding='utf-8')
                self.assertEqual(match.settings(), self.policy())
                for key in match.THRESHOLD_DEFAULTS:
                    for invalid in (True, -1, 101, '50', float('nan')):
                        with self.subTest(key=key, value=invalid):
                            config.write_text(json.dumps({**self.policy(), key:invalid}), encoding='utf-8')
                            with self.assertRaises(ValueError): match.settings()

    def test_cached_evidence_recalculates_acceptance_without_inference(self):
        with TemporaryDirectory() as folder:
            source = Path(folder)/'master.docx'
            with ZipFile(source, 'w') as package:
                package.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Managed paid search</w:t></w:r></w:p></w:body></w:document>')
            client = Mock(); client.last_receipt = {}
            client.complete.return_value = {'reviews':[self.review((.5,.5,1,1,0))]}
            options = {'client': client, 'cache_dir': Path(folder)/'cache', 'master_path': source}
            old_policy = {'enabled':True, 'minimum_score':80,
                          'minimum_responsibilities_match':70, 'minimum_required_skills_match':70}
            with patch('resume_match.settings', return_value=old_policy):
                old = match.assess([self.item()], **options)['1']
                self.assertFalse(old['accepted'])
            cache_file = next(options['cache_dir'].glob('*.json'))
            before = cache_file.read_bytes()
            client.complete.side_effect = AssertionError('Cached evidence must not launch inference')
            with patch('resume_match.settings', return_value=self.policy()):
                new = match.assess([self.item()], **options)['1']
            self.assertTrue(new['accepted']); self.assertTrue(new['cached'])
            self.assertEqual(new['score'], 60)
            self.assertEqual(new['failed_rules'], [])
            self.assertEqual(new['categories'], old['categories'])
            self.assertEqual(cache_file.read_bytes(), before)
            self.assertEqual(client.complete.call_count, 1)
            with patch('resume_match.settings', return_value=old_policy):
                self.assertFalse(match.assess([self.item()], **options)['1']['accepted'])

    def test_screening_and_publication_share_all_three_thresholds(self):
        for name, review, item, accepted in self.boundary_cases():
            with self.subTest(name=name), TemporaryDirectory() as folder:
                raw = RawListing('test','new','https://example.test/new','Paid Search Manager','Test',
                                 location='Remote',description=item['description'])
                def assess(records):
                    return {str(r['id']):match.validate(review,r,'Managed paid search') for r in records}
                with patch('resume_match.settings', return_value=self.policy()), patch('resume_match.assess',side_effect=assess):
                    with JobStore(Path(folder)/'jobs.db') as store, patch('service._capture_full_description'):
                        result = discover_listings([raw],store,require_content=True)
                        self.assertEqual(result.added, int(accepted))
                        self.assertEqual(len(store.all()), int(accepted))
                    sheets = FakeSheets()
                    before = copy.deepcopy(sheets.data)
                    remote = GoogleTracker(Config('test',Path('unused'),'Job Tracker','Job Scout'),service=sheets)
                    job = normalize(raw); job.id = 99
                    result = remote.upsert_scout([job])
                    self.assertEqual(result['added'], int(accepted))
                    self.assertEqual(sheets.data['Job Scout'][1], before['Job Scout'][1])
                    self.assertEqual(sheets.data['Job Tracker'], before['Job Tracker'])

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
            failure = {'accepted':False,'score':59,'status':'reviewed','reason':'Below cutoff'}
            with patch('resume_match.check',return_value=failure):
                summary = discover_listings([raw], store)
            self.assertEqual(summary.match_excluded,1)
            self.assertEqual(store.all(),[])

    def test_publication_blocks_low_scores_preserves_existing(self):
        remote = GoogleTracker(Config('test', Path('unused'), 'Job Tracker', 'Job Scout'),service=FakeSheets())
        new = normalize(RawListing('test','new','https://example.test/new','Paid Search Manager','Test',location='Remote'))
        new.id = 99
        fail = {'accepted':False,'score':59,'status':'reviewed','reason':'Below cutoff'}
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
