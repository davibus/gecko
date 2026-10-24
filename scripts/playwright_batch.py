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
from playwright_application import save, ROOT

DASH = ROOT / '.tools/dashboard-python/Scripts/python.exe'


def fresh_row(ident):
    result = subprocess.run([str(DASH), str(ROOT/'scripts/playwright_tracker.py'),
                             '--check', str(ident)], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Primary tracker preflight failed: ' + result.stderr[-1200:])
    return json.loads(result.stdout)


def snapshot(page):
    frames = []
    for fi, frame in enumerate(page.frames):
        try:
            fields = frame.locator('input,textarea,select,button,a').evaluate_all(r'''els=>els.map((e,i)=>{
                e.setAttribute('data-gecko-index',String(i));
                const p=e.closest('.application-question,.application-field,fieldset,.form-group,.field,.ashby-application-form-field-entry')||e.parentElement?.parentElement;
                let question=p?.innerText?.slice(0,1600)||'';
                if(!question){for(let a=e.parentElement,n=0;a&&n<6;a=a.parentElement,n++){const t=a.innerText?.trim();if(t){question=t.slice(0,1600);break}}}
                const m=(e.name||'').match(/^cards\[([^\]]+)\]\[field(\d+)\]$/);
                if(m){const template=[...document.querySelectorAll('input')].find(t=>t.name==='cards['+m[1]+'][baseTemplate]');
                    if(template){try{question=JSON.parse(template.value).fields[Number(m[2])].text}catch{}}}
                return {index:i,tag:e.tagName,type:e.type||'',id:e.id,name:e.name||'',
                  label:([...(e.labels||[])].map(l=>l.innerText).join(' ')||e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').split('\n')[0],
                  context:question,text:(e.innerText||'').slice(0,200),href:e.href||'',
                  required:!!e.required||e.getAttribute('aria-required')==='true',valid:e.validity?e.validity.valid:true,validationMessage:e.validationMessage||'',visible:!!(e.offsetWidth||e.offsetHeight||e.getClientRects().length),
                  value:e.type==='password'?'<redacted>':e.type==='hidden'?'<hidden>':e.value||'',checked:!!e.checked,
                  files:e.files?[...e.files].map(f=>({name:f.name,size:f.size})):[],
                  options:e.options?[...e.options].map(o=>({text:o.text,value:o.value,selected:o.selected})):[]};
                })''')
            frames.append({'frame':fi,'url':frame.url,'text':frame.locator('body').inner_text(timeout=5000)[:20000], 'fields':fields,
                           'choices':frame.locator('[role="option"]:visible').all_text_contents()})
        except Exception as exc:
            frames.append({'frame':fi,'url':frame.url,'error':str(exc)[:200]})
    return {'url':page.url,'title':page.title(),'frames':frames}


def supported_answer(field, packet):
    label = re.sub(r'[*✱]','',field['label']).strip().lower()
    name = field['name'].lower()
    context=field['context'] if len(field['context'])<=650 else ''
    q = (label+' '+context).lower()
    # Exact contact labels/names. Larger contexts are used only for screening questions.
    if label in ('full name','name') or name == 'name': return 'Dave Call'
    if 'legal first name' in label: return 'Mark'
    if 'legal last name' in label: return 'Call'
    if 'legal name' in label: return 'Mark David Call'
    if label in ('first name','preferred first name','preferred name') or name=='first_name': return 'Dave'
    if name=='preferred_name':return 'Dave'
    if label == 'last name' or name=='last_name': return 'Call'
    if label in ('email','email address','retype email address') or name=='email': return 'mdavidcall@gmail.com'
    if label in ('phone','phone number','mobile phone') or name=='phone': return '(530) 507-8269'
    if label=='city' or 'city of residence' in label:return 'American Fork'
    if label in ('current location','location (city)') or name=='location': return 'American Fork, UT, USA'
    if label in ('address','street address'):return '1046 W 360 S'
    if 'residential address' in label:return '1046 W 360 S, American Fork, UT 84003, United States'
    if label in ('state','state/province') or 'state of residence' in label:return 'UT'
    if label in ('postal','postal code','zip','zip code'):return '84003'
    if 'linkedin' in label or name=='urls[linkedin]': return 'https://www.linkedin.com/in/mdavidcall'
    if label=='current company' or name=='org': return 'ILT Marketing'
    if label in ('country','country/region','country of residence'): return 'United States'
    if re.search(r'(desired|expected|expectations).{0,30}(salary|compensation)|(salary|compensation).{0,30}(desired|expected|expectations|requirement|targeting)',q) and not any(x in q for x in ('aligned','posted range','acceptable')): return '70000'
    if any(x in q for x in ('are you located in the united states','are you located within the us','do you reside in the united states','do you live in the united states')): return 'Yes'
    if re.search(r'(require|need|requiring).{0,60}(sponsor|visa)',q): return 'No'
    if re.search(r'(legally authorized|legally employable|authorized to work|authorization to work)',q): return 'Yes'
    if 'previously' in q and re.search(r'(employed|worked)',q) and 'applied' not in q and 'offer' not in q: return 'No'
    if ('referred' in q or 'employee referral' in q) and 'name' not in label: return 'No'
    if 'gender' == label: return 'Male'
    if label=='race':return 'White'
    if 'pronouns' in label:return 'He/him'
    if 'veteran' in label: return 'I am not a veteran'
    if 'text message' in q or 'sms' in q: return 'No'
    ident=packet['id']
    if ident in (2905,2906,2907):
        if any(x in q for x in ('built seo performance reports','primary strategic point of contact','optimized for ai search','personally managed and optimized live campaigns','main point of contact for a portfolio of paid media')): return 'Yes'
        if ident==2906 and ('client-facing' in q or 'account management role' in q): return '8'
    if ident==2925 and 'considered for other positions' in q: return 'Yes'
    if ident==2928:
        if 'high school diploma' in q: return 'Yes'
        if 'how many years' in q and 'b2b marketing campaigns' in q: return '5–7 years of relevant experience'
        if 'best describes your experience supporting events' in q: return 'I have occasionally supported events as part of a broader marketing role'
    if ident==2931 and 'worked for eleanor health before' in q: return 'No'
    if ident==2933 and 'certifications do you currently hold' in q: return 'None'
    return None


def fill_supported(page, packet, state):
    snap=snapshot(page)
    for fr in snap['frames']:
        for f in fr.get('fields',[]):
            if not f['visible'] or f['tag'] not in ('INPUT','TEXTAREA','SELECT') or f['type'] in ('hidden','password','file','submit','button'): continue
            value=supported_answer(f,packet)
            if value is None: continue
            # Preserve user-entered values. Radio changes only select matching confirmed choices.
            if f['type'] not in ('radio','checkbox') and f['value'].strip(): continue
            el=page.frames[fr['frame']].locator(f'[data-gecko-index="{f["index"]}"]')
            try:
                if f['type']=='radio':
                    if f['value'].strip().lower()==value.lower() or f['label'].strip().lower()==value.lower(): el.check()
                    else: continue
                elif f['type']=='checkbox': continue
                elif f['tag']=='SELECT':
                    opts=[o for o in f['options'] if o['text'].strip().lower()==value.lower()]
                    if len(opts)!=1: continue
                    el.select_option(value=opts[0]['value'])
                else: el.fill(value)
                state.setdefault('filled',[]).append({'question':f['label'] or f['context'][:300],'answer':value})
            except Exception as exc: state.setdefault('field_errors',[]).append(str(exc)[:180])
    # Only upload when the actual field identifies itself as Resume/CV.
    snap=snapshot(page)
    files=[(fr['frame'],f) for fr in snap['frames'] for f in fr.get('fields',[]) if f['type']=='file' and re.search(r'resume|\bcv\b',f['label']+' '+f['name']+' '+f['context'],re.I) and 'cover letter' not in f['label'].lower()]
    if len(files)==1:
        fi,f=files[0]
        if not f['files']:
            data=pathlib.Path(packet['resume']).read_bytes()
            page.frames[fi].locator(f'[data-gecko-index="{f["index"]}"]').set_input_files(packet['resume'])
            page.wait_for_timeout(5000)
            state['resume']={'filename':pathlib.Path(packet['resume']).name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'content_verified':False}
    return snapshot(page)


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
    if (out/'submission-attempt.json').exists():
        raise RuntimeError('Prior submission attempt exists; reconcile employer state instead of retrying')
    if not command.get('all_required_answers_verified'):
        raise RuntimeError('Required-answer verification missing')
    if not command.get('attachment_verified'):
        raise RuntimeError('Exact matching attachment and successful upload not verified')
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
    invalid=page.locator('input:invalid,textarea:invalid,select:invalid').evaluate_all('''els=>els.filter(e=>!(e.type==='checkbox'&&e.name&&[...e.form.querySelectorAll('input[type="checkbox"]')].some(x=>x.name===e.name&&x.checked))).map(e=>({name:e.name,id:e.id,message:e.validationMessage}))''')
    assert not invalid, 'Form validation incomplete: '+json.dumps(invalid)
    fi=command.get('frame',0)
    target=page.frames[fi].locator(command['selector'])
    assert target.count()==1 and target.is_visible() and target.is_enabled()
    before=page.locator('body').inner_text()
    confirmation=command.get('confirmation_text','')
    pattern=command.get('confirmation_pattern')
    if pattern:
        pattern='(?:'+pattern+r")|we(?:'ve| have) received\s+your application|your application is in|your application was successfully submitted|you have successfully applied|Our Talent Acquisition team is currently reviewing your resume"
        assert not re.search(pattern,before,re.I),'Confirmation wording was already present'
    else:
        assert confirmation and confirmation.lower() not in before.lower()
    attempt={'id':packet['id'],'company':packet['company'],'title':packet['title'],'attempted_at':datetime.now(timezone.utc).isoformat(),'url':page.url}
    save(out/'submission-attempt.json',attempt)  # Never resend after an uncertain result.
    target.click(no_wait_after=True,timeout=15000)
    page.wait_for_timeout(3000)
    if pattern:
        page.wait_for_function('(pattern)=>new RegExp(pattern,"i").test(document.body.innerText)',arg=pattern,timeout=20000)
        confirmation=re.search(pattern,page.locator('body').inner_text(),re.I).group(0)
    else:
        page.get_by_text(confirmation,exact=False).first.wait_for(state='visible',timeout=20000)
    after=page.locator('body').inner_text()
    assert not re.search(r'verify your email|verification link.{0,100}complete your application',after,re.I|re.S),'Email verification remains pending'
    receipt=dict(attempt,submitted_at=datetime.now(timezone.utc).isoformat(),confirmation_verified=True,confirmation_text=confirmation,confirmation_url=page.url)
    save(out/'receipt.json',receipt)
    try:page.screenshot(path=str(out/'submission-confirmed.png'),full_page=True,timeout=15000)
    except Exception as exc:state['confirmation_screenshot_error']=str(exc)[:200]
    completed=subprocess.run([str(DASH),str(ROOT/'scripts/playwright_tracker.py'),'--receipt',str(out/'receipt.json')],capture_output=True,text=True,timeout=60)
    if completed.returncode: raise RuntimeError('Employer receipt saved; tracker update requires reconciliation: '+completed.stderr[-1000:])
    state.update(status='Applied — employer confirmed',tracker=json.loads(completed.stdout),receipt=receipt)
    return snapshot(page)


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
                        page.wait_for_timeout(1500)
                        snap=snapshot(page)
                        if command.get('prepare'):
                            # Navigate only a visible, ordinary Apply/Application control.
                            files=[f for fr in snap['frames'] for f in fr.get('fields',[]) if f['type']=='file']
                            if not files:
                                candidates=[(fr['frame'],f) for fr in snap['frames'] for f in fr.get('fields',[]) if f['visible'] and f['tag'] in ('A','BUTTON') and f['text'].strip().lower() in ('apply for this job','apply now','apply','application') and f['type']!='submit']
                                if candidates:
                                    fi,f=candidates[0]
                                    page.frames[fi].locator(f'[data-gecko-index="{f["index"]}"]').click()
                                    page.wait_for_timeout(2000)
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
                                el.click();page.wait_for_timeout(1000)
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
