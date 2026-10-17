import sys
from pathlib import Path
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2]/'scripts')]
from test_sqlite_tracker import SQLiteTrackerTests
from dashboard import manual
from dashboard.server import Workspace

class ManualTests(SQLiteTrackerTests):
    def test_manual_resume_worker_publishes_only_after_completion_readback(self):
        from types import SimpleNamespace
        import dashboard.server as server
        root=Path(self.temp.name)
        source=root/'output/resumes/canonical.docx'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'verified document')
        fields={'Company':'Example','Job Title':'Manager','Resume Created':'X','Resume Link':source.as_uri()}
        app=Workspace(lambda:self.tracker)
        app.operation={'kind':'resume','status':'running','manual_upload':True,'started_at':'2026-10-17T00:00:00-06:00'}
        with patch.object(server,'ROOT',root),patch.object(server,'STATE',root/'state'),patch('codex_runner.CodexJsonClient') as runner,patch.object(app,'run_command',return_value=SimpleNamespace(returncode=0)),patch.object(app,'detail',return_value={'resume_available':True,'fields':fields}):
            (root/'state').mkdir()
            runner.return_value.complete.return_value={'ok':True}
            runner.return_value.last_receipt={'verified':True}
            app.worker('resume',123)
        self.assertEqual(app.operation['status'],'complete')
        self.assertEqual(Path(app.operation['upload_path']).read_bytes(),b'verified document')
        self.assertIn('ID123.docx',app.operation['upload_name'])

    def test_create_resume_saves_approved_unsubmitted_job_and_pasted_description(self):
        description = 'Lead paid search campaigns and improve acquisition performance. ' * 20
        payload = {'url':'https://example.com/manual-tailored','Company':'Example','Job Title':'Search Manager',
                   'Location':'United States','Work Arrangement':'remote','description':description,'create_resume':True}
        saved = manual.save(self.tracker,payload,'2026-10-17')
        detail = Workspace(lambda:self.tracker).detail(saved['id'])
        self.assertTrue(detail['can_generate'])
        self.assertFalse(detail['applied'])
        self.assertFalse(detail['fields'].get('Resume Created'))
        with self.tracker.connection() as con:
            self.assertEqual(con.execute('SELECT description FROM jobs WHERE id=?',(saved['id'],)).fetchone()[0],description)

    def test_create_resume_rejects_incomplete_description_and_unknown_eligibility(self):
        payload = {'url':'https://example.com/manual-invalid','Company':'Example','Job Title':'Manager',
                   'Location':'Utah','description':'Too short','create_resume':True}
        with self.assertRaisesRegex(ValueError,'complete job description'):
            manual.save(self.tracker,payload,'2026-10-17')
        payload.update(description='Manage marketing campaigns and report results. '*30,Location='Unknown')
        with self.assertRaisesRegex(ValueError,'eligibility'):
            manual.save(self.tracker,payload,'2026-10-17')
        self.assertEqual(manual.manual_ids(self.tracker),[])

    def test_upload_copy_named_by_job_and_never_overwrites_different_content(self):
        root=Path(self.temp.name)
        source=root/'output/resumes/canonical.docx'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'verified canonical document')
        fields={'Company':'Example/Co','Job Title':'Marketing: Manager'}
        target=manual.publish_upload_copy(source,fields,12345,root)
        self.assertEqual(target.name,'Dave Call - ExampleCo - Marketing Manager - ID12345.docx')
        self.assertEqual(target.parent,root/'output/resumes/Manual Applications/Ready to Upload')
        self.assertEqual(target.read_bytes(),source.read_bytes())
        self.assertEqual(manual.publish_upload_copy(source,fields,12345,root),target)
        source.write_bytes(b'a different document')
        with self.assertRaisesRegex(ValueError,'preserved'):
            manual.publish_upload_copy(source,fields,12345,root)
        self.assertEqual(target.read_bytes(),b'verified canonical document')

    def setUp(self):
        super().setUp()
        from storage import JobStore
        JobStore(self.db).close()

    def test_uploaded_resume_saved_with_shared_record(self):
        from dashboard import attachments
        content=b'%PDF-1.7\nUploaded test resume\n%%EOF'
        with patch.object(attachments,'DIRECTORY',Path(self.temp.name)/'uploads'):
            uploaded=attachments.upload('My Resume.pdf',content)
            saved=manual.save(self.tracker,{'url':'https://example.com/resume-job','Company':'Test','Job Title':'Manager','resume_token':uploaded['token']},'2026-10-17')
            info,actual=attachments.for_job(self.tracker,saved['id'])
            self.assertEqual(actual,content)
            self.assertEqual(info['name'],'My Resume.pdf')
            detail=Workspace(lambda:self.tracker).detail(saved['id'])
            self.assertEqual(detail['attached_resume']['name'],'My Resume.pdf')
            self.assertFalse(detail['resume_available'])
            self.assertFalse(detail['fields'].get('Resume Created'))
            for bad in ['../outside','not-a-token']:
                with self.assertRaises(ValueError): attachments.read(bad)
            with self.assertRaises(ValueError): attachments.upload('resume.pdf',b'not a PDF')
            with self.assertRaises(ValueError): attachments.upload('resume.docx',b'not a zip')
            with self.assertRaises(ValueError): attachments.upload('resume.exe',content)

    def test_missing_attachment_does_not_create_job(self):
        with self.assertRaises(ValueError):
            manual.save(self.tracker,{'url':'https://example.com/missing-resume','Company':'Test','Job Title':'Manager','resume_token':'bad'},'2026-10-17')
        self.assertEqual(len(self.tracker.scout().rows),1)

    def test_shared_record_and_duplicate_prevention(self):
        original=self.tracker.scout().rows[0][1]
        payload={'url':'https://example.com/jobs/new','Company':'New company','Job Title':'Manager','applied':True,'applied_date':'2026-10-16'}
        saved=manual.save(self.tracker,payload,'2026-10-16T12:00:00-06:00')
        self.assertGreater(int(saved['id']),10)
        self.assertEqual(manual.manual_ids(self.tracker),[saved['id']])
        snap=Workspace(lambda:self.tracker).snapshot()
        job=next(j for j in snap['jobs'] if j['id']==saved['id'])
        self.assertTrue(job['applied'])
        self.assertEqual(job['meta']['applied_at'],'2026-10-16')
        self.assertEqual(self.tracker.scout().rows[0][1],original)
        with self.assertRaisesRegex(ValueError,'already saved'):
            manual.save(self.tracker,payload,'2026-10-16T12:00:00-06:00')

    def test_save_unsubmitted_work_appears_in_both_lists(self):
        payload={'url':'https://example.com/jobs/not-applied','Company':'Saved company','Job Title':'Manager',
                 'description':'My saved posting details','Notes':'My unfinished application notes','applied':False,
                 'applied_date':'2026-10-17'}
        saved=manual.save(self.tracker,payload,'2026-10-17T12:00:00-06:00')
        snapshot=Workspace(lambda:self.tracker).snapshot()
        self.assertIn(saved['id'],snapshot['manual_ids'])
        job=next(j for j in snapshot['jobs'] if j['id']==saved['id'])
        self.assertFalse(job['applied'])
        self.assertFalse(job['fields']['Applied Date'])
        self.assertEqual(job['notes'],'My unfinished application notes')
        with self.tracker.connection() as con:
            self.assertEqual(con.execute('SELECT description FROM jobs WHERE id=?',(saved['id'],)).fetchone()[0],payload['description'])

    def test_atomic_rollback(self):
        with self.tracker.connection() as con,con:
            con.execute("CREATE TRIGGER reject_manual BEFORE INSERT ON workspace_events BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(Exception):
            manual.save(self.tracker,{'url':'https://example.com/new','Company':'X','Job Title':'Y'},'2026-10-16')
        self.assertEqual(len(self.tracker.scout().rows),1)
        with self.tracker.connection() as con:
            self.assertIsNone(con.execute("SELECT id FROM jobs WHERE url='https://example.com/new'").fetchone())

    def test_private_url_and_future_date_rejected(self):
        for url in ['http://example.com/job','https://127.0.0.1/job','https://user:pass@example.com/job']:
            with self.assertRaises(Exception): manual.validate_url(url)
        with self.assertRaises(ValueError):
            manual.save(self.tracker,{'url':'https://example.com/new','Company':'X','Job Title':'Y','applied':True,'applied_date':'2027-01-01'},'2026-10-16')

    def test_import_reviews_details_without_writing_jobs(self):
        import json
        from types import SimpleNamespace
        app=Workspace(lambda:self.tracker)
        result=SimpleNamespace(returncode=0,stdout=json.dumps({'result':{'payloads':[{'text':json.dumps({'Company':'Test','Job Title':'Manager','Salary':'','description':'Public posting'})}]}}))
        with patch('dashboard.server.STATE',Path(self.temp.name)),patch('dashboard.server.subprocess.run',return_value=result):
            app.import_manual_worker('https://example.com/job')
        self.assertEqual(app.manual_import['status'],'ready')
        self.assertEqual(len(self.tracker.scout().rows),1)
        result.stdout=json.dumps({'result':{'payloads':[{'text':'{"blocked":"CAPTCHA"}'}]}})
        with patch('dashboard.server.STATE',Path(self.temp.name)),patch('dashboard.server.subprocess.run',return_value=result):
            app.import_manual_worker('https://example.com/job')
        self.assertEqual(app.manual_import['status'],'failed')
