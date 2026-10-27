"""Real local Chrome DOMs, mocked Sheet writes; no employer requests."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from application_browser import (SingleApplicationTab, recovery_archiver, BrowserLifecycleError,
                                 SubmissionUncertain, request_tab_session)
from application_runtime import save, Checkpoints, claim_attempt
from playwright_fast import run_sequential
from test_application_workflow import fixture_sources


class LocalTracker:
    def __init__(self, packets, context):
        self.packets = {p['id']: p for p in packets}
        self.context = context
        self.events = []
        self.fail_outcome = False
        self.outcomes = []
    def call(self, action, **kw):
        ident = kw.get('id') or kw.get('result', kw.get('receipt', {})).get('id')
        self.events.append((action, ident, len(self.context.pages)))
        if action == 'application_check':
            return {'skip': None, 'row': deepcopy(self.packets[ident]['row'])}
        if action == 'prepare':
            return deepcopy(self.packets[ident])
        if action == 'check':
            return deepcopy(self.packets[ident]['row'])
        if action == 'outcome':
            self.last_outcome = deepcopy(kw['result'])
            self.outcomes.append(deepcopy(kw['result']))
            if self.fail_outcome:
                raise RuntimeError('Sheet readback unavailable')
            if 'job outcome' not in kw['result']['note']:
                pass
            return {'verified': True}
        if action == 'receipt':
            return {'verified': True, 'Applied': 'X', 'Applied Date': '2026-10-26'}
        raise AssertionError(action)
    def close(self):
        pass


class LifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel='chrome', headless=True)
    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.sources = fixture_sources(self.base)
        self.html = {}
        self.requests = []
        def route(r):
            self.requests.append(r.request.url)
            if r.request.url not in self.html:
                r.abort()
            else:
                r.fulfill(status=200, content_type='text/html', body=self.html[r.request.url])
        self.context.route('**/*', route)
    def packet(self, ident, extra='', button=None):
        path = self.base/f'resume-{ident}.docx'
        path.write_bytes(b'fixture resume')
        url = f'https://jobs.example/{ident}'
        row = {'Company': 'Example', 'Job Title': 'Example role', 'Job URL': url,
               'Resume Link': path.as_uri(), 'Ready to Apply?': 'X', 'Applied': ''}
        packet = dict(id=ident, company='Example', title='Example role', row=row, url=url,
                      resume=str(path), resume_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.html[url] = ('<h1>Example - Example role</h1>'
            '<label>Full name<input name="name" required></label>'
            '<label>Email<input name="email" required type="email"></label>'
            '<label>Resume<input name="resume" required type="file"></label>' + extra +
            (button or '<button onclick="document.body.innerHTML=\'<h1>Application received!</h1>\'">Submit application</button>'))
        return packet
    def manager(self, tracker):
        ref = []
        manager = SingleApplicationTab(self.context, self.base,
            recovery_archiver(self.base, tracker, ref), manifest=self.base/'browser.json')
        ref.append(manager)
        # Headless test contexts have no user window. Exercise actual tabs/CDP
        # targets while mapping this isolated context to one logical window.
        original_info = manager.info
        manager.info = lambda page: (original_info(page)[0], getattr(page, '_fixture_window', 1))
        manager.create_window = self.context.new_page
        manager.reconcile()
        self.addCleanup(manager.detach)
        return manager
    def run_batch(self, packets, tracker=None, manager=None):
        tracker = tracker or LocalTracker(packets, self.context)
        manager = manager or self.manager(tracker)
        reports = run_sequential(self.context, packets, tracker, self.sources, self.base,
                                 allow_submit=True, lifecycle=manager)
        return reports, tracker, manager
    def test_many_blocked_captcha_and_successful_jobs_reuse_exact_target(self):
        packets = [self.packet(i, '<label>Unknown screening answer<input required name="unknown"></label>' if i < 104 else
                               '<div>Human Check: I am not a robot</div>' if i < 107 else '') for i in range(101, 110)]
        tracker = LocalTracker(packets, self.context)
        manager = self.manager(tracker)
        target = manager.info(manager.page)[0]
        reports, _, _ = self.run_batch(packets, tracker, manager)
        self.assertEqual([r['category'] for r in reports], ['blocked']*3 + ['captcha']*3 + ['submitted']*3)
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(manager.info(manager.page)[0], target)
        self.assertEqual(manager.page.url, 'about:blank')
        self.assertTrue(all(count == 1 for _, _, count in tracker.events))
        for p in packets:
            recovery = json.loads((self.base/str(p['id'])/'recovery.json').read_text())
            self.assertEqual(recovery['url'], p['url'])
            self.assertFalse(recovery['form_entries_persist'])
        checks = [e for e in tracker.events if e[0] in ('application_check', 'outcome')]
        self.assertEqual([(e[0], e[1]) for e in checks],
                         [event for p in packets for event in [('application_check', p['id']), ('outcome', p['id'])]])
    def test_popup_submit_handoff_closes_old_tab_and_records_receipt(self):
        popup_url = 'https://jobs.example/receipt'
        self.html[popup_url] = '<h1>Application received!</h1>'
        p = self.packet(101, button=f'<button onclick="window.open(\'{popup_url}\', \'_blank\')">Submit application</button>')
        tracker = LocalTracker([p], self.context)
        manager = self.manager(tracker)
        old = manager.page
        reports, _, _ = self.run_batch([p], tracker, manager)
        self.assertEqual(reports[0]['category'], 'submitted')
        self.assertTrue(old.is_closed())
        self.assertEqual(len(self.context.pages), 1)
        self.assertTrue((self.base/'101/receipt.json').exists())
        self.assertEqual(manager.verify('test')['dedicated_window_tab_count'], 1)

    def test_popup_next_step_blocker_then_next_job_still_has_one_tab(self):
        popup_url = 'https://jobs.example/101/application'
        self.html[popup_url] = '<h1>Example - Example role</h1><label>Unknown required response<input name="unknown" required></label><button>Submit application</button>'
        one = self.packet(101, button=f'<button onclick="window.open(\'{popup_url}\', \'_blank\')">Next</button>')
        two = self.packet(102)
        tracker = LocalTracker([one, two], self.context)
        manager = self.manager(tracker)
        old = manager.page
        reports, _, _ = self.run_batch([one, two], tracker, manager)
        self.assertTrue(old.is_closed())
        self.assertEqual([r['category'] for r in reports], ['blocked', 'submitted'])
        self.assertTrue(all(count == 1 for _, _, count in tracker.events))
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(json.loads((self.base/'101/recovery.json').read_text())['url'], popup_url)
    def test_uncertain_submit_is_verified_and_next_job_uses_same_tab_without_retry(self):
        one = self.packet(101)
        two = self.packet(102)
        tracker = LocalTracker([one, two], self.context)
        manager = self.manager(tracker)
        def uncertain(page, packet, state, command, out):
            if packet['id'] != one['id']:
                return original_submit(page, packet, state, command, out)
            claim_attempt(packet, out, {'id': packet['id'], 'url': page.url})
            raise RuntimeError('Confirmation timed out')
        import playwright_batch as batch
        original_submit = batch.submit
        with patch('playwright_batch.submit', side_effect=uncertain):
            reports, _, _ = self.run_batch([one, two], tracker, manager)
        self.assertEqual([r['category'] for r in reports], ['unconfirmed', 'submitted'])
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(manager.page.url, 'about:blank')
        state = json.loads((self.base/'101/state.json').read_text())
        self.assertTrue(state['submission_uncertain'])
        self.assertTrue(state['outcome_tracker']['verified'])
        self.assertTrue(state['never_automatically_retry'])
        self.assertTrue((self.base/'101/recovery.json').exists())
        manager.detach()
        restored = SingleApplicationTab(self.context, self.base, manager.archive, manifest=self.base/'browser.json')
        restored.info = manager.info
        restored.reconcile()
        self.addCleanup(restored.detach)
        self.assertEqual(len(self.context.pages), 1)
    def test_failed_publication_does_not_navigate_or_start_next_job(self):
        one = self.packet(101, '<label>Unknown<input name="unknown" required></label>')
        two = self.packet(102)
        tracker = LocalTracker([one, two], self.context)
        tracker.fail_outcome = True
        manager = self.manager(tracker)
        with self.assertRaisesRegex(RuntimeError, 'Sheet readback unavailable'):
            self.run_batch([one, two], tracker, manager)
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(manager.page.url, one['url'])
        self.assertFalse(any(ident == 102 for _, ident, _ in tracker.events))

    def test_post_submit_captcha_is_marked_then_next_job_continues_in_sole_tab(self):
        one, two = self.packet(101), self.packet(102)
        tracker = LocalTracker([one, two], self.context)
        manager = self.manager(tracker)
        def challenge(page, packet, state, command, out):
            if packet['id'] != one['id']:
                return original_submit(page, packet, state, command, out)
            claim_attempt(packet, out, {'id': packet['id'], 'url': page.url})
            page.set_content('<h1>Example - Example role</h1><p>Human check: I am not a robot</p>')
            raise RuntimeError('No employer confirmation')
        import playwright_batch as batch
        original_submit = batch.submit
        with patch('playwright_batch.submit', side_effect=challenge):
            reports, _, _ = self.run_batch([one, two], tracker, manager)
        self.assertTrue(tracker.outcomes[0]['captcha'])
        self.assertEqual([r['category'] for r in reports], ['unconfirmed', 'submitted'])
        state = json.loads((self.base/'101/state.json').read_text())
        self.assertTrue(state['captcha'])
        self.assertTrue(state['submission_uncertain'])
        self.assertEqual(state['category'], 'unconfirmed')
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(manager.page.url, 'about:blank')
    def test_interruption_reconciles_saved_information_then_reuses_one_tab(self):
        one = self.packet(101, '<label>Unknown<input name="unknown" required></label>')
        two = self.packet(102)
        tracker = LocalTracker([one, two], self.context)
        manager = self.manager(tracker)
        state = Checkpoints(self.base).read(one)
        save(self.base/'101/packet.json', one)
        manager.begin(one, state)
        manager.detach()  # Simulated process interruption before publication.
        fresh = SingleApplicationTab(self.context, self.base, manager.archive, manifest=self.base/'browser.json')
        fresh.info = manager.info
        fresh.create_window = self.context.new_page
        fresh.reconcile()
        self.addCleanup(fresh.detach)
        self.assertEqual(len(self.context.pages), 1)
        saved = json.loads((self.base/'101/state.json').read_text())
        self.assertTrue(saved['outcome_tracker']['verified'])
        self.assertFalse(saved['form_entries_persist'])
        reports, _, _ = self.run_batch([one, two], tracker, fresh)
        self.assertEqual(reports[-1]['category'], 'submitted')
        self.assertEqual(len(self.context.pages), 1)

    def test_interrupted_positive_receipt_is_reconciled_without_refilling_or_resubmitting(self):
        packet = self.packet(101)
        tracker = LocalTracker([packet], self.context)
        manager = self.manager(tracker)
        state = Checkpoints(self.base).read(packet)
        save(self.base/'101/packet.json', packet)
        manager.begin(packet, state)
        claim_attempt(packet, self.base/'101', {'id': 101, 'url': packet['url']})
        save(self.base/'101/receipt.json', dict(id=101, company='Example', title='Example role',
             confirmation_verified=True, confirmation_text='Application received!', submitted_at='2026-10-26T22:00:00+00:00'))
        manager.detach()
        restored = SingleApplicationTab(self.context, self.base, manager.archive, manifest=self.base/'browser.json')
        restored.info = manager.info
        restored.reconcile()
        self.addCleanup(restored.detach)
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(restored.page.url, 'about:blank')
        self.assertEqual([e[0] for e in tracker.events], ['receipt', 'outcome'])
        state = json.loads((self.base/'101/state.json').read_text())
        self.assertTrue(state['tracker']['verified'])
        self.assertEqual(state['category'], 'submitted')
    def test_unrelated_tab_is_never_closed_to_meet_window_count(self):
        packet = self.packet(101)
        tracker = LocalTracker([packet], self.context)
        manager = self.manager(tracker)
        unrelated = self.context.new_page()
        unrelated.set_content('<p>User-owned notes</p>')
        with self.assertRaises(BrowserLifecycleError):
            manager.verify('before job')
        manager.detach()
        def create():
            page = self.context.new_page()
            page._fixture_window = 2
            return page
        manager.create_window = create
        manager.reconcile()
        self.assertFalse(unrelated.is_closed())
        self.assertEqual(manager.verify('isolated')['dedicated_window_tab_count'], 1)
        self.assertEqual(len(self.context.pages), 2)

    def test_recover_multiple_legacy_blocked_tabs_only_after_all_sheet_readbacks(self):
        packets = [self.packet(i) for i in (101, 102, 103)]
        tracker = LocalTracker(packets, self.context)
        manager = self.manager(tracker)
        manager.detach()
        old = []
        for packet in packets:
            page = self.context.new_page()
            page.goto(packet['url'])
            page.evaluate('(n)=>window.name=n', f"gecko-{packet['id']}")
            save(self.base/str(packet['id'])/'packet.json', packet)
            save(self.base/str(packet['id'])/'state.json', dict(id=packet['id'], company='Example', title='Example role',
                url=page.url, status='Needs attention', category='blocked', elapsed_seconds=1,
                blocker='Missing confirmed response', outcome_tracker={'verified': True}))
            old.append(page)
        manager.reconcile(archive_all=True)
        self.assertTrue(all(p.is_closed() for p in old))
        self.assertEqual(len(self.context.pages), 1)
        for packet in packets:
            state = json.loads((self.base/str(packet['id'])/'state.json').read_text())
            self.assertTrue(state['browser_recovery_tracker']['verified'])
            self.assertTrue((self.base/str(packet['id'])/'recovery.json').exists())

    def test_explicit_request_fallback_uses_same_tab_and_publication_gate(self):
        import playwright_batch as batch
        packet = self.packet(101, '<label>Unknown response<input name="unknown" required></label>')
        tracker = LocalTracker([packet], self.context)
        manager = self.manager(tracker)
        target = manager.info(manager.page)[0]
        state = Checkpoints(self.base).read(packet)
        with patch('application_runtime.TrackerClient', return_value=tracker), \
             patch('application_runtime.BatchSources', return_value=self.sources), \
             patch('application_browser.ROOT', self.base), \
             patch('application_browser.SingleApplicationTab', return_value=manager):
            with request_tab_session(self.context, self.base, packet, state) as active:
                page = active.begin(packet, state)
                batch.fill_supported(page, packet, state)
        self.assertEqual(len(self.context.pages), 1)
        self.assertEqual(manager.info(manager.page)[0], target)
        self.assertEqual(manager.page.url, 'about:blank')
        self.assertTrue(state['outcome_tracker']['verified'])
        self.assertFalse(state['form_entries_persist'])
        self.assertEqual([e[0] for e in tracker.events], ['outcome'])


if __name__ == '__main__':
    unittest.main()
