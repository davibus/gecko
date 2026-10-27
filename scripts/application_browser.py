"""One owned Chrome window and one reusable tab; no application actions on import."""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path
import re
import uuid

from application_runtime import ROOT, save, prior_attempt


class BrowserLifecycleError(RuntimeError):
    pass


class SubmissionUncertain(BrowserLifecycleError):
    pass


def saved_receipt(base, ident, state):
    path = Path(base)/str(ident)/'receipt.json'
    receipt = json.loads(path.read_text(encoding='utf-8')) if path.exists() else state.get('receipt')
    if not receipt:
        return None
    if (str(receipt.get('id')) != str(ident) or receipt.get('company') != state.get('company') or
            receipt.get('title') != state.get('title') or receipt.get('confirmation_verified') is not True or
            not str(receipt.get('confirmation_text', '')).strip()):
        raise BrowserLifecycleError('Saved receipt identity/confirmation needs reconciliation; preserve the tab')
    return receipt


def target_info(context, page):
    session = context.new_cdp_session(page)
    try:
        target = session.send('Target.getTargetInfo')['targetInfo']['targetId']
        window = session.send('Browser.getWindowForTarget', {'targetId': target})['windowId']
        return target, window
    finally:
        session.detach()


def save_recovery(page, packet, state, base, reason):
    """Save observable information, never imply the employer saved form entries."""
    import playwright_batch as batch
    from application_forms import missing_questions
    out = Path(base)/str(packet['id'])
    snap = batch.snapshot(page)
    if not snap.get('frames') or all('error' in fr for fr in snap['frames']):
        raise BrowserLifecycleError('Cannot save readable recovery evidence; leave the tab untouched')
    questions = state.get('missing_required', []) + state.get('unverified_required', []) + missing_questions(snap)
    recovery = dict(id=packet['id'], company=packet['company'], title=packet['title'],
        captured_at=datetime.now(timezone.utc).isoformat(), reason=reason, url=page.url,
        outcome=state.get('status', 'Interrupted'), blocker=state.get('blocker'),
        missing_questions=list(dict.fromkeys(q.get('question', str(q)) if isinstance(q, dict) else str(q) for q in questions)),
        resume=state.get('resume'), filled_answers=state.get('filled', []),
        submission_attempt=str(prior_attempt(packet, out) or ''), receipt=state.get('receipt'),
        server_saved_draft_verified=False,
        form_entries_persist=False,
        recovery_instruction='Reopen the exact URL, check employer submission state, then refill only confirmed answers and reverify the exact resume. Unsaved entries and uploads are not guaranteed to persist.',
        snapshot=snap)
    previous = out/'recovery.json'
    if previous.exists():
        save(out/'recovery-history'/f'{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}.json',
             json.loads(previous.read_text(encoding='utf-8')))
    save(previous, recovery)
    state.update(url=page.url, recovery_file=str(out/'recovery.json'),
                 recovery_url=page.url, form_entries_persist=False,
                 missing_required=state.get('missing_required', []))
    return recovery


class SingleApplicationTab:
    def __init__(self, context, base, archive, *, manifest=None):
        self.context = context
        self.base = Path(base)
        self.archive = archive
        self.path = Path(manifest or ROOT/'reports/playwright-pilot/application-browser.json')
        self.data = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {
            'token': uuid.uuid4().hex, 'targets': {}}
        self.page = None
        self.error = None
        self.listening = False

    def info(self, page):
        return target_info(self.context, page)

    def persist(self):
        save(self.path, self.data)

    def legacy_job(self, page):
        name = page.evaluate('window.name')
        match = re.fullmatch(r'gecko-(\d+)', name or '')
        if not match:
            return None
        ident = int(match[1])
        state_path = self.base/str(ident)/'state.json'
        if not state_path.exists():
            return None
        state = json.loads(state_path.read_text(encoding='utf-8'))
        urls = {state.get('url'), state.get('recovery_url')}
        latest = self.base/str(ident)/'latest.json'
        if latest.exists():
            urls.add(json.loads(latest.read_text(encoding='utf-8')).get('url'))
        return ident if page.url in urls else None

    def inventory(self):
        result = []
        for page in self.context.pages:
            if page.is_closed():
                continue
            target, window = self.info(page)
            known = self.data['targets'].get(target)
            ident = known.get('job_id') if known else self.legacy_job(page)
            owned = bool(known) or ident is not None
            result.append(dict(page=page, target=target, window=window, owned=owned, job_id=ident, url=page.url))
        return result

    def remember(self, page, job_id=None, phase='idle'):
        target, window = self.info(page)
        self.data['targets'][target] = dict(job_id=job_id, window=window)
        self.data.update(current_target=target, current_job=job_id, window=window, phase=phase)
        self.page = page
        page.set_default_timeout(8000)
        try:
            page.evaluate('(name)=>window.name=name', 'gecko-application-'+self.data['token'])
        except Exception:
            # Cross-origin navigation may clear/destroy window.name. The
            # persisted CDP target remains the ownership proof.
            if page.is_closed():
                raise
        self.persist()

    def create_window(self):
        session = self.context.browser.new_browser_cdp_session()
        try:
            with self.context.expect_page() as event:
                session.send('Target.createTarget', {'url': 'about:blank', 'newWindow': True})
            return event.value
        finally:
            session.detach()

    def uncertain(self, item):
        if item['job_id'] is None:
            return False
        path = self.base/str(item['job_id'])/'state.json'
        state = json.loads(path.read_text(encoding='utf-8'))
        packet = {'id': item['job_id'], 'url': item['url']}
        return bool(prior_attempt(packet, path.parent)) and not saved_receipt(self.base, item['job_id'], state) and not state.get('tracker', {}).get('verified')

    def reconcile(self, *, archive_all=False):
        """Archive and verify every retiring owned job before closing anything."""
        items = self.inventory()
        owned = [p for p in items if p['owned']]
        uncertain = [p for p in owned if self.uncertain(p)]
        survivor = (uncertain or [p for p in owned if p['target'] == self.data.get('current_target')] or owned or [None])[0]
        mixed = survivor and any(p['window'] == survivor['window'] and not p['owned'] for p in items)
        # Never remove an unrelated tab to achieve the dedicated-window count.
        # Isolate an owned survivor in a new window when the old window is mixed.
        retiring = [p for p in owned if p is not survivor or mixed]
        for item in owned:
            if archive_all or item['job_id'] is not None or item in retiring or self.data.get('phase') == 'in_progress':
                if not self.archive(item['page'], item['job_id'], 'window reconciliation'):
                    raise BrowserLifecycleError('Recovery/Sheet readback incomplete; tabs preserved')
        if not survivor or mixed:
            self.remember(self.create_window())
        else:
            self.remember(survivor['page'], survivor['job_id'], 'idle')
        for item in retiring:
            item['page'].close()
        self.verify('after reconciliation')
        if not self.listening:
            self.context.on('page', self.on_popup)
            self.listening = True
        if self.data.get('current_job') is not None:
            self.page.goto('about:blank')
            self.remember(self.page)
        return self.page

    def verify(self, boundary):
        if self.error:
            raise BrowserLifecycleError(self.error)
        items = self.inventory()
        owned = [p for p in items if p['owned']]
        here = [p for p in items if p['window'] == self.data.get('window')]
        if len(owned) != 1 or len(here) != 1 or here[0]['page'] != self.page:
            raise BrowserLifecycleError(f'{boundary}: expected one owned tab and one tab total in its window; found {len(owned)} owned, {len(here)} in window. Reconcile before continuing.')
        record = dict(boundary=boundary, verified_at=datetime.now(timezone.utc).isoformat(),
                      window=self.data['window'], target=self.data['current_target'],
                      dedicated_window_tab_count=len(here), owned_tab_count=len(owned),
                      unrelated_tabs=[dict(target=p['target'], window=p['window'], url=p['url']) for p in items if not p['owned']])
        save(self.base/'browser-tab-count.json', record)
        return record

    def begin(self, packet, state):
        self.verify('before job '+str(packet['id']))
        same_job = self.data.get('current_job') == packet['id'] and self.page.url != 'about:blank'
        if self.data.get('current_job') not in (None, packet['id']):
            raise BrowserLifecycleError('Previous job has not released the sole tab')
        self.remember(self.page, packet['id'], 'in_progress')
        self.active_packet, self.active_state = packet, state
        state.setdefault('started_at', datetime.now(timezone.utc).isoformat())
        if not same_job:
            state.update(draft_opened=True, url=state.get('recovery_url') or packet['url'])
            save(self.base/str(packet['id'])/'state.json', state)
            self.page.goto(state['url'], wait_until='domcontentloaded', timeout=35000)
        state['url'] = self.page.url
        return self.page

    def on_popup(self, popup):
        """Only a popup with the current owned opener may replace that tab."""
        try:
            if popup.opener() != self.page:
                return
            old = self.page
            ident = self.data.get('current_job')
            target, window = self.info(popup)
            self.data['targets'][target] = dict(job_id=ident, window=window)
            self.persist()
            if not self.archive(old, ident, 'popup handoff'):
                raise BrowserLifecycleError('Cannot save popup handoff recovery information')
            # Persist new target before closing old: interruption can recover both.
            self.remember(popup, ident, 'in_progress')
            old.close()
            self.verify('after popup handoff')
        except Exception as exc:
            self.error = 'Popup handoff paused: '+str(exc)

    def after_outcome(self, packet, state, *, uncertain=False):
        self.verify('after outcome '+str(packet['id']))
        if not state.get('outcome_tracker', {}).get('verified'):
            raise BrowserLifecycleError('Sheet outcome not verified; do not navigate')
        if uncertain:
            state.update(submission_uncertain=True, never_automatically_retry=True, batch_blocker=False)
        if self.data.get('current_job') == packet['id']:
            self.page.goto('about:blank')
            self.remember(self.page)
        state.update(draft_opened=False, browser_released=True, form_entries_persist=False)
        self.verify('between jobs')

    def detach(self):
        if self.listening:
            self.context.remove_listener('page', self.on_popup)
            self.listening = False


def recovery_archiver(base, tracker, lifecycle_ref):
    """Capture first; publish only job outcomes, not intermediate popup handoffs."""
    base = Path(base)
    def archive(page, ident, reason):
        if ident is None:
            return True
        state_path = base/str(ident)/'state.json'
        manager = lifecycle_ref[0] if lifecycle_ref else None
        if manager and getattr(manager, 'active_packet', {}).get('id') == ident:
            packet, state = manager.active_packet, manager.active_state
        else:
            state = json.loads(state_path.read_text(encoding='utf-8'))
            packet_path = base/str(ident)/'packet.json'
            if packet_path.exists():
                packet = json.loads(packet_path.read_text(encoding='utf-8'))
            else:
                inventory = base/'selected.json' if (base/'selected.json').exists() else base/'packets.json'
                packet = next(p for p in json.loads(inventory.read_text(encoding='utf-8')) if str(p['id']) == str(ident))
                packet = dict(packet, url=packet['row']['Job URL'])
        recovery = save_recovery(page, packet, state, base, reason)
        save(state_path, state)
        if reason == 'popup handoff':
            return True
        receipt = saved_receipt(base, ident, state)
        if receipt and not state.get('tracker', {}).get('verified'):
            verified_receipt = tracker.call('receipt', receipt=receipt)
            if not verified_receipt.get('verified'):
                raise BrowserLifecycleError('Saved employer receipt requires Applied/date readback before tab reuse')
            state.update(receipt=receipt, tracker=verified_receipt)
        uncertain = bool(prior_attempt(packet, state_path.parent)) and not state.get('receipt') and not state.get('tracker', {}).get('verified')
        if uncertain:
            state.update(status='Submission unconfirmed', submission_uncertain=True,
                         never_automatically_retry=True, batch_blocker=False,
                         blocker='Prior submission attempt requires employer-state reconciliation; never automatically resubmit')
        elif state.get('receipt') and state.get('tracker', {}).get('verified'):
            state.update(status='Applied - employer confirmed', blocker=None)
        elif not state.get('outcome_tracker', {}).get('verified'):
            state.update(status='Needs attention', blocker=state.get('blocker') or 'Interrupted before a verified outcome; saved entries are not guaranteed to persist')
        result = dict(id=ident, company=packet['company'], title=packet['title'],
            job_url=packet['row']['Job URL'], captcha=bool(state.get('captcha')),
            note=f"Single-tab recovery | {state['status']} | {state.get('blocker') or 'Verified outcome'} | URL: {page.url} | Required: {', '.join(recovery['missing_questions']) or 'None recorded'} | Recovery: {state['recovery_file']} | Unsaved entries/uploads are not guaranteed to persist.")
        save(state_path.parent/'browser-recovery-publication.json', result)
        for attempt in range(2):
            try:
                verified = tracker.call('outcome', result=result)
                if not verified.get('verified'):
                    raise BrowserLifecycleError('Recovery Sheet readback incomplete')
                break
            except Exception:
                if attempt:
                    raise
        state.update(browser_recovery_tracker=verified, outcome_tracker=verified,
                     browser_released=True, draft_opened=False, form_entries_persist=False)
        if uncertain:
            state['category'] = 'unconfirmed'
        state.setdefault('category', 'captcha' if state.get('captcha') else
                         'submitted' if state.get('receipt') and state.get('tracker', {}).get('verified') else 'blocked')
        if 'elapsed_seconds' not in state:
            if state.get('started_at'):
                state['elapsed_seconds'] = state.get('prior_elapsed_seconds', 0) + (datetime.now(timezone.utc)-datetime.fromisoformat(state['started_at'])).total_seconds()
            else:
                state['elapsed_seconds'] = 0
                state['elapsed_unknown'] = True
        save(state_path, state)
        return True
    return archive


@contextmanager
def request_tab_session(context, base, packet, state):
    """The explicit request fallback shares the same ownership/publication gate."""
    from application_runtime import TrackerClient, BatchSources, Timings, batch_lock
    from playwright_fast import batch_session
    with batch_lock(ROOT/'reports/playwright-pilot/sequential.lock'), batch_lock(Path(base)/'batch.lock'):
        tracker = TrackerClient()
        ref = []
        manager = SingleApplicationTab(context, base, recovery_archiver(base, tracker, ref))
        ref.append(manager)
        try:
            items = manager.inventory()
            current = next((p for p in items if p['target'] == manager.data.get('current_target')), None)
            if current and manager.data.get('current_job') == packet['id']:
                manager.remember(current['page'], packet['id'], manager.data.get('phase', 'in_progress'))
                manager.verify('before explicit request')
                manager.context.on('page', manager.on_popup)
                manager.listening = True
            else:
                manager.reconcile()
            manager.active_packet, manager.active_state = packet, state
            with batch_session(tracker, BatchSources().refresh(), Timings(), manager):
                yield manager
            if manager.data.get('current_job') == packet['id']:
                manager.archive(manager.page, packet['id'], 'explicit request outcome')
                manager.after_outcome(packet, state, uncertain=state.get('submission_uncertain', False))
                save(Path(base)/str(packet['id'])/'state.json', state)
            manager.verify('explicit request complete')
        finally:
            manager.detach()
            tracker.close()
