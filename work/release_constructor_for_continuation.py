"""Verify 2972, preserve its no-retry evidence, release the same tab for 87 jobs."""
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from playwright.sync_api import sync_playwright
from application_runtime import TrackerClient, Checkpoints, save, batch_lock
from application_browser import SingleApplicationTab, save_recovery

base = ROOT/'reports/playwright-pilot/sequential-2954-3060-except-2995-20261026'
ids = [i for i in range(2973,3061) if i != 2995]
assert len(ids)==87 and 3046 in ids and 2972 not in ids
with batch_lock(ROOT/'reports/playwright-pilot/sequential.lock'), batch_lock(base/'batch.lock'):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = base/'resume-history'/stamp
    for name in ('selected.json','batch-summary.json','progress.json','current-progress.json','batch-start.json'):
        path = base/name
        if path.exists():
            save(backup/name, json.loads(path.read_text(encoding='utf-8')))
    cp = Checkpoints(base)
    packet = json.loads((base/'2972/packet.json').read_text(encoding='utf-8'))
    state = cp.read(packet)
    save(backup/'constructor-2972-state.json', state)
    assert (base/'2972/submission-attempt.json').exists() and state.get('submission_uncertain')
    tracker = TrackerClient()
    try:
        before = tracker.call('application_check', id=2972)['row']
        cap = next(k for k in before if k.strip().casefold() in ('capture','captcha'))
        assert str(before[cap]).strip().upper()=='X' and not str(before['Applied']).strip()
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp('http://127.0.0.1:9333')
            manager = SingleApplicationTab(browser.contexts[0], base, lambda *args: False)
            manager.page = next(p['page'] for p in manager.inventory() if p['target']==manager.data['current_target'])
            assert manager.data['current_job']==2972
            original_target = manager.data['current_target']
            manager.verify('Constructor continuation override - before publication')
            save_recovery(manager.page, packet, state, base, 'User authorized unrelated jobs to continue; Constructor never automatically retried')
            result = dict(id=2972, company=packet['company'], title=packet['title'], job_url=packet['row']['Job URL'], captcha=True,
                note=f"Continuation override {datetime.now(timezone.utc).isoformat()} | Constructor remains submission UNCONFIRMED and CAPTCHA=X; Applied stays blank. Never automatically retry this application. Its resolution is not a prerequisite for unrelated jobs. Evidence: {state['recovery_file']} | URL: {manager.page.url}")
            for attempt in range(2):
                try:
                    verified = tracker.call('outcome', result=result)
                    assert verified.get('verified')
                    break
                except Exception:
                    if attempt:
                        raise
            after = tracker.call('application_check', id=2972)['row']
            assert str(after[cap]).strip().upper()=='X' and not str(after['Applied']).strip()
            assert all(after.get(k,'')==before.get(k,'') for k in ('Applied Date','Previous Applied Date'))
            state.update(status='Submission unconfirmed - never automatically retry', submission_uncertain=True,
                         never_automatically_retry=True, batch_blocker=False, constructor_prerequisite=False,
                         captcha=True, outcome_tracker=verified, continuation_authorized_at=datetime.now(timezone.utc).isoformat())
            state.pop('publication_error', None)
            cp.write(packet, state)
            manager.after_outcome(packet, state, uncertain=True)
            cp.write(packet, state)
            proof = manager.verify('Constructor verified; same tab released for remaining 87')
            assert proof['target']==original_target and manager.page.url=='about:blank'
            save(base/'constructor-continuation-override.json', dict(tracker=verified, browser=proof,
                never_automatically_retry=True, submission_unconfirmed=True, applied=False,
                preserved_attempt=str(base/'2972/submission-attempt.json'), backup=str(backup)))
        selected = tracker.call('selected', ids=ids)
        assert len(selected)==87 and set(p['id'] for p in selected)==set(ids)
        save(base/'resume-scope.json', dict(ids=ids, count=87, selected=selected, excludes_2995=True,
            includes_3046=True, excludes_constructor=True, authorized_at=datetime.now(timezone.utc).isoformat(), prior_run_backup=str(backup)))
        save(base/'batch-start.json', dict(started_at=datetime.now(timezone.utc).isoformat(), segment='remaining-87'))
        save(base/'current-progress.json', dict(step='Constructor verified; remaining 87 authorized', remaining=87,
             constructor_prerequisite=False, dedicated_window_tab_count=1))
        print(json.dumps(dict(constructor_verified=True, captcha='X', applied='', never_automatically_retry=True,
             same_tab=True, tab_count=1, remaining_count=87, ids=[p['id'] for p in selected])))
    finally:
        tracker.close()
