"""Checkpointed direct Playwright batches. Default: prepare only, without a browser.

Use --apply only for job IDs the user has requested applications for. OpenClaw
is never called. One owned window/tab is reused; recovery information is saved.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from playwright.sync_api import sync_playwright
import playwright_batch as batch
from application_forms import (answer_for, missing_questions, platform, wait_page,
                               captcha_visible, captcha_evidence, FormNavigation, profile_uploader)
from application_runtime import (ROOT, BatchSources, Checkpoints, Timings, TrackerClient,
                                 meaning, prior_attempt, save, batch_lock)
from application_browser import (SingleApplicationTab, save_recovery, recovery_archiver,
                                 SubmissionUncertain, BrowserLifecycleError)
from application_history import previous_blocker, workflow_fingerprint

RECEIPT = (r"we(?:'ve| have) received\s+your application\b|application (?:has been |was )?"
           r"(?:successfully )?submitted\b|thank you for applying\b|application received\b|"
           r"you have successfully applied\b")
NEXT = {'next', 'next step', 'save & continue', 'continue application'}
SEND = {'submit', 'submit application', 'send application', 'finish application'}


def form_signature(snap):
    return [(fr['frame'], [(f['tag'], f['type'], f['name'], f.get('question'), f['required'], f['visible'])
                          for f in fr.get('fields', [])]) for fr in snap['frames']]


def exact_pages(context, ident):
    found = []
    for page in context.pages:
        try:
            if page.evaluate('window.name') == f'gecko-{ident}':
                found.append(page)
        except Exception:
            continue
    if len(found) > 1:
        raise RuntimeError('Multiple draft tabs for this job; preserve them for review')
    return found


def identity_visible(snap, packet):
    text = meaning(snap.get('title', '') + ' ' + ' '.join(f.get('text', '') for f in snap['frames']))
    return meaning(packet['title']) in text and meaning(packet['company']) in text


def unverified_required(snap, packet, sources, state):
    missing = []
    for fr in snap['frames']:
        for f in fr.get('fields', []):
            if not f['visible'] or not f['required'] or f.get('disabled') or f['type'] in ('hidden', 'file'):
                continue
            if f['type'] == 'radio' and not f['checked']:
                continue
            if f['type'] == 'checkbox' and not f['checked']:
                continue  # Missing choice/groups are reported separately.
            record = answer_for(f, packet, sources, fr['url'])
            actual = f['value']
            if f['tag'] == 'SELECT':
                actual = next((o['text'] for o in f['options'] if o['value'] == f['value']), '')
            elif f['type'] == 'radio':
                actual = f['label'] or f['value']
            elif f['type'] == 'checkbox':
                allowed = record and (meaning(record['answer']) in ('yes','agree','i agree','accept') or
                                      meaning(f['label']) in [meaning(x) for x in record.get('choices',[])])
                actual = record['answer'] if allowed and f['checked'] else ''
            if not str(actual).strip() and f['type'] != 'checkbox':
                continue  # Already reported as missing; not a populated/unverified answer.
            if f.get('role') == 'combobox':
                committed = f.get('choice_committed') or any(
                    x.get('choice_committed') and x['frame']==fr['frame'] and
                    x['index']==f['index'] and meaning(x['question'])==meaning(f.get('question') or f['label'])
                    and meaning(x['answer'])==meaning(actual) for x in state.get('filled', []))
                if not committed or f.get('expanded') == 'true':
                    missing.append({'frame':fr['frame'], 'question':f.get('question') or f['label'],
                                    'reason':'Custom dropdown value has not been selected and verified'})
                    continue
            if not record or meaning(record['answer']) != meaning(actual):
                missing.append({'frame': fr['frame'], 'question': f.get('question') or f['label'] or f['name'],
                                'reason': 'Populated answer or agreement requires confirmed source'})
    return missing


def mutation_signature(frame):
    return frame.evaluate("() => document.body.innerText + [...document.querySelectorAll('input,select,textarea')].map(e=>[e.tagName,e.type,e.id,e.name,e.required,!!e.getClientRects().length].join('|')).join(';')")


def wait_transition(frame, before, timings, timeout=12000):
    with timings.phase('waiting'):
        frame.wait_for_function("before => document.body.innerText + [...document.querySelectorAll('input,select,textarea')].map(e=>[e.tagName,e.type,e.id,e.name,e.required,!!e.getClientRects().length].join('|')).join(';') !== before",
                                arg=before, timeout=timeout)


def process_packet(context, packet, state, checkpoints, *, allow_submit, lifecycle=None):
    """A blocked job always returns control to the batch; no human wait loop."""
    out = checkpoints.base / str(packet['id'])
    receipt_path = out / 'receipt.json'
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if (str(receipt['id']), receipt['company'], receipt['title']) != (str(packet['id']), packet['company'], packet['title']):
            raise RuntimeError('Saved receipt does not belong to this requested job')
        if not state.get('tracker', {}).get('verified'):
            with batch.timing().phase('tracker'):
                verified = batch.SESSION.tracker.call('receipt', receipt=receipt)
            if not verified.get('verified'):
                raise RuntimeError('Receipt preserved; tracker readback incomplete')
            checkpoints.write(packet, state, status='Applied - employer confirmed', receipt=receipt, tracker=verified, blocker=None)
        return
    if state.get('never_automatically_retry') or prior_attempt(packet, out):
        checkpoints.write(packet, state, status='Submission unconfirmed', submission_uncertain=True,
                          blocker='Prior submission attempt has no saved receipt; reconcile employer state, never resend')
        return
    if state.get('tracker', {}).get('verified') or state.get('status', '').startswith('Applied'):
        return
    with batch.timing().phase('preparation'):
        batch.SESSION.sources.refresh()
        state['prepared_answers'] = batch.SESSION.sources.for_job(packet)
        fresh = batch.fresh_row(packet['id'])
        if any(fresh.get(k) != packet['row'].get(k) for k in ('Company', 'Job Title', 'Job URL', 'Resume Link')):
            raise RuntimeError('Prepared job changed in primary tracker')
        if hashlib.sha256(Path(packet['resume']).read_bytes()).hexdigest() != packet['resume_sha256']:
            raise RuntimeError('Prepared resume changed; prepare the exact job again')
    if lifecycle:
        page = lifecycle.begin(packet, state)
        found = [page]
    else:
        found = exact_pages(context, packet['id'])
    if not found and state.get('draft_opened'):
        # Chromium can clear window.name across origins. Recover only a unique
        # recorded URL whose visible employer AND title still match this job.
        candidates=[]
        for candidate in context.pages:
            if candidate.url in {state.get('url'),packet['url']} and identity_visible(batch.snapshot(candidate),packet):
                candidates.append(candidate)
        if len(candidates)>1:
            raise RuntimeError('Multiple matching saved drafts; preserve them for review')
        found=candidates
    if not found and state.get('draft_opened'):
        checkpoints.write(packet, state, status='Needs attention', blocker='Saved draft tab missing; do not create a second draft')
        return
    if found:
        page = found[0]
    else:
        page = context.new_page()
        page.set_default_timeout(8000)
        page.evaluate('(name)=>window.name=name', f'gecko-{packet["id"]}')
        checkpoints.write(packet, state, draft_opened=True, url=packet['url'], status='Opening draft')
        with batch.timing().phase('waiting'):
            page.goto(packet['url'], wait_until='domcontentloaded', timeout=35000)
    for step in range(12):
        if lifecycle:
            page = lifecycle.page
            lifecycle.verify('during application')
        wait_page(page, batch.timing())
        # A visible empty body is not a hydrated application (notably Ashby).
        with batch.timing().phase('waiting'):
            page.wait_for_function("() => document.body.innerText.trim().length > 20 && document.querySelector('a,button,input,select,textarea')", timeout=12000)
        if not lifecycle:
            page.evaluate('(name)=>window.name=name',f'gecko-{packet["id"]}')
        try:
            snap = batch.snapshot(page)
            challenge_evidence = captcha_evidence(page)
        except FormNavigation:
            checkpoints.write(packet, state, status='Navigation changed; inspecting destination')
            continue
        save(out/'latest.json', snap)
        challenge = ' '.join(fr.get('text', '') for fr in snap['frames'])
        if re.search(r'this (?:position|job) is no longer available|this job has (?:closed|expired)', challenge, re.I):
            checkpoints.write(packet, state, status='Blocked - position unavailable', url=page.url,
                              blocker='Employer page states this position is no longer available')
            return
        state['captcha_detection'] = challenge_evidence
        if challenge_evidence['blocking']:
            save(out/'latest.json', snap)
            checkpoints.write(packet, state, status='CAPTCHA', captcha=True, url=page.url,
                              blocker='CAPTCHA/human verification displayed; no attempt to solve or retry')
            return
        if not identity_visible(snap, packet):
            save(out/'latest.json', snap)
            checkpoints.write(packet, state, status='Needs attention', url=page.url,
                              blocker='Employer and exact job title not visible together; unfamiliar form needs review')
            return
        # The same existing tab must retain job identity on later steps.
        if state.get('identity_verified') and page.url != state.get('url'):
            from urllib.parse import urlsplit
            if urlsplit(page.url).hostname != state.get('identity_host'):
                raise RuntimeError('Application moved to another host; verify exact draft before continuing')
        text = ' '.join(fr.get('text', '') for fr in snap['frames'])
        from urllib.parse import urlsplit
        if re.search(r'/(?:profile|settings)(?:/|$)', urlsplit(page.url).path, re.I) or re.search(r'save (?:changes )?to (?:my|your) profile|make (?:this )?(?:my |your )?default resume', text, re.I):
            checkpoints.write(packet, state, status='Needs attention', url=page.url,
                              blocker='Account-wide profile change is outside application scope')
            return
        if re.search(r'verify you are human|verify your identity|sign in to (?:apply|continue)|create (?:an |your )account|enter (?:the )?(?:verification|security) code', text, re.I):
            checkpoints.write(packet, state, status='Needs attention', url=page.url,
                              blocker='Login, account creation or human verification required')
            save(out/'latest.json', snap)
            return
        inputs = [f for fr in snap['frames'] for f in fr.get('fields', [])
                  if f['visible'] and f['tag'] in ('INPUT', 'TEXTAREA', 'SELECT') and f['type'] not in ('hidden', 'submit', 'button', 'checkbox', 'radio','search')]
        if any(profile_uploader(f) for fr in snap['frames'] for f in fr.get('fields', []) if f['type']=='file') and not any(
                f['type']=='file' and not profile_uploader(f) for fr in snap['frames'] for f in fr.get('fields', [])):
            checkpoints.write(packet, state, status='Needs attention',
                              blocker='Listing exposes an account-wide resume uploader, not the employer application; direct employer application URL required',
                              url=page.url)
            return
        apply_controls = [(fr, f) for fr in snap['frames'] for f in fr.get('fields', [])
                          if f['visible'] and f['tag'] in ('A', 'BUTTON') and f['type'] != 'submit'
                          and f['text'].strip().lower() in ('apply', 'apply now', 'apply for this job', 'apply to position', 'application')]
        # Workable repeats the same application URL in its header and footer.
        # Both controls identify one destination, not two different applications.
        apply_controls = list({('href', f['href']) if f['tag'] == 'A' and f['href'] else
                               ('control', fr['frame'], f['index']): (fr, f)
                               for fr, f in apply_controls}.values())
        if not inputs and len(apply_controls) == 1:
            fr, f = apply_controls[0]
            checkpoints.write(packet, state, status='Opening application form', url=page.url)
            if f['tag'] == 'A' and f['href']:
                with batch.timing().phase('waiting'):
                    page.goto(f['href'], wait_until='domcontentloaded', timeout=35000)
            else:
                frame = page.frames[fr['frame']]
                before = mutation_signature(frame)
                page = click_step(page, frame, f'[data-gecko-index="{f["index"]}"]', before, lifecycle)
            # The application route can show the old navigation while its form
            # hydrates. Wait for an editable control before considering another
            # Apply click, rather than repeatedly navigating to the same route.
            with batch.timing().phase('waiting'):
                page.wait_for_function("() => [...document.querySelectorAll('input,textarea,select')].some(e => !['hidden','submit','button'].includes(e.type) && !!e.getClientRects().length)", timeout=12000)
            continue
        from urllib.parse import urlsplit
        checkpoints.write(packet, state, identity_verified=True, identity_host=urlsplit(page.url).hostname,
                          url=page.url, status='Filling draft', source_hashes=batch.SESSION.sources.hashes)
        before_signature = form_signature(snap)
        try:
            batch.fill_supported(page, packet, state, snap=snap)
            # Inspect the actual new DOM. A rerender can replace fields without
            # changing their count; old indices/labels are not valid evidence.
            snap = batch.snapshot(page)
        except FormNavigation:
            checkpoints.write(packet, state, status='Navigation changed; inspecting destination')
            continue
        signature_changed = before_signature != form_signature(snap)
        if signature_changed:
            checkpoints.write(packet, state, status='Conditional step revealed')
            continue
        missing = missing_questions(snap)
        unknown = unverified_required(snap, packet, batch.SESSION.sources, state)
        save(out/'latest.json', snap)
        checkpoints.write(packet, state, missing_required=missing, unverified_required=unknown,
                          platform=platform(page.url), step=step)
        if missing or unknown:
            checkpoints.write(packet, state, status='Needs attention', blocker='Required answers need confirmation')
            return
        controls = [(fr, f) for fr in snap['frames'] for f in fr.get('fields', [])
                    if f['visible'] and f['tag'] in ('BUTTON', 'INPUT')]
        next_controls = [(fr, f) for fr, f in controls if not f.get('disabled') and (f['text'] or f['value']).strip().lower() in NEXT]
        if len(next_controls) == 1:
            fr, f = next_controls[0]
            frame = page.frames[fr['frame']]
            before = mutation_signature(frame)
            checkpoints.write(packet, state, status='Advancing step')
            page = click_step(page, frame, f'[data-gecko-index="{f["index"]}"]', before, lifecycle)
            continue
        send = [(fr, f) for fr, f in controls if (f['text'] or f['value']).strip().lower() in SEND]
        if len(send)==1 and send[0][1].get('disabled'):
            fr,f=send[0]
            checkpoints.write(packet,state,status='Waiting for employer form/upload processing')
            try:
                with batch.timing().phase('waiting'):
                    page.frames[fr['frame']].wait_for_function(
                        'selector=>{const e=document.querySelector(selector);return e&&!e.disabled&&e.getAttribute("aria-disabled")!=="true"}',
                        arg=f'[data-gecko-index="{f["index"]}"]',timeout=30000)
            except Exception as exc:
                if page.url!=snap['url']:
                    continue
                checkpoints.write(packet,state,status='Needs attention',
                    blocker='Employer Submit control remained disabled after 30 seconds; upload or form processing incomplete')
                return
            continue  # Processing can replace/import fields; verify the new DOM.
        if not allow_submit:
            checkpoints.write(packet, state, status='Draft prepared - submission disabled')
            return
        if len(send) != 1 or not state.get('resume', {}).get('upload_verified'):
            checkpoints.write(packet, state, status='Needs attention', blocker='Final control or exact resume upload unverified')
            return
        fr, f = send[0]
        command = {'frame': fr['frame'], 'selector': f'[data-gecko-index="{f["index"]}"]',
                   'expected_url': page.url, 'confirmation_pattern': RECEIPT,
                   'attachment_verified': True, 'all_required_answers_verified': True}
        checkpoints.write(packet, state, status='Ready to submit', submission_command=command)
        with batch.timing().phase('confirmation'):
            batch.submit(page, packet, state, command, out)
        checkpoints.write(packet, state)
        return
    checkpoints.write(packet, state, status='Needs attention', blocker='Step limit reached; draft preserved')


def click_step(page, frame, selector, before, lifecycle):
    start_url, frame_url = page.url, frame.url
    try:
        frame.locator(selector).click()
    except Exception:
        if not lifecycle or lifecycle.page == page or not page.is_closed():
            raise
    if lifecycle and lifecycle.page != page:
        wait_page(lifecycle.page, batch.timing())
        return lifecycle.page
    try:
        wait_transition(frame, before, batch.timing())
    except Exception:
        if not page.is_closed() and (page.url != start_url or frame.is_detached() or frame.url != frame_url):
            wait_page(page, batch.timing())
            return page  # Inspect the destination; never click Next a second time.
        if not lifecycle or lifecycle.page == page or not page.is_closed():
            raise
        wait_page(lifecycle.page, batch.timing())
        return lifecycle.page
    return page


@contextmanager
def batch_session(tracker, sources, timings, lifecycle=None):
    previous = batch.SESSION
    batch.SESSION = SimpleNamespace(tracker=tracker, sources=sources, timings=timings, browser_lifecycle=lifecycle)
    try:
        yield
    finally:
        batch.SESSION = previous


def run_packets(context, packets, tracker, sources, base, *, allow_submit=False):
    """Legacy isolated fixture harness; all CLI browser modes use run_sequential."""
    checkpoints = Checkpoints(base)
    reports = []
    for packet in packets:
        timer = Timings()
        state = checkpoints.read(packet)
        try:
            with batch_session(tracker, sources, timer):
                process_packet(context, packet, state, checkpoints, allow_submit=allow_submit)
        except Exception as exc:
            checkpoints.write(packet, state, status='Needs attention', blocker=str(exc))
        finally:
            state['timings'] = timer.report()
            checkpoints.write(packet, state)
            reports.append(state)
            save(Path(base)/'progress.json', reports)
            print(json.dumps({'id': packet['id'], 'status': state['status'], 'blocker': state.get('blocker'),
                              'timings': state['timings']}), flush=True)
    return reports


def receipt_from_recovery(recovery, packet, out):
    """Recover a receipt observed after a click; never retry the click itself."""
    from urllib.parse import urlsplit
    attempt_path=Path(out)/'submission-attempt.json'
    if not attempt_path.exists():
        return None
    attempt=json.loads(attempt_path.read_text(encoding='utf-8'))
    identity=lambda x:(str(x.get('id')),x.get('company'),x.get('title'))
    if identity(recovery)!=identity(packet) or identity(attempt)!=identity(packet):
        return None
    start=urlsplit(attempt['url']);end=urlsplit(recovery['url'])
    if (start.scheme,start.netloc)!=(end.scheme,end.netloc):
        return None
    if end.path!=start.path and not end.path.startswith(start.path.rstrip('/')+'/'):
        return None
    if datetime.fromisoformat(recovery['captured_at'])<datetime.fromisoformat(attempt['attempted_at']):
        return None
    frames=recovery.get('snapshot',{}).get('frames',[])
    if not frames or frames[0].get('error'):
        return None
    if any(f.get('visible') and f.get('tag') in ('INPUT','TEXTAREA','SELECT') for fr in frames for f in fr.get('fields',[])):
        return None
    match=re.search(r'(?im)^(?:Application (?:successfully )?Submitted[.!]?|Your application has been submitted successfully\.?(?: Good luck!)?|Thank you for applying[.!]?)$',frames[0].get('text',''))
    if not match:
        return None
    return dict(attempt,submitted_at=recovery['captured_at'],confirmation_verified=True,
                confirmation_text=match.group(0),confirmation_url=recovery['url'],
                confirmation_evidence=str(Path(out)/'recovery.json'),reconciled_from_saved_confirmation=True)


def elapsed_text(seconds):
    seconds = int(seconds)
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def run_sequential(context, selected, tracker, sources, base, *, allow_submit, lifecycle=None):
    checkpoints = Checkpoints(base)
    owns_lifecycle = lifecycle is None
    if lifecycle is None:
        ref = []
        lifecycle = SingleApplicationTab(context, base, recovery_archiver(base, tracker, ref))
        ref.append(lifecycle)
        lifecycle.reconcile()
    reports = []
    batch_start = time.perf_counter()
    first_start_file = Path(base)/'batch-start.json'
    if not first_start_file.exists():
        save(first_start_file, {'started_at': datetime.now(timezone.utc).isoformat()})
    first_start = datetime.fromisoformat(json.loads(first_start_file.read_text())['started_at'])
    def batch_elapsed():
        return (datetime.now(timezone.utc)-first_start).total_seconds()
    counts = dict(submitted=0, captcha=0, blocked=0, skipped=0, unconfirmed=0)
    for position, item in enumerate(selected, 1):
        lifecycle.verify('before selected job '+str(item['id']))
        timer = Timings()
        packet = dict(item, url=item['row']['Job URL'])
        state = checkpoints.read(packet)
        if state.get('outcome_tracker', {}).get('verified'):
            reports.append(dict(state))
            counts[state['category']] += 1
            continue
        prior_elapsed = state.get('prior_elapsed_seconds', 0)
        state.update(position=position, total=len(selected), started_at=datetime.now(timezone.utc).isoformat(),
                     workflow_fingerprint=workflow_fingerprint())
        stop = threading.Event()
        def display():
            while not stop.is_set():
                current = dict(id=item['id'], company=item['company'], title=item['title'],
                    position=position, total=len(selected), step=state.get('status'),
                    elapsed_seconds=prior_elapsed+time.perf_counter()-timer.started,
                    batch_elapsed_seconds=batch_elapsed(), counts=dict(counts),
                    remaining=len(selected)-sum(counts.values()))
                save(Path(base)/'current-progress.json', current)
                print(f"Job {position} of {len(selected)} | ID {item['id']} | {item['company']} | {item['title']} | {state.get('status')} | Elapsed {elapsed_text(current['elapsed_seconds'])}", flush=True)
                stop.wait(1)
        thread = threading.Thread(target=display, daemon=True)
        thread.start()
        try:
            fresh = tracker.call('application_check', id=item['id'])
            if fresh['skip']:
                state.update(status='skipped', blocker=fresh['skip'], url=packet['url'])
            else:
                sources.refresh()
                prior = previous_blocker(dict(item, row=fresh['row']), sources, base)
                try:
                    if prior:
                        state.update(prior)
                    else:
                        packet = tracker.call('prepare', id=item['id'])
                        save(Path(base)/str(item['id'])/'packet.json', packet)
                        with batch_session(tracker, sources, timer, lifecycle):
                            process_packet(context, packet, state, checkpoints, allow_submit=allow_submit, lifecycle=lifecycle)
                except BrowserLifecycleError:
                    raise
                except Exception as exc:
                    state.update(status='Needs attention', blocker=str(exc))
            saved_receipt = Path(base)/str(item['id'])/'receipt.json'
            if saved_receipt.exists() and not state.get('tracker', {}).get('verified'):
                receipt = json.loads(saved_receipt.read_text(encoding='utf-8'))
                verified = tracker.call('receipt', receipt=receipt)
                if not verified.get('verified'):
                    raise RuntimeError('Employer receipt saved; Applied/date readback incomplete')
                state.update(status='Applied - employer confirmed', receipt=receipt, tracker=verified, blocker=None)
            if prior_attempt(packet, Path(base)/str(item['id'])) and not state.get('receipt') and not fresh.get('row', {}).get('Applied'):
                state.update(status='Submission unconfirmed', submission_uncertain=True, submission_error=state.get('blocker'),
                             never_automatically_retry=True, batch_blocker=False,
                             blocker=('Employer form requires correction: '+'; '.join(state['submission_validation'])+
                                      '; no confirmed submission; do not automatically resubmit') if state.get('submission_validation') else
                                     'Submission attempted without employer confirmation; do not automatically resubmit')
            if lifecycle.data.get('current_job') == packet['id']:
                recovery = save_recovery(lifecycle.page, packet, state, base, 'job outcome before tab reuse')
                if state.get('submission_uncertain') and not state.get('receipt'):
                    recovered=receipt_from_recovery(recovery,packet,Path(base)/str(packet['id']))
                    if recovered:
                        save(Path(base)/str(packet['id'])/'receipt.json',recovered)
                        verified=tracker.call('receipt',receipt=recovered)
                        if not verified.get('verified'):
                            raise RuntimeError('Recovered receipt saved; Applied/date readback incomplete')
                        state.update(status='Applied - employer confirmed',receipt=recovered,tracker=verified,
                                     submission_uncertain=False,blocker=None)
                state['captcha_detection'] = captcha_evidence(lifecycle.page)
                if not state.get('receipt') and state['captcha_detection']['blocking']:
                    state['captcha'] = True
                    state['blocker'] = ('CAPTCHA appeared after submission attempt; no employer confirmation; do not resubmit'
                                        if state.get('submission_uncertain') else 'CAPTCHA/human verification displayed; no attempt to solve or retry')
                    if not state.get('submission_uncertain'):
                        state['status'] = 'CAPTCHA'
                checkpoints.write(packet, state)
            labels = [x.get('question', '') if isinstance(x, dict) else str(x)
                      for x in state.get('missing_required', []) + state.get('unverified_required', [])]
            note = (f"Sequential application {Path(base).name} | {state['status']} | "
                    f"{state.get('blocker') or 'Employer submission confirmed'}"
                    + (f" | Required: {', '.join(dict.fromkeys(labels))}" if labels else '')
                    + (f" | Recovery: {state['recovery_file']} | Unsaved entries/uploads are not guaranteed to persist." if state.get('recovery_file') else '')
                    + f" | URL: {state.get('url') or packet['url']} | Elapsed before final readback {elapsed_text(prior_elapsed+time.perf_counter()-timer.started)}")
            result = dict(id=item['id'], company=item['company'], title=item['title'],
                          job_url=item['row']['Job URL'], note=note, captcha=state.get('captcha', False))
            # The exact same idempotent append is retried once; never advance
            # to another employer while an outcome remains unverified.
            save(Path(base)/str(item['id'])/'outcome-pending.json', result)
            for attempt in range(2):
                try:
                    verified = tracker.call('outcome', result=result)
                    if not verified.get('verified'):
                        raise RuntimeError('Outcome not verified')
                    break
                except Exception:
                    if attempt:
                        raise
            state['outcome_tracker'] = verified
            state['elapsed_seconds'] = prior_elapsed+time.perf_counter()-timer.started
            category = ('unconfirmed' if state.get('submission_uncertain') else 'skipped' if state['status'] == 'skipped' else 'captcha' if state.get('captcha') else
                        'submitted' if state.get('tracker', {}).get('verified') and state.get('receipt') else 'blocked')
            counts[category] += 1
            state['category'] = category
            checkpoints.write(packet, state)
            reports.append(dict(state))
            save(Path(base)/'progress.json', reports)
            save(Path(base)/'batch-summary.json', dict(counts=counts, elapsed_seconds=batch_elapsed(), jobs=reports,
                 remaining=len(selected)-sum(counts.values())))
            lifecycle.after_outcome(packet, state, uncertain=state.get('submission_uncertain', False))
            checkpoints.write(packet, state)
            print(json.dumps(dict(id=item['id'], outcome=state['status'], elapsed=elapsed_text(state['elapsed_seconds']), verified=True, counts=counts)), flush=True)
        except Exception as exc:
            checkpoints.write(packet, state, status='PAUSED - submission unconfirmed' if state.get('submission_uncertain') else 'PAUSED - outcome or browser verification incomplete', publication_error=str(exc))
            save(Path(base)/'batch-summary.json', dict(counts=counts, elapsed_seconds=batch_elapsed(), jobs=reports,
                 remaining=len(selected)-sum(counts.values()), paused=True, blocker=str(exc), current_id=packet['id']))
            save(Path(base)/'current-progress.json', dict(paused=True, id=packet['id'], company=packet['company'],
                 title=packet['title'], step=state['status'], counts=counts,
                 remaining=len(selected)-sum(counts.values()), batch_elapsed_seconds=batch_elapsed()))
            if owns_lifecycle:
                lifecycle.detach()
            raise
        finally:
            stop.set()
            thread.join(timeout=3)
    save(Path(base)/'batch-summary.json', dict(counts=counts, elapsed_seconds=batch_elapsed(), jobs=reports, complete=True, remaining=0))
    save(Path(base)/'current-progress.json', dict(complete=True, step='Batch complete',
         batch_elapsed_seconds=batch_elapsed(), counts=counts, remaining=0,
         last_job_id=reports[-1]['id'] if reports else None,
         last_job_elapsed_seconds=reports[-1]['elapsed_seconds'] if reports else 0))
    lifecycle.verify('batch complete')
    if owns_lifecycle:
        lifecycle.detach()
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ids', nargs='+', required=True, type=int)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--apply', action='store_true', help='Execute only the explicitly requested applications')
    mode.add_argument('--draft-only', action='store_true', help='Fill authorized drafts; disable submission')
    parser.add_argument('--cdp', default='http://127.0.0.1:9333')
    parser.add_argument('--sequential', action='store_true', help='Live ready-marker gate, Sheet order and verified outcomes after every job')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Run without Python -O: legacy browser guards require assertions')
    if not args.cdp.startswith('http://127.0.0.1:'):
        parser.error('Use the dedicated loopback Chrome endpoint')
    if not args.ids or min(args.ids) <= 0 or len(set(args.ids)) != len(args.ids):
        parser.error('IDs must be unique positive stable tracker IDs')
    base = args.evidence_dir.resolve()
    if base.parent != (ROOT/'reports/playwright-pilot').resolve():
        parser.error('Evidence must be a batch directory under reports/playwright-pilot')
    base.mkdir(parents=True, exist_ok=True)
    lock = batch_lock(base/'batch.lock')
    lock.__enter__()
    tracker = None
    try:
        timer = Timings()
        with timer.phase('preparation'):
            sources = BatchSources().refresh()
            tracker = TrackerClient()
            if args.sequential or args.apply or args.draft_only:
                selected = tracker.call('selected', ids=args.ids)
                save(base/'selected.json', selected)
                if not (args.apply or args.draft_only):
                    print(json.dumps({'status': 'Selected only', 'ids': [p['id'] for p in selected]}))
                    return
                with sync_playwright() as pw:
                    browser = pw.chromium.connect_over_cdp(args.cdp)
                    if len(browser.contexts) != 1:
                        raise RuntimeError('Dedicated browser context is ambiguous')
                    with batch_lock(ROOT/'reports/playwright-pilot/sequential.lock'):
                        run_sequential(browser.contexts[0], selected, tracker, sources, base, allow_submit=args.apply)
                return
            packets = []
            skipped = []
            for ident in args.ids:
                receipt_path = base/str(ident)/'receipt.json'
                if receipt_path.exists() and (args.apply or args.draft_only):
                    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
                    if str(receipt['id']) != str(ident):
                        raise RuntimeError('Saved receipt ID differs from the requested job')
                    verified = tracker.call('receipt', receipt=receipt)
                    save(base/str(ident)/'tracker-reconciled.json', verified)
                    skipped.append({'id': ident, 'status': 'Applied - receipt reconciled', 'tracker': verified})
                    continue
                try:
                    p = tracker.call('prepare', id=ident)
                    p['prepared_answers'] = sources.for_job(p)
                    p['answer_source_hashes'] = dict(sources.hashes)
                    packets.append(p)
                except Exception as exc:
                    skipped.append({'id': ident, 'status': 'skipped', 'reason': str(exc)})
            save(base/'packets.json', packets)
        save(base/'preparation.json', {'timings': timer.report(), 'source_parses': sources.parse_counts, 'skipped': skipped})
        if not (args.apply or args.draft_only):
            print(json.dumps({'status': 'Prepared only; no browser opened or tracker writes',
                              'ids': [p['id'] for p in packets], 'skipped': skipped, 'timings': timer.report()}))
            return
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(args.cdp)
            if len(browser.contexts) != 1:
                raise RuntimeError('Dedicated application browser context is ambiguous')
            run_packets(browser.contexts[0], packets, tracker, sources, base, allow_submit=args.apply)
            # Selected-ID browser modes return above through the single-tab path.
    finally:
        try:
            if tracker is not None:
                tracker.close()
        finally:
            lock.__exit__(None, None, None)


if __name__ == '__main__':
    main()
