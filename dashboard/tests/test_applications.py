import json
from contextlib import nullcontext
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
from test_sqlite_tracker import SQLiteTrackerTests
from dashboard import applications, server

class ApplicationTests(SQLiteTrackerTests):
    def setUp(self):
        super().setUp()
        self.state=Path(self.temp.name)/'dashboard'
        self.patch=patch.object(server,'STATE',self.state);self.patch.start();self.addCleanup(self.patch.stop)
        self.app=server.Workspace(lambda:self.tracker)
        self.app.activity=lambda:{'busy':False,'operation':self.app.operation}

    def select(self, created=True):
        if created:
            with self.tracker.connection() as con,con:
                data=json.loads(con.execute("SELECT values_json FROM workspace_records WHERE dataset='Job List' AND slot=2").fetchone()[0])
                data['Resume Created']=' x '
                con.execute("UPDATE workspace_records SET values_json=? WHERE dataset='Job List' AND slot=2",(json.dumps(data),))
        data=self.tracker.scout().rows[0][1]
        with patch.object(applications.threading,'Thread') as thread:
            result=applications.start(self.app,{'jobs':[{'id':'10','version':server.version(data)}]})
        thread.return_value.start.assert_called_once()
        return result

    def run_result(self, result):
        self.select()
        with patch.object(server,'run_lock',return_value=nullcontext()),patch.object(server,'resume_path',return_value=Path('matching.docx')),patch.object(applications,'invoke',return_value=result) as invoke:
            applications.worker(self.app)
        return invoke

    def test_exact_selection_and_stale_rejected(self):
        self.assertEqual(self.select()['job_ids'],['10'])
        self.app.operation=None
        with self.assertRaisesRegex(ValueError,'changed'):
            applications.start(self.app,{'jobs':[{'id':'10','version':'old'}]})
        self.assertFalse(self.tracker.scout().rows[0][1]['Applied'])

    def test_confirmed_receipt_records_application(self):
        invoke=self.run_result({'job_id':'10','job_url':'https://example.com/jobs/10','status':'submitted','reason':'Receipt verified','application_url':'https://example.com/jobs/10/receipt','confirmation_text':'Your application has been received','confirmed_company':'Example','confirmed_title':'Paid Search Manager'})
        invoke.assert_called_once()
        data=self.tracker.scout().rows[0][1]
        self.assertEqual(data['Applied'],'X')
        self.assertTrue(data['Notes'].startswith('Keep my notes'))
        self.assertEqual(self.app.operation['items'][0]['status'],'submitted')

    def test_captcha_does_not_mark_applied(self):
        self.run_result({'job_id':'10','job_url':'https://example.com/jobs/10','status':'needs_attention','reason':'Complete the CAPTCHA','application_url':'https://example.com/jobs/10'})
        self.assertFalse(self.tracker.scout().rows[0][1]['Applied'])
        self.assertEqual(self.app.operation['status'],'needs attention')

    def test_wrong_receipt_identity_does_not_mark_applied(self):
        self.run_result({'job_id':'99','job_url':'https://example.com/wrong','status':'submitted'})
        self.assertFalse(self.tracker.scout().rows[0][1]['Applied'])
        self.assertEqual(self.app.operation['items'][0]['status'],'unconfirmed')

    def test_previous_uncertain_attempt_cannot_be_retried(self):
        self.run_result({'job_id':'99','job_url':'https://example.com/wrong','status':'submitted'})
        receipt=self.state/'applications/job-10.json'
        before=receipt.read_text()
        invoke=self.run_result({'job_id':'10','status':'submitted'})
        invoke.assert_not_called()
        self.assertEqual(receipt.read_text(),before)
        self.assertFalse(self.tracker.scout().rows[0][1]['Applied'])

    def test_missing_resume_is_held_without_dispatch(self):
        self.select()
        with patch.object(server,'run_lock',return_value=nullcontext()),patch.object(server,'resume_path',return_value=None),patch.object(applications,'invoke') as invoke:
            applications.worker(self.app)
        invoke.assert_not_called()
        self.assertEqual(self.app.operation['items'][0]['status'],'needs_attention')

    def test_uncreated_resume_is_held_even_if_file_exists(self):
        self.select(created=False)
        with patch.object(server,'run_lock',return_value=nullcontext()),patch.object(server,'resume_path',return_value=Path('matching.docx')),patch.object(applications,'invoke') as invoke:
            applications.worker(self.app)
        invoke.assert_not_called()
        self.assertIn('not marked created',self.app.operation['items'][0]['reason'])

    def test_already_applied_selection_is_skipped_without_dispatch(self):
        with self.tracker.connection() as con,con:
            data=json.loads(con.execute("SELECT values_json FROM workspace_records WHERE dataset='Job List' AND slot=2").fetchone()[0])
            data['Applied']='X'
            con.execute("UPDATE workspace_records SET values_json=? WHERE dataset='Job List' AND slot=2",(json.dumps(data),))
        self.select()
        with patch.object(server,'run_lock',return_value=nullcontext()),patch.object(applications,'invoke') as invoke:
            applications.worker(self.app)
        invoke.assert_not_called()
        self.assertEqual(self.app.operation['items'][0]['status'],'skipped')

    def test_held_job_does_not_block_next_selection(self):
        self.select()
        self.app.operation=None
        with self.tracker.connection() as con,con:
            data=json.loads(con.execute("SELECT values_json FROM workspace_records WHERE dataset='Job List' AND slot=2").fetchone()[0])
            data.update({'ID':11,'Job URL':'https://example.com/jobs/11'})
            con.execute("INSERT INTO workspace_records(dataset,slot,values_json) VALUES('Job List',3,?)",(json.dumps(data),))
        selected=[{'id':str(data['Scout ID']),'version':server.version(data)} for _,data in self.tracker.scout().rows]
        with patch.object(applications.threading,'Thread'):
            applications.start(self.app,{'jobs':selected})
        def outcome(app,item,data,resume,folder):
            return {'job_id':item['id'],'job_url':item['url'],'status':'needs_attention','reason':'Human answer needed'}
        with patch.object(server,'run_lock',return_value=nullcontext()),patch.object(server,'resume_path',return_value=Path('matching.docx')),patch.object(applications,'invoke',side_effect=outcome) as invoke:
            applications.worker(self.app)
        self.assertEqual(invoke.call_count,2)
        self.assertTrue(all(i['status']=='needs_attention' for i in self.app.operation['items']))
