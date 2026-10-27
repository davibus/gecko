"""Record observed post-submit CAPTCHA for 2972; no fill, clicks or navigation."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from playwright.sync_api import sync_playwright
from application_browser import SingleApplicationTab, save_recovery
from application_forms import captcha_visible
from application_runtime import Checkpoints, TrackerClient, save, batch_lock

base = ROOT/'reports/playwright-pilot/sequential-2954-3060-except-2995-20261026'
ident = 2972
assert ident in set(range(2954,3061))-{2995}
with batch_lock(ROOT/'reports/playwright-pilot/sequential.lock'), batch_lock(base/'batch.lock'):
    cp = Checkpoints(base)
    packet = json.loads((base/str(ident)/'packet.json').read_text(encoding='utf-8'))
    state = cp.read(packet)
    assert state.get('submission_uncertain') and (base/str(ident)/'submission-attempt.json').exists()
    assert not (base/str(ident)/'receipt.json').exists()
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp('http://127.0.0.1:9333')
        manager = SingleApplicationTab(browser.contexts[0], base, lambda *args: False)
        manager.page = next(p['page'] for p in manager.inventory() if p['target'] == manager.data['current_target'])
        assert manager.data['current_job'] == ident
        manager.verify('before uncertainty CAPTCHA publication')
        recovery = save_recovery(manager.page, packet, state, base, 'Observed post-submit CAPTCHA; batch remains paused')
        evidence = None
        if not captcha_visible(manager.page, recovery['snapshot']):
            for saved in (base/str(ident)/'recovery-history').glob('*.json'):
                prior = json.loads(saved.read_text(encoding='utf-8'))
                if prior.get('url') != manager.page.url:
                    continue
                if any('recaptcha' in fr.get('url','') and '/bframe' in fr.get('url','')
                       and fr.get('text','').strip() == 'VERIFY' for fr in prior.get('snapshot',{}).get('frames',[])):
                    evidence = str(saved)
                    break
            assert evidence, 'Do not infer CAPTCHA without captured challenge evidence'
        state['captcha_evidence'] = evidence or state['recovery_file']
        state.update(captcha=True, status='PAUSED - submission unconfirmed (CAPTCHA)',
            blocker='Post-submit reCAPTCHA verification frame captured with VERIFY; no employer confirmation. Employer also reports missing Full Name, Email and Location. Do not resubmit.')
        state['submission_validation_errors'] = ['Missing entry for required field: Full Name', 'Missing entry for required field: Email', 'Missing entry for required field: Location']
        started = datetime.fromisoformat(state['started_at'])
        elapsed = state.get('prior_elapsed_seconds',0)+(datetime.now(timezone.utc)-started).total_seconds()
        result = dict(id=ident, company=packet['company'], title=packet['title'], job_url=packet['row']['Job URL'], captcha=True,
            note=f"Sequential application {base.name} | Submission unconfirmed | {state['blocker']} | URL: {manager.page.url} | Recovery: {state['recovery_file']} | CAPTCHA evidence: {state['captcha_evidence']} | Elapsed before final readback {int(elapsed)//60:02d}:{int(elapsed)%60:02d} | Sole tab retained; no retry or next job.")
        save(base/str(ident)/'outcome-pending.json', result)
        tracker = TrackerClient()
        try:
            for attempt in range(2):
                try:
                    verified = tracker.call('outcome', result=result)
                    assert verified.get('verified')
                    break
                except Exception:
                    if attempt:
                        raise
        finally:
            tracker.close()
        state['outcome_tracker'] = verified
        state['elapsed_seconds'] = state.get('prior_elapsed_seconds',0)+(datetime.now(timezone.utc)-started).total_seconds()
        cp.write(packet, state)
        summary = json.loads((base/'batch-summary.json').read_text(encoding='utf-8'))
        summary['jobs'] = [dict(state) if p['id']==ident else p for p in summary['jobs']]
        batch_start = datetime.fromisoformat(json.loads((base/'batch-start.json').read_text())['started_at'])
        summary.update(elapsed_seconds=(datetime.now(timezone.utc)-batch_start).total_seconds(),
                       paused=True, complete=False, blocker=state['blocker'])
        save(base/'batch-summary.json', summary)
        save(base/'current-progress.json', dict(paused=True, id=ident, company=packet['company'], title=packet['title'],
            position=state['position'], total=106, step=state['status'], elapsed_seconds=state['elapsed_seconds'],
            counts=summary['counts'], remaining=summary['remaining'], batch_elapsed_seconds=summary['elapsed_seconds']))
        proof = manager.verify('paused on uncertain submission; CAPTCHA update verified')
        save(base/'final-browser-readback.json', proof)
        print(json.dumps(dict(sheet=verified, browser=proof, elapsed_seconds=state['elapsed_seconds'], counts=summary['counts'], remaining=summary['remaining'])))
