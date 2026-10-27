"""Isolated checks for the scoped sequential publication gate."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_application_workflow import MockSheets
from playwright_tracker import PrimaryTracker, check_row
from playwright_fast import run_sequential


class SequentialTests(unittest.TestCase):
    def client(self):
        row = {'ID': '101', 'Scout ID': '101', 'Company': 'Example', 'Job Title': 'Role',
               'Applied': '', 'Applied Date': '', 'Resume Link': 'file:///fixture.docx',
               'Resume Created': 'X', 'Apply?': 'Yes', 'Qualifies to Apply?': 'Yes',
               'Job URL': 'https://example.com/101', 'Source': 'Company', 'Cost': '',
               'Ready to Apply?': ' x ', 'Capture': '', 'Notes': 'manual note',
               'Previous Applied Date': '2025-01-01'}
        headers = [k for k in row if k not in ('Scout ID', 'Apply?')]
        remote = MockSheets([(9, row)], headers)
        return PrimaryTracker(SimpleNamespace(spreadsheet_id='mock'), remote), remote

    def test_ready_and_existing_capture_gates(self):
        client, remote = self.client()
        self.assertIsNone(client.application_check(101)['skip'])
        remote.rows[0][1]['Ready to Apply?'] = ''
        self.assertIn('not X', client.application_check(101)['skip'])
        remote.rows[0][1]['Ready to Apply?'] = 'X'
        remote.rows[0][1]['Capture'] = ' x '
        self.assertIn('CAPTCHA', client.application_check(101)['skip'])
        with self.assertRaisesRegex(ValueError, 'CAPTCHA'):
            check_row(remote.rows[0][1])

    def test_manual_applied_updates_win_over_old_captcha_and_readiness(self):
        client,remote=self.client()
        remote.rows[0][1].update({'Applied':'x','Applied Date':'10-27-26','Capture':'X','Ready to Apply?':'X'})
        self.assertEqual(client.application_check(101)['skip'],'Already Applied')
        self.assertFalse(remote.calls)
        self.assertEqual(remote.rows[0][1]['Applied Date'],'10-27-26')

    def test_notes_append_existing_capture_readback_idempotent(self):
        client, remote = self.client()
        result = dict(id=101, company='Example', title='Role', job_url='https://example.com/101', note='CAPTCHA | URL: https://example.com/101 | Elapsed 00:02', captcha=True)
        self.assertTrue(client.outcome(result)['verified'])
        self.assertEqual(remote.rows[0][1]['Notes'], 'manual note\n' + result['note'])
        self.assertEqual(remote.rows[0][1]['Capture'], 'X')
        self.assertEqual(remote.rows[0][1]['Previous Applied Date'], '2025-01-01')
        self.assertEqual(client.outcome(result)['cells_written'], 0)
        remote.formulas = {'Notes': '=TODAY()'}
        with self.assertRaisesRegex(ValueError, 'formula protected'):
            client.outcome(result)

    def test_stop_before_next_job_when_outcome_unverified(self):
        events = []
        class Tracker:
            def call(self, action, **kw):
                events.append((action, kw.get('id')))
                if action == 'application_check':
                    return {'skip': 'Ready to Apply is not X'}
                raise RuntimeError('readback unavailable')
        items = [dict(id=i, company='Example', title='Role', row={'Job URL': f'https://example.com/{i}'}) for i in (101, 102)]
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, 'readback unavailable'):
                run_sequential(None, items, Tracker(), None, Path(folder), allow_submit=True,
                    lifecycle=SimpleNamespace(data={}, verify=lambda *a: None, after_outcome=lambda *a, **k: None))
        self.assertEqual(events, [('application_check', 101), ('outcome', None), ('outcome', None)])

    def test_outcomes_verified_before_next_job(self):
        events = []
        class Tracker:
            def call(self, action, **kw):
                events.append((action, kw.get('id', kw.get('result', {}).get('id'))))
                if action == 'application_check':
                    return {'skip': 'Ready to Apply is not X'}
                return {'verified': True}
        items = [dict(id=i, company='Example', title='Role', row={'Job URL': f'https://example.com/{i}'}) for i in (102, 101)]
        with tempfile.TemporaryDirectory() as folder, patch('playwright_fast.exact_pages', return_value=[]):
            reports = run_sequential(None, items, Tracker(), None, Path(folder), allow_submit=True,
                lifecycle=SimpleNamespace(data={}, verify=lambda *a: None, after_outcome=lambda *a, **k: None))
            self.assertTrue(all(r['elapsed_seconds'] > 0 for r in reports))
            self.assertEqual(events, [('application_check', 102), ('outcome', 102), ('application_check', 101), ('outcome', 101)])


if __name__ == '__main__':
    unittest.main()
