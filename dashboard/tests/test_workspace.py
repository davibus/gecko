import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as dashboard
from google_tracker import Tab


def record(**values):
    data = {'Scout ID': 123, 'Source': 'Example', 'Company': 'Example Co', 'Job Title': 'Marketing Manager',
            'Job URL': 'https://example.com/jobs/123', 'Location': 'Utah', 'Work Arrangement': '',
            'Apply?': '', 'Applied': '', 'Cost': '', 'Notes': 'Preserve this note', 'Response': '',
            'Resume Created': '', 'Resume Link': '', 'Last Updated': 'historical run'}
    data.update(values)
    return data


class FakeTracker:
    def __init__(self, data=None):
        self.data = data or record()
        self.headers = {name: i + 1 for i, name in enumerate(self.data)}
        self.formulas = {}
        self.writes = []
        self.config = SimpleNamespace(spreadsheet_id='test')
        self.api = self
        self.corrupt_readback = False

    def scout(self, value_render_option='UNFORMATTED_VALUE'):
        data = copy.deepcopy(self.data)
        if value_render_option == 'FORMULA':
            data.update(self.formulas)
        return Tab('Job List', 99, dict(self.headers), [(2, data)], 100,
                   tuple(self.headers), {2: tuple(data[k] for k in self.headers)})

    def values(self):
        return self

    def batchUpdate(self, **kwargs):
        self.writes.append(kwargs['body'])
        for item in kwargs['body']['data']:
            cell = item['range'].split('!')[1]
            for field, col in self.headers.items():
                if cell == dashboard._col(col) + '2':
                    self.data[field] = item['values'][0][0]
        if self.corrupt_readback:
            self.data['Notes'] = 'Concurrent edit'
        return SimpleNamespace(execute=lambda: {})

    def _assert_scout_row_not_rejected(self, data):
        pass

    def url(self):
        return 'https://docs.google.com/spreadsheets/d/test/edit'


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(dashboard, 'STATE', Path(self.temp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def write(self, tracker, changes, original=None):
        tab = tracker.scout()
        return dashboard.write_verified(tracker, tab, 2, original or tab.rows[0][1], changes)

    def test_complete_daily_state_flow(self):
        t = FakeTracker()
        for action, payload in [('approve', {}), ('applied', {}), ('details', {'notes': 'Preserve this note\nFollow-up context', 'follow_up': '2026-10-23', 'stage': 'Interview'})]:
            changes = dashboard.changes_for(t.data, action, payload)
            job = self.write(t, changes)
        self.assertEqual(job['stage'], 'Interview')
        self.assertEqual(job['meta']['follow_up'], '2026-10-23')
        self.assertEqual(t.data['Applied'], 'X')
        self.assertEqual(t.data['Last Updated'], 'historical run')
        self.assertEqual(len(job['history']), 3)
        self.assertEqual(job['notes'], 'Preserve this note\nFollow-up context')
        self.assertTrue(all(x['valueInputOption'] == 'RAW' for x in t.writes))

    def test_stale_edit_does_not_write(self):
        t = FakeTracker()
        old = dict(t.data)
        t.data['Notes'] = 'New user note'
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.write(t, {'Notes': 'Overwrite'}, old)
        self.assertEqual(t.writes, [])

    def test_formula_blocks_entire_edit(self):
        t = FakeTracker()
        t.formulas['Notes'] = '=A1'
        with self.assertRaisesRegex(ValueError, 'formula-protected'):
            self.write(t, {'Notes': 'new', 'Apply?': 'Yes'})
        self.assertEqual(t.writes, [])

    def test_array_spill_blocks_edit(self):
        t = FakeTracker()
        t.formulas['Company'] = '=ARRAYFORMULA(A1:A)'
        with self.assertRaisesRegex(ValueError, 'formula-protected'):
            self.write(t, {'Notes': 'new'})
        self.assertEqual(t.writes, [])

    def test_reordered_headers_target_named_cells(self):
        t = FakeTracker(dict(reversed(list(record().items()))))
        self.write(t, {'Applied': 'X'})
        self.assertEqual(t.data['Applied'], 'X')
        self.assertEqual(t.data['Company'], 'Example Co')

    def test_readback_failure_not_success(self):
        t = FakeTracker(); t.corrupt_readback = True
        with self.assertRaisesRegex(RuntimeError, 'readback'):
            self.write(t, {'Notes': 'new'})

    def test_unmanaged_fields_rejected(self):
        t = FakeTracker()
        with self.assertRaises(ValueError):
            self.write(t, {'Resume Created': 'X'})
        self.assertEqual(t.writes, [])

    def test_existing_resume_marker_blocks_generation(self):
        job = dashboard.present(2, record(**{'Resume Created': ' x ', 'Apply?': 'Yes'}))
        self.assertFalse(job['can_generate'])
        self.assertTrue(any('regeneration is blocked' in x for x in job['issues']))

    def test_existing_link_blocks_generation_even_without_marker(self):
        job = dashboard.present(2, record(**{'Resume Link': 'file:///C:/missing.docx', 'Apply?': 'Yes'}))
        self.assertFalse(job['can_generate'])

    def test_eligibility_fee_expiration_and_unknown_location(self):
        for fields in [{'Cost':' X '}, {'Location':'Unknown'}, {dashboard.INDEED_APPLICATION_HEADER:'Expired'}]:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                dashboard.changes_for(record(**fields), 'approve', {})

    def test_decline_retains_job_and_manual_content(self):
        changes = dashboard.changes_for(record(), 'decline', {})
        self.assertEqual(changes['Apply?'], 'No')
        self.assertTrue(changes['Notes'].startswith('Preserve this note'))

    def test_duplicate_id_rejected(self):
        t = FakeTracker().scout(); t.rows.append((3, dict(t.rows[0][1])))
        with self.assertRaisesRegex(ValueError, 'duplicated'):
            dashboard.find_job(t, 123)

    def test_dates_and_stage_require_valid_state(self):
        for payload in [{'follow_up':'not-a-date'}, {'stage':'Interview'}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                dashboard.changes_for(record(), 'details', payload)

    def test_file_escape_and_script_url_rejected(self):
        self.assertIsNone(dashboard.resume_path({'Resume Link':'file:///C:/Windows/secrets.docx'}))
        self.assertEqual(dashboard.safe_url('javascript:alert(1)'), '')

    def test_applied_action_is_explicit_and_idempotence_guarded(self):
        self.assertNotIn('Applied', dashboard.changes_for(record(), 'approve', {}))
        with self.assertRaises(ValueError):
            dashboard.changes_for(record(Applied='X'), 'applied', {})

    def test_api_csrf_host_and_origin(self):
        srv = dashboard.ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
        srv.workspace = dashboard.Workspace(lambda: FakeTracker())
        thread = threading.Thread(target=srv.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{srv.server_port}'
        try:
            with urlopen(base + '/api/jobs') as response:
                snap = json.load(response)
            self.assertEqual(len(snap['jobs']), 1)
            req = Request(base+'/api/edit', data=b'{}', headers={'Content-Type':'application/json'}, method='POST')
            with self.assertRaises(HTTPError) as error:
                urlopen(req)
            self.assertEqual(error.exception.code, 403)
            for headers in [{'Host':'evil.test'}, {'Origin':'https://evil.test'}]:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base+'/api/jobs', headers=headers))
                self.assertEqual(error.exception.code, 403)
            body = json.dumps({'id':'123','version':snap['jobs'][0]['version'],'action':'approve'}).encode()
            with urlopen(Request(base+'/api/edit', data=body, headers={'Content-Type':'application/json','X-Gecko-Token':snap['token']}, method='POST')) as response:
                self.assertEqual(json.load(response)['stage'], 'Approved')
        finally:
            srv.shutdown(); srv.server_close(); thread.join()

    def test_targeted_resume_dispatch_preserves_exact_id(self):
        t = FakeTracker(record(**{'Apply?': 'Yes'}))
        app = dashboard.Workspace(lambda: t)
        with patch.object(dashboard.threading, 'Thread') as thread:
            result = app.start({'kind':'resume', 'id':'123', 'version':dashboard.version(t.data)})
        self.assertEqual(result['job_id'], 123)
        self.assertEqual(thread.call_args.kwargs['args'], ('resume', 123))
        self.assertEqual(t.writes, [])

    def test_completed_resume_dispatch_rejected_before_launch(self):
        t = FakeTracker(record(**{'Apply?':'Yes', 'Resume Created':'X'}))
        app = dashboard.Workspace(lambda:t)
        with patch.object(dashboard.threading, 'Thread') as thread, self.assertRaises(ValueError):
            app.start({'kind':'resume','id':'123','version':dashboard.version(t.data)})
        thread.assert_not_called()

    def test_running_operation_prevents_second_run(self):
        app = dashboard.Workspace(lambda:FakeTracker())
        app.operation = {'status':'running'}
        with self.assertRaisesRegex(ValueError, 'already running'):
            app.start({'kind':'gecko'})

    def test_resume_worker_uses_canonical_targeted_command_and_readback(self):
        app = dashboard.Workspace(lambda:FakeTracker())
        app.operation = {'status':'running'}
        with patch.object(dashboard.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run, patch.object(app, 'detail', return_value={'resume_available':True,'fields':{'Resume Created':'X'}}):
            app.worker('resume',123)
        self.assertEqual(run.call_args.args[0][-3:], [str(dashboard.ROOT/'scripts/generate_apply_queue.py'),'--ids','123'])
        self.assertEqual(app.operation['status'],'complete')

    def test_resume_skip_cannot_claim_success(self):
        app = dashboard.Workspace(lambda:FakeTracker())
        app.operation = {'status':'running'}
        with patch.object(dashboard.subprocess, 'run', return_value=SimpleNamespace(returncode=0)), patch.object(app, 'detail', return_value={'resume_available':False,'fields':{}}):
            app.worker('resume',123)
        self.assertEqual(app.operation['status'],'failed')

    def test_full_pipeline_failure_is_visible(self):
        app = dashboard.Workspace(lambda:FakeTracker())
        app.operation = {'status':'running'}
        with patch.object(dashboard.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as run:
            app.worker('gecko',None)
        self.assertEqual(run.call_args.args[0][-1],str(dashboard.ROOT/'scripts/run_gecko.py'))
        self.assertEqual(app.operation['status'],'failed')

    def test_google_clock_assertion_uses_sample_not_local_time(self):
        from google_auth_clock import GoogleClockCredentials
        credential = GoogleClockCredentials(signer=SimpleNamespace(), service_account_email='test@example.com',
                                            token_uri='https://oauth2.googleapis.com/token',scopes=['test-scope'])
        with patch('google_auth_clock.google_timestamp', return_value=10000), patch('google_auth_clock.jwt.encode',return_value=b'not-a-real-token') as encode:
            credential._make_authorization_grant_assertion()
        payload = encode.call_args.args[1]
        self.assertEqual((payload['iat'],payload['exp']),(10000,13600))
        self.assertEqual(payload['scope'],'test-scope')


if __name__ == '__main__':
    unittest.main()
