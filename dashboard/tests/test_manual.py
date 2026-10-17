import sys
from pathlib import Path
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2]/'scripts')]
from test_sqlite_tracker import SQLiteTrackerTests
from dashboard import manual
from dashboard.server import Workspace

class ManualTests(SQLiteTrackerTests):
    def setUp(self):
        super().setUp()
        from storage import JobStore
        JobStore(self.db).close()

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
