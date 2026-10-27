"""Direct, local Gecko browser worker. No model calls and no OpenClaw dependency."""
import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import time
from urllib.parse import urlparse,parse_qs
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright
from playwright_application import ROOT
from application_runtime import (save, BatchSources, Timings, claim_attempt, prior_attempt)
from application_forms import (answer_for, plan_fields, fill_together, upload_resume, wait_page,
                               frame_visible, resume_fields, FormNavigation, VALIDATION_JS, validation_messages)

SESSION = None
SOURCES = None


def sources_for_batch():
    global SOURCES
    if SESSION is not None:
        return SESSION.sources
    if SOURCES is None:
        SOURCES = BatchSources()
    return SOURCES.refresh()


def timing():
    return SESSION.timings if SESSION is not None else Timings()

DASH = ROOT / '.tools/dashboard-python/Scripts/python.exe'


def fresh_row(ident):
    if SESSION is not None:
        return SESSION.tracker.call('check', id=ident)
    result = subprocess.run([str(DASH), str(ROOT/'scripts/playwright_tracker.py'),
                             '--check', str(ident)], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Primary tracker preflight failed: ' + result.stderr[-1200:])
    return json.loads(result.stdout)


def snapshot(page, _retry=0):
    frames = []
    start_url = page.url
    initial_frames = list(page.frames)
    with timing().phase('inspection'):
        for fi, frame in enumerate(initial_frames):
            try:
                if not frame_visible(frame):
                    frames.append(dict(frame=fi,url=frame.url,visible=False,text='',fields=[],choices=[]))
                    continue
                observed=frame.locator('body').evaluate(r'''body=>{
                    const visible=e=>{if(!e.getClientRects().length)return false;for(let a=e;a;a=a.parentElement){const s=getComputedStyle(a);if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)===0||a.hidden||a.getAttribute('aria-hidden')==='true')return false;}return true;};
                    const fields=[...document.querySelectorAll('input,textarea,select,button,a,[role=combobox]')].map((e,i)=>{
                        e.setAttribute('data-gecko-index',String(i));
                        const p=e.closest('li.question,.application-question,.application-field,fieldset,.form-group,.field,.ashby-application-form-field-entry')||e.parentElement?.parentElement;
                        const breezy=e.closest('li.question');
                        const ariaLabel=(e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.innerText||'').join(' ').trim();
                        const rawLabel=[...(e.labels||[])].map(l=>l.innerText).join(' ')||e.getAttribute('aria-label')||ariaLabel||e.getAttribute('placeholder')||'';
                        let label=rawLabel.split('\n').map(x=>x.trim()).find(x=>x && !/^\*+$/.test(x))||rawLabel.trim();
                        if(!label && breezy && ['checkbox','radio'].includes(e.type)) label=e.closest('li.option')?.querySelector('span')?.innerText?.trim()||'';
                        const heading=(e.closest('[data-field-entry-id],.ashby-application-form-field-entry')||
                            (['radio','checkbox'].includes(e.type)?e.closest('fieldset'):null))?.querySelector('.ashby-application-form-question-title');
                        const legend=e.closest('fieldset')?.querySelector('legend')?.innerText||heading?.innerText;
                        const isChoice=e.type==='radio'||e.type==='checkbox';
                        const visibleLabels=isChoice?[...(e.labels||[])].filter(visible):[];
                        const groupRequired=['INPUT','TEXTAREA','SELECT'].includes(e.tagName) &&
                            (!!e.closest('[aria-required="true"],fieldset[required]') ||
                            !!heading && [...heading.classList].some(c=>/^_required_/.test(c)));
                        const context=p?.innerText?.slice(0,1600)||'';
                        let question=isChoice ? legend||label : label||legend;
                        if(e.type==='radio' && !legend) question=context.split('\n').map(x=>x.trim()).find(x=>x && x!==label)||label;
                        if(breezy) question=breezy.querySelector('h3')?.innerText?.trim()||question;
                        if(!question && e.name==='cSummary') question=e.parentElement.querySelector('.section-header h3')?.innerText?.trim()||'';
                        if(!question && e.tagName==='SELECT' && e.getAttribute('ng-model')==='candidate.salary.period') question='Salary payment frequency';
                        const m=(e.name||'').match(/^cards\[([^\]]+)\]\[field(\d+)\]$/);
                        if(m){const t=[...document.querySelectorAll('input')].find(t=>t.name==='cards['+m[1]+'][baseTemplate]');
                            if(t){try{question=JSON.parse(t.value).fields[Number(m[2])].text}catch{}}}
                        const combo=e.getAttribute('role')==='combobox';
                        const choiceParent=e.closest('.select__container,[class*="select-container"],.field,.form-group')||e.parentElement?.parentElement;
                        const choiceLabel=combo?choiceParent?.querySelector('[class*="singleValue"],[class*="single-value"]')?.textContent?.trim():'';
                        return {index:i,tag:e.tagName,type:e.type||'',id:e.id,name:e.name||'',label,question,context,
                            role:e.getAttribute('role')||'',choice_value:choiceLabel||'',choice_committed:!!choiceLabel,
                            expanded:e.getAttribute('aria-expanded'),
                            form_action:e.form?.getAttribute('action')||'',form_id:e.form?.id||'',
                            text:(e.innerText||'').slice(0,200),href:e.href||'',disabled:!!e.disabled,readonly:!!e.readOnly,
                            required:!!e.required||groupRequired||e.getAttribute('aria-required')==='true'||/\*\s*$/.test(question||label),valid:e.validity?e.validity.valid:true,
                            validationMessage:e.validationMessage||'',visible:visible(e)||visibleLabels.length>0,
                            label_click:!visible(e)&&visibleLabels.length>0,
                            value:e.type==='password'?'<redacted>':e.type==='hidden'?'<hidden>':e.tagName==='SELECT'&&!e.selectedOptions[0]?.text.trim()?'':choiceLabel||e.value||'',checked:!!e.checked,
                            files:e.files?[...e.files].map(f=>({name:f.name,size:f.size})):[],
                            options:e.options?[...e.options].map(o=>({text:o.text,value:o.value,selected:o.selected})):[]};
                    });
                    return {text:body.innerText.slice(0,20000),fields,
                        choices:[...document.querySelectorAll('[role=option]')].filter(e=>e.getClientRects().length).map(e=>e.innerText)};
                }''')
                frames.append(dict(frame=fi,url=frame.url,**observed))
            except Exception as exc:
                if page.url != start_url or frame.is_detached() or re.search(r'execution context was destroyed|navigation', str(exc), re.I):
                    if _retry < 2:
                        page.wait_for_load_state('domcontentloaded', timeout=12000)
                        return snapshot(page, _retry+1)
                    raise FormNavigation('Navigation interrupted form inspection; no action dispatched') from exc
                frames.append({'frame':fi,'url':frame.url,'error':str(exc)[:200]})
        if page.url != start_url or list(page.frames) != initial_frames:
            if _retry < 2:
                return snapshot(page, _retry+1)
            raise FormNavigation('Navigation changed inspected frames; no action dispatched')
        try:
            return {'url':page.url,'title':page.title(),'frames':frames}
        except Exception as exc:
            raise FormNavigation('Navigation interrupted form title inspection') from exc


def supported_answer(field, packet):
    record=answer_for(field,packet,sources_for_batch(),packet.get('url',''))
    return record['answer'] if record else None


def fill_supported(page, packet, state, snap=None):
    timer=timing()
    with timer.phase('preparation'):
        sources=sources_for_batch()
    snap=snap or snapshot(page)
    plans=plan_fields(snap,packet,sources)
    try:
        fill_together(page,plans,state,timer)
        files=resume_fields(snap)
        if files:
            upload_resume(page,packet,state,files,timer)
    except Exception as exc:
        if page.url != snap['url'] or re.search(r'execution context was destroyed|frame was detached', str(exc), re.I):
            raise FormNavigation('Navigation during form interaction; inspect destination before another action') from exc
        raise
    return snap


def missing_fields(snap):
    missing=[]
    for fr in snap['frames']:
        fields=fr.get('fields',[])
        for f in fields:
            if not f['visible'] or not f['required'] or f['type']=='hidden': continue
            if f['type']=='radio':
                if any(x['name']==f['name'] and x['checked'] for x in fields):continue
            elif f['type']=='checkbox':
                if f['checked']:continue
            elif f['value']:continue
            question=f['context'] or f['label'] or f['name']
            if question not in missing:missing.append(question)
    return missing


def submit(page, packet, state, command, out):
    if prior_attempt(packet, out):
        raise RuntimeError('Prior submission attempt exists; reconcile employer state instead of retrying')
    if not command.get('all_required_answers_verified'):
        raise RuntimeError('Required-answer verification missing')
    if not command.get('attachment_verified'):
        raise RuntimeError('Exact matching attachment and successful upload not verified')
    with timing().phase('preparation'):
        fresh=fresh_row(packet['id'])
    assert fresh['Company']==packet['company'] and fresh['Job Title']==packet['title']
    assert fresh['Resume Link']==packet['row']['Resume Link']
    snap=snapshot(page)
    resume=pathlib.Path(packet['resume'])
    if command.get('resume_format')=='pdf':
        validation=json.loads((out/'pdf-validation.json').read_text(encoding='utf-8-sig'))
        assert validation['status']=='native-valid' and validation['word_pages']==validation['pdf_pages']==2
        assert pathlib.Path(validation['docx'])==resume
        resume=resume.with_suffix('.pdf')
        assert pathlib.Path(validation['pdf'])==resume and resume.is_file()
    data=resume.read_bytes()
    uploaded=state.get('resume',{})
    assert uploaded.get('sha256')==hashlib.sha256(data).hexdigest(), 'Resume changed or upload evidence missing'
    if command.get('short_name'):
        assert packet['id'] in (2934,2936)
        alias=out/'Dave-Call-Resume.docx'
        assert alias.is_file() and alias.read_bytes()==data
        resume=alias
    assert uploaded.get('filename')==resume.name and uploaded.get('bytes')==len(data)
    files=[f for fr in snap['frames'] for f in fr.get('fields',[]) if f.get('files')]
    selected_matching_file=any(any(x['name']==resume.name and x['size']==len(data) for x in f['files']) for f in files)
    if files:
        assert selected_matching_file, 'Selected resume differs'
    text=' '.join(fr.get('text','') for fr in snap['frames'])
    controls=[f for fr in snap['frames'] for f in fr.get('fields',[])]
    removable=any(f['visible'] and f['tag']=='BUTTON' and re.search(r'remove.*file|remove.*resume',f['label']+' '+f['text'],re.I) for f in controls)
    completed_uploads=page.locator('.dz-success.dz-complete').all_text_contents()
    dropzone_success=any(resume.name.lower() in item.lower() for item in completed_uploads)
    assert (resume.name.lower() in text.lower() or selected_matching_file) and (re.search(r'\bSuccess!|upload complete|file uploaded',text,re.I) or removable or uploaded.get('upload_http_success') or dropzone_success or selected_matching_file), 'Upload success not verified'
    assert page.url==command['expected_url'], 'Application identity changed'
    title_present=packet['title'].lower() in ' '.join(fr.get('text','') for fr in snap['frames']).lower()
    if not title_present and packet['id']==2903:
        parent=json.loads((ROOT/'reports/playwright-pilot/batch-resumed-20261023/2903/latest.json').read_text())
        assert packet['title'].lower() in ' '.join(fr.get('text','') for fr in parent['frames']).lower()
        current=urlparse(page.url);query=parse_qs(current.query)
        assert current.hostname=='job-boards.greenhouse.io' and current.path=='/embed/job_app'
        assert query.get('for')==['pinterest'] and query.get('token')==['8268329']
        assert any(parse_qs(urlparse(fr['url']).query).get('token')==['8268329'] for fr in parent['frames'][1:])
        title_present=True
    assert title_present,'Employer job title not verified'
    invalid=[]
    for frame in page.frames:
        invalid.extend(frame.locator('input:invalid,textarea:invalid,select:invalid').evaluate_all('''els=>els.filter(e=>!(e.type==='checkbox'&&e.name&&e.form&&[...e.form.querySelectorAll('input[type="checkbox"]')].some(x=>x.name===e.name&&x.checked))).map(e=>({name:e.name,id:e.id,message:e.validationMessage}))'''))
    assert not invalid, 'Form validation incomplete: '+json.dumps(invalid)
    visible_errors=validation_messages(page)
    assert not visible_errors, 'Page validation incomplete: '+json.dumps(visible_errors)
    fi=command.get('frame',0)
    target=page.frames[fi].locator(command['selector'])
    assert target.count()==1 and target.is_visible() and target.is_enabled()
    target.click(trial=True,timeout=8000)  # Do not claim an attempt for a covered/unready control.
    before=page.locator('body').inner_text()
    confirmation=command.get('confirmation_text','')
    pattern=command.get('confirmation_pattern')
    if pattern:
        pattern='(?:'+pattern+r")|we(?:'ve| have) received\s+your application\b|your application was successfully submitted\b|you have successfully applied\b|Our Talent Acquisition team is currently reviewing your resume"
        assert not re.search(pattern,before,re.I),'Confirmation wording was already present'
    else:
        assert confirmation and confirmation.lower() not in before.lower()
    attempt={'id':packet['id'],'company':packet['company'],'title':packet['title'],'attempted_at':datetime.now(timezone.utc).isoformat(),'url':page.url}
    attempt['job_url']=packet.get('row',{}).get('Job URL',packet.get('url',''))
    claim_attempt(packet,out,attempt)  # Durable cross-batch guard before the final click.
    lifecycle = getattr(SESSION, 'browser_lifecycle', None) if SESSION else None
    try:
        target.click(no_wait_after=True,timeout=15000)
    except Exception:
        if not lifecycle or lifecycle.page == page or not page.is_closed():
            raise
    if lifecycle:
        page = lifecycle.page
        lifecycle.verify('submission confirmation')
        page.wait_for_load_state('domcontentloaded', timeout=20000)
    with timing().phase('waiting'):
        for handoff in range(2):
            try:
                if pattern:
                    result=page.wait_for_function('(pattern)=>{if(!document.body)return false;const errors=('+VALIDATION_JS+')();'
                        'if(errors.length)return {errors};'
                        'if(new RegExp(pattern,"i").test(document.body.innerText))return {confirmed:true};}',arg=pattern,timeout=20000)
                    observed=result.json_value()
                    result.dispose()
                    if observed.get('errors'):
                        state['submission_validation']=observed['errors']
                        save(out/'submission-validation.json',{'url':page.url,'messages':observed['errors']})
                        raise RuntimeError('Employer form requires correction: '+'; '.join(observed['errors']))
                    confirmation=re.search(pattern,page.locator('body').inner_text(),re.I).group(0)
                else:
                    page.get_by_text(confirmation,exact=False).first.wait_for(state='visible',timeout=20000)
                break
            except Exception:
                if handoff or not lifecycle or lifecycle.page == page or not page.is_closed():
                    raise
                page = lifecycle.page
                lifecycle.verify('popup confirmation handoff')
    after=page.locator('body').inner_text()
    assert not re.search(r'verify your email|verification link.{0,100}complete your application',after,re.I|re.S),'Email verification remains pending'
    receipt=dict(attempt,submitted_at=datetime.now(timezone.utc).isoformat(),confirmation_verified=True,confirmation_text=confirmation,confirmation_url=page.url)
    save(out/'receipt.json',receipt)
    with timing().phase('tracker'):
        if SESSION is not None:
            verified=SESSION.tracker.call('receipt',receipt=receipt)
        else:
            completed=subprocess.run([str(DASH),str(ROOT/'scripts/playwright_tracker.py'),'--receipt',str(out/'receipt.json')],capture_output=True,text=True,timeout=60)
            if completed.returncode: raise RuntimeError('Employer receipt saved; tracker update requires reconciliation: '+completed.stderr[-1000:])
            verified=json.loads(completed.stdout)
    assert verified.get('verified') is True, 'Tracker readback not verified'
    state.update(status='Applied \u2014 employer confirmed',tracker=verified,receipt=receipt)
    save(out/'state.json',state)
    # Confirmation is recorded in the tracker before optional screenshot work.
    try:page.screenshot(path=str(out/'submission-confirmed.png'),full_page=True,timeout=15000)
    except Exception as exc:state['confirmation_screenshot_error']=str(exc)[:200]
    return {'url':page.url,'frames':[{'frame':0,'url':page.url,'text':after,'fields':[]}]}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packets',required=True,type=pathlib.Path)
    args=ap.parse_args();base=args.packets.resolve().parent
    packets={p['id']:p for p in json.loads(args.packets.read_text())}
    states={i:{'id':i,'company':p['company'],'title':p['title'],'status':p['status'],'reason':p.get('reason')} for i,p in packets.items()}
    pages={}
    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(ROOT/'.tools/playwright-batch-profile'),channel='chrome',headless=False)
        while context.pages:
            for path in sorted(base.glob('command-*.json')):
                result_path=path.with_name(path.stem+'-result.json')
                if path.stem.endswith('-result') or result_path.exists(): continue
                command=json.loads(path.read_text(encoding='utf-8-sig'));ident=int(command['id']);packet=packets[ident];state=states[ident]
                out=base/str(ident);out.mkdir(exist_ok=True)
                result={'id':ident,'action':command['action']}
                try:
                    assert packet['status']=='queued','Skipped/Applied job cannot be opened'
                    if command['action']=='open':
                        assert ident not in pages,'Reuse existing draft'
                        (ROOT/'openclaw/application-answers.md').read_text(encoding='utf-8-sig')
                        page=context.new_page();pages[ident]=page;page.set_default_timeout(8000)
                        page.goto(command.get('url',packet['url']),wait_until='domcontentloaded',timeout=35000)
                        wait_page(page,timing())
                        snap=snapshot(page)
                        if command.get('prepare'):
                            # Navigate only a visible, ordinary Apply/Application control.
                            files=[f for fr in snap['frames'] for f in fr.get('fields',[]) if f['type']=='file']
                            if not files:
                                candidates=[(fr['frame'],f) for fr in snap['frames'] for f in fr.get('fields',[]) if f['visible'] and f['tag'] in ('A','BUTTON') and f['text'].strip().lower() in ('apply for this job','apply now','apply','application') and f['type']!='submit']
                                if candidates:
                                    fi,f=candidates[0]
                                    page.frames[fi].locator(f'[data-gecko-index="{f["index"]}"]').click()
                                    page.frames[fi].locator('input,textarea,select').first.wait_for(state='attached',timeout=12000)
                            snap=fill_supported(page,packet,state)
                    else:
                        page=pages[ident]
                        if command['action']=='inspect': snap=snapshot(page)
                        elif command['action']=='prepare': snap=fill_supported(page,packet,state)
                        elif command['action']=='submit': snap=submit(page,packet,state,command,out)
                        else:
                            frame=page.frames[command.get('frame',0)];el=frame.locator(command['selector'])
                            assert el.count()==1
                            if command['action']=='fill': el.fill(command['value'])
                            elif command['action']=='select': el.select_option(label=command['value'])
                            elif command['action']=='check': el.set_checked(command['value'])
                            elif command['action']=='click':
                                text=el.inner_text();typ=el.get_attribute('type')
                                assert typ!='submit' and not re.search(r'submit|send application|finish',text,re.I),'Use guarded submit action'
                                from playwright_fast import mutation_signature,wait_transition
                                before=mutation_signature(frame)
                                el.click();wait_transition(frame,before,timing())
                            else: raise ValueError('Unknown action')
                            snap=snapshot(page)
                    result.update(ok=True,page=snap)
                    save(out/'latest.json',snap)
                    page.screenshot(path=str(out/'latest.png'),full_page=True,timeout=15000)
                    if not state['status'].startswith('Applied'): state['status']='Needs review — not submitted'
                    state['url']=page.url
                    state['missing_required']=missing_fields(snap)
                except Exception as exc:
                    result.update(ok=False,error=str(exc));state.update(status='Needs attention',error=str(exc))
                    if ident in pages:
                        try:
                            snap=snapshot(pages[ident]);save(out/'latest.json',snap)
                            state['missing_required']=missing_fields(snap)
                        except Exception: pass
                save(result_path,result);save(base/'progress.json',list(states.values()))
                print(json.dumps({k:v for k,v in result.items() if k!='page'}),flush=True)
            time.sleep(.3)


if __name__=='__main__': main()
