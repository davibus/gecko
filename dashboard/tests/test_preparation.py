import json
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'scripts')]
from test_sqlite_tracker import SQLiteTrackerTests
from dashboard import preparation as p, server as s, manual
from storage import JobStore


class PreparationTests(SQLiteTrackerTests):
    def setUp(self):
        super().setUp()
        JobStore(self.db).close()
        self.state = Path(self.temp.name)/'state'
        patcher = patch.object(s, 'STATE', self.state)
        patcher.start(); self.addCleanup(patcher.stop)
        self.app = s.Workspace(lambda: self.tracker)
        self.app.activity = lambda: {'busy':False, 'operation':self.app.operation}
        self.url = 'https://www.indeed.com/viewjob?jk=123456abcdef'

    def begin(self):
        with patch.object(p.threading, 'Thread'):
            return p.start(self.app, {'url':self.url})

    def details(self):
        return {'Company':'Example', 'Job Title':'Search Manager', 'Location':'Remote', 'Work Arrangement':'Remote',
                'description':'Lead paid search campaigns, manage campaign budgets, analyze marketing results and optimize acquisition performance. '*20}

    def result(self, record, **extra):
        return dict(job_id=record['id'], job_url=self.url, confirmed_company='Example', confirmed_title='Search Manager',
                    status='ready_for_review', application_url='https://www.indeed.com/review',
                    resume_verified=True, review_evidence='Review your application', missing_fields=[], **extra)

    def run_flow(self, outcome=None):
        record = self.begin()
        def generation(kind, job_id, continuation=None):
            self.assertEqual(kind, 'resume')
            self.assertEqual(str(job_id), record['id'])
            row, data = s.find_job(self.tracker.scout(), job_id)
            self.tracker.dashboard_edit(data, {'Resume Created':'X'})
            continuation()
            self.app.operation['workflow_status'] = 'complete'
        calls=[]
        def invoke(app, item, data, resume, folder, prompt_override=None):
            calls.append(prompt_override)
            if item['id']=='intake': return self.details()
            return outcome(record) if outcome else self.result(record)
        with patch.object(s,'run_lock',return_value=nullcontext()), patch.object(s,'resume_path',return_value=Path('verified.docx')), patch.object(self.app,'worker',side_effect=generation) as gen, patch.object(p.applications,'invoke',side_effect=invoke):
            p.worker(self.app, record)
        return record,gen,calls

    def test_existing_ats_job_prepares_review_without_manual_membership_or_regeneration(self):
        url='https://jobs.lever.co/example/123'
        saved=manual.save(self.tracker,dict(self.details(),url=url,Source='lever',applied=False),s.now())
        _,data=s.find_job(self.tracker.scout(),saved['id'])
        self.tracker.dashboard_edit(data,{'Resume Created':'X'})
        with self.tracker.connection() as con,con:
            con.execute('DELETE FROM workspace_manual_jobs WHERE job_id=?',(saved['id'],))
        _,data=s.find_job(self.tracker.scout(),saved['id'])
        with patch.object(p.threading,'Thread'),patch.object(s,'resume_path',return_value=Path('verified.docx')):
            record=p.start(self.app,{'id':saved['id'],'version':s.version(data)})
        result=dict(job_id=saved['id'],job_url=url,confirmed_company='Example',confirmed_title='Search Manager',status='ready_for_review',application_url='https://jobs.lever.co/example/review',resume_verified=True,review_evidence='Review application',missing_fields=[])
        with patch.object(s,'run_lock',return_value=nullcontext()),patch.object(s,'resume_path',return_value=Path('verified.docx')),patch.object(p.applications,'invoke',return_value=result) as invoke,patch.object(self.app,'worker') as generate:
            p.worker(self.app,record)
        self.assertEqual(record['status'],'ready_for_review')
        generate.assert_not_called()
        self.assertIn('NEVER click Submit',invoke.call_args.kwargs['prompt_override'])
        self.assertNotIn(saved['id'],manual.manual_ids(self.tracker))
        self.assertFalse(s.marked(s.find_job(self.tracker.scout(),saved['id'])[1].get('Applied')))

    def test_existing_job_rejects_stale_version_before_browser_work(self):
        saved=manual.save(self.tracker,dict(self.details(),url=self.url,applied=False),s.now())
        with patch.object(p.threading,'Thread') as thread,self.assertRaisesRegex(ValueError,'changed'):
            p.start(self.app,{'id':saved['id'],'version':'stale'})
        thread.assert_not_called()

    def test_link_to_saved_job_resume_and_review_without_applied(self):
        record,gen,calls=self.run_flow()
        self.assertEqual(record['status'],'ready_for_review')
        self.assertEqual(gen.call_count,1)
        self.assertIn('NEVER click Submit',calls[-1])
        self.assertNotIn('authorized to submit',calls[-1])
        self.assertIn(record['id'],manual.manual_ids(self.tracker))
        _,data=s.find_job(self.tracker.scout(),record['id'])
        self.assertFalse(s.marked(data.get('Applied')))
        self.assertEqual(p.records(self.app)[0]['application_url'],'https://www.indeed.com/review')

    def test_captcha_preserves_draft_without_applied(self):
        def outcome(record):
            result=self.result(record)
            result.update(status='needs_attention',reason='Complete CAPTCHA',missing_fields=['Complete CAPTCHA'],resume_verified=False)
            return result
        record,_,_=self.run_flow(outcome)
        self.assertEqual(record['status'],'needs_attention')
        self.assertEqual(record['missing_fields'],['Complete CAPTCHA'])
        self.assertFalse(s.marked(s.find_job(self.tracker.scout(),record['id'])[1].get('Applied')))

    def test_submitted_response_is_rejected(self):
        def outcome(record):
            result=self.result(record);result['status']='submitted';return result
        record,_,_=self.run_flow(outcome)
        self.assertEqual(record['status'],'needs_attention')
        self.assertIn('Unexpected application outcome',record['reason'])
        self.assertFalse(s.marked(s.find_job(self.tracker.scout(),record['id'])[1].get('Applied')))

    def test_unverified_resume_cannot_be_ready(self):
        def outcome(record):
            result=self.result(record);result['resume_verified']=False;return result
        record,_,_=self.run_flow(outcome)
        self.assertEqual(record['status'],'needs_attention')

    def test_existing_marker_blocks_regeneration_even_without_link(self):
        saved=manual.save(self.tracker,dict(self.details(),url=self.url),s.now())
        _,data=s.find_job(self.tracker.scout(),saved['id'])
        self.tracker.dashboard_edit(data,{'Resume Created':' x '})
        record=self.begin()
        with patch.object(s,'run_lock',return_value=nullcontext()),patch.object(self.app,'worker') as gen,patch.object(p.applications,'invoke') as invoke:
            p.worker(self.app,record)
        gen.assert_not_called();invoke.assert_not_called()
        self.assertIn('Regeneration is blocked',record['reason'])

    def test_duplicate_preparation_and_restart_do_not_dispatch(self):
        record=self.begin()
        self.app.operation=None
        self.assertEqual(p.records(self.app)[0]['status'],'needs_attention')
        with patch.object(p.threading,'Thread') as thread,self.assertRaisesRegex(ValueError,'already has a preparation'):
            p.start(self.app,{'url':self.url+'&from=shared'})
        thread.assert_not_called()

    def test_non_indeed_url_rejected(self):
        with self.assertRaisesRegex(ValueError,'Indeed job link'):
            p.start(self.app,{'url':'https://example.com/jobs/12'})

    def test_linkedin_job_links_supported_and_normalized(self):
        for url in ['https://www.linkedin.com/jobs/view/search-manager-1234567890/', 'https://www.linkedin.com/jobs/search/?currentJobId=1234567890']:
            self.app.operation=None
            with patch.object(p.threading,'Thread'):
                record=p.start(self.app,{'url':url})
            self.assertEqual(record['url'],'https://www.linkedin.com/jobs/view/1234567890/')
            (self.state/'preparations'/record['preparation_id']/'record.json').unlink()

    def test_linkedin_profile_link_is_not_a_job(self):
        with self.assertRaisesRegex(ValueError,'job posting link'):
            p.start(self.app,{'url':'https://www.linkedin.com/in/example/'})

    def test_wrong_job_identity_does_not_become_ready(self):
        def outcome(record):
            result=self.result(record);result['confirmed_company']='Wrong employer';return result
        record,_,_=self.run_flow(outcome)
        self.assertEqual(record['status'],'needs_attention')
        self.assertIn('identity was not verified',record['reason'])

    def test_existing_validated_resume_is_reused(self):
        saved=manual.save(self.tracker,dict(self.details(),url=self.url),s.now())
        _,data=s.find_job(self.tracker.scout(),saved['id'])
        self.tracker.dashboard_edit(data,{'Resume Created':'X'})
        record=self.begin()
        with patch.object(s,'run_lock',return_value=nullcontext()),patch.object(s,'resume_path',return_value=Path('verified.docx')),patch.object(self.app,'worker') as gen,patch.object(p.applications,'invoke',side_effect=lambda *args,**kwargs:self.result(record)) as invoke:
            p.worker(self.app,record)
        gen.assert_not_called();invoke.assert_called_once()
        self.assertEqual(record['status'],'ready_for_review')
        self.assertEqual(record['id'],saved['id'])

    def test_failed_intake_can_continue_but_browser_draft_cannot_repeat(self):
        record=self.begin()
        with patch.object(s,'run_lock',return_value=nullcontext()),patch.object(p.applications,'invoke',return_value={'blocked':'Complete CAPTCHA on posting'}):
            p.worker(self.app,record)
        self.assertTrue(record['retry_safe'])
        with patch.object(p.threading,'Thread'):
            continued=p.start(self.app,{'url':self.url,'retry_id':record['preparation_id']})
        self.assertEqual(continued['preparation_id'],record['preparation_id'])
        continued.update(status='needs_attention',retry_safe=False)
        self.app.operation['status']='needs attention';p.persist(self.app,continued)
        with self.assertRaisesRegex(ValueError,'already has a preparation'):
            p.start(self.app,{'url':self.url,'retry_id':record['preparation_id']})

    def test_real_resume_worker_continues_only_after_completed_resume_readback(self):
        from types import SimpleNamespace
        root=Path(self.temp.name)
        self.state.mkdir()
        self.app.operation={'kind':'prepare_application','status':'running','started_at':s.now()}
        fields={'Resume Created':'X'}
        with patch.object(s,'ROOT',root),patch.object(s,'run_lock',return_value=nullcontext()),patch('codex_runner.CodexJsonClient') as client,patch.object(self.app,'run_command',return_value=SimpleNamespace(returncode=0)),patch.object(self.app,'detail',return_value={'resume_available':True,'fields':fields}):
            client.return_value.complete.return_value={'ok':True}
            client.return_value.last_receipt={'verified':True}
            observed=[]
            self.app.worker('resume',10,continuation=lambda:observed.append(self.app.operation['status']))
        self.assertEqual(observed,['running'])
        self.assertEqual(self.app.operation['workflow_status'],'complete')
        self.assertEqual(self.app.operation['status'],'running')
