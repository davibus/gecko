"""Conservative form plans for platforms observed in Gecko's saved browser evidence."""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from urllib.parse import urlsplit

from application_runtime import meaning

# These are field-name hints, not employer answers or account-profile mappings.
# Screening fields always use the question's meaning and scoped answer bank.
PLATFORMS = {
    'lever': {'hosts': ('jobs.lever.co',), 'names': {'name': 'full_name', 'email': 'email',
              'phone': 'phone', 'urls[linkedin]': 'linkedin', 'org': 'current_company'}},
    'greenhouse': {'hosts': ('job-boards.greenhouse.io', 'boards.greenhouse.io'),
                  'names': {'first_name': 'first_name', 'last_name': 'last_name',
                            'email': 'email', 'phone': 'phone'}},
    'ashby': {'hosts': ('jobs.ashbyhq.com',), 'names': {'_systemfield_name': 'full_name',
              '_systemfield_email': 'email', '_systemfield_phone': 'phone'}},
    'jazzhr': {'hosts': ('applytojob.com',), 'names': {'firstName': 'first_name',
                'lastName': 'last_name', 'email': 'email', 'phone': 'phone'}},
}


def platform(url):
    host = (urlsplit(url).hostname or '').lower()
    for key, spec in PLATFORMS.items():
        if any(host == h or host.endswith('.' + h) for h in spec['hosts']):
            return key
    return 'generic'


VISIBLE_JS = r'''e => {
    if (!e || !e.getClientRects().length) return false;
    const r=e.getBoundingClientRect(); if(r.width<=0 || r.height<=0) return false;
    for(let a=e;a;a=a.parentElement) {
        const s=getComputedStyle(a);
        if(s.display==='none'||s.visibility==='hidden'||s.visibility==='collapse'||
           Number(s.opacity)===0||a.hidden||a.getAttribute('aria-hidden')==='true') return false;
    }
    return true;
}'''


class FormNavigation(RuntimeError):
    """The document changed; discard its field handles and inspect the new page."""


VALIDATION_JS = r'''() => {
    const visible = e => !!e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
    const errors = [...document.querySelectorAll('[role="alert"],.field-error,.error-message,.error-container .error,[class*="_errorMessage_"],[class*="_error_"],.ashby-application-form-field-error')]
        .filter(visible).map(e => e.innerText?.trim()).filter(Boolean);
    for (const e of document.querySelectorAll('input,select,textarea')) {
        if(e.disabled || e.type==='hidden') continue;
        const labels=[...(e.labels||[])];
        if(!visible(e) && !labels.some(visible)) continue;
        const question=labels.map(l=>l.innerText).join(' ').trim() || e.name || e.id;
        if(e.validity && !e.validity.valid) errors.push(question+': '+e.validationMessage);
        if(e.getAttribute('aria-invalid')==='true') {
            const ids=(e.getAttribute('aria-errormessage')||e.getAttribute('aria-describedby')||'').split(/\s+/);
            const message=ids.map(id=>document.getElementById(id)).filter(x=>x&&visible(x)).map(x=>x.innerText).join(' ');
            errors.push(question+': '+(message||'Invalid or incomplete answer'));
        }
    }
    return [...new Set(errors)].slice(0,20);
}'''


def validation_messages(page):
    return [message for frame in page.frames if frame_visible(frame)
            for message in frame.evaluate(VALIDATION_JS)]


def frame_visible(frame):
    current = frame
    while current.parent_frame is not None:
        element = current.frame_element()
        try:
            if not element.evaluate(VISIBLE_JS):
                return False
        finally:
            element.dispose()
        current = current.parent_frame
    return True


def captcha_evidence(page):
    """Report a displayed challenge, never the presence of an integration/badge.

    Check live ancestor visibility even for cross-origin child frames. Saved
    child-body text alone cannot establish that a challenge was visible.
    """
    reasons = []
    for frame in page.frames:
        if not frame_visible(frame):
            continue
        url = frame.url.split('?')[0]
        text = frame.locator('body').inner_text(timeout=3000) if frame.locator('body').count() else ''
        match = re.search(r"verify (?:that )?you are human|i.m not a robot|human check|recaptcha requires verification|complete (?:the )?captcha", text, re.I)
        if match:
            reasons.append({'frame': url, 'reason': 'visible challenge text', 'text': match.group(0)})
        widgets = frame.locator('iframe[src*="recaptcha"],iframe[src*="hcaptcha"]').evaluate_all(
            '(els)=>{const visible='+VISIBLE_JS+r''';return els.filter(e=>{
                if(!visible(e)||e.closest('.grecaptcha-badge')) return false;
                const u=new URL(e.src,location.href);
                if(u.searchParams.get('size')==='invisible') return false;
                return /challenge|bframe/i.test(e.title+' '+u.pathname) ||
                    /recaptcha|hcaptcha/i.test(e.title) || u.searchParams.get('size')==='normal';
            }).map(e=>({title:e.title,url:e.src.split('?')[0]}));}''')
        reasons.extend({'frame': url, 'reason': 'visible challenge frame', **w} for w in widgets)
    return {'blocking': bool(reasons), 'evidence': reasons}


def captcha_visible(page, snap=None):
    return captcha_evidence(page)['blocking']


def profile_uploader(field):
    context = ' '.join(str(field.get(k, '')) for k in ('id', 'name', 'context', 'form_action', 'form_id'))
    return bool(re.search(r'global_resume|my[-_]?profile|resume[-_]?database|discovered by (?:global )?employers|make .*default resume|save .*profile', context, re.I))


def resume_fields(snap):
    """Allow hidden employer upload controls, but never a site-wide profile upload."""
    candidates = []
    for fr in snap['frames']:
        if fr.get('visible') is False:
            continue
        for f in fr.get('fields', []):
            if f['type'] != 'file' or f.get('disabled') or profile_uploader(f):
                continue
            direct = ' '.join(str(f.get(k, '')) for k in ('label', 'name', 'id'))
            context = f.get('context', '')
            if 'cover letter' in direct.lower():
                continue
            if re.search(r'resume|\bcv\b', direct, re.I) or (
                    re.search(r'resume|\bcv\b', context, re.I) and 'cover letter' not in context.lower()):
                candidates.append((fr['frame'], f))
    return candidates


def answer_for(field, packet, sources, url=''):
    question = field.get('question') or field.get('label', '')
    answer = sources.resolve(question, packet)
    if answer:
        return answer
    # Standing agreement authorization applies to application terms/privacy,
    # never to an arbitrary Yes/Agree control or a factual certification.
    if field.get('type') in ('radio', 'checkbox'):
        q=meaning(question)
        topic=re.search(r'\b(?:privacy (?:notice|policy)|(?:application |terms and )conditions|terms (?:of use|of service|and conditions)|processing (?:of )?(?:my |your )?(?:application|personal data))\b', q)
        acceptance=re.search(r'\b(?:agree|accept|consent|acknowledge)\b',q)
        excluded=re.search(r'\b(?:sms|text messages|recruiting messages|certify|warrant|purchase|payment)\b',q)
        if topic and acceptance and not excluded:
            return sources.resolve('',packet,alias='application_agreement')
    # Unlabelled contact fields on a known platform have stable documented names.
    # A conflicting/unknown label always wins over the field-name hint.
    if not meaning(question):
        alias = PLATFORMS.get(platform(url), {}).get('names', {}).get(field.get('name'))
        if alias:
            return sources.resolve('', packet, alias=alias)
    return None


def verify_answer_action(element, action, packet, sources, url=''):
    """The unfamiliar-form fallback cannot promote proposed text into an answer."""
    field=element.evaluate("e=>({name:e.name||'',label:([...(e.labels||[])].map(l=>l.innerText).join(' ')||e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').split('\\n')[0],question:e.closest('fieldset')?.querySelector('legend')?.innerText||'',value:e.type==='checkbox'?e.checked:e.value||''})")
    field['question']=field['question'] or field['label']
    record=answer_for(field,packet,sources,url)
    if not record or (action.get('answer_id') and record['id']!=action['answer_id']):
        raise RuntimeError('Fallback field needs a matching scoped confirmed answer record')
    expected=record['answer']
    value=action['value']
    if isinstance(value,bool):
        value='Yes' if value else 'No'
    if meaning(value)!=meaning(expected):
        raise RuntimeError('Fallback value differs from its confirmed answer; proposed wording is not confirmed')
    if isinstance(field['value'],str) and field['value'].strip() and meaning(field['value'])!=meaning(expected):
        raise RuntimeError('Preserve existing answer for review instead of overwriting it')
    return record


def plan_fields(snap, packet, sources):
    plans = []
    for fr in snap['frames']:
        fields = fr.get('fields', [])
        for f in fields:
            combo = f.get('role') == 'combobox'
            if (not f['visible'] or f.get('disabled') or (f.get('readonly') and not combo) or
                    (f['tag'] not in ('INPUT', 'TEXTAREA', 'SELECT') and not combo) or
                    (f['type'] in ('hidden', 'password', 'file', 'submit', 'button') and not combo)):
                continue
            record = answer_for(f, packet, sources, fr['url'])
            if not record:
                continue
            value = str(record['answer'])
            if f['type'] == 'radio':
                group = [x for x in fields if x['type'] == 'radio' and x['name'] == f['name']]
                if any(x['checked'] for x in group):
                    continue
                if meaning(f['label']) != meaning(value) and meaning(f['value']) != meaning(value):
                    continue
            elif f['type'] == 'checkbox':
                # Only an explicitly confirmed affirmative answer can check a box.
                choices=record.get('choices',[])
                supported_choice=bool(choices) and meaning(f['label']) in [meaning(x) for x in choices]
                if f['checked'] or not (supported_choice or not choices and meaning(value) in ('yes', 'agree', 'i agree', 'accept')):
                    continue
            elif f['value'].strip():
                continue
            if f['tag'] == 'SELECT':
                opts = [o for o in f['options'] if meaning(o['text']) == meaning(value)]
                if len(opts) != 1:
                    continue
                value = opts[0]['value']
            plans.append({'frame': fr['frame'], 'index': f['index'], 'name': f['name'],
                          'id': f['id'], 'type': f['type'], 'value': value, 'record': record,
                          'question': f.get('question') or f['label'], 'field': f})
    return plans


def settle_field(frame):
    # Let synchronous rerenders and the next paint finish before acknowledging data.
    frame.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


def fill_combo(frame, element, plan):
    controls = element.get_attribute('aria-controls') or element.get_attribute('aria-owns')
    if not controls:
        raise RuntimeError('Custom dropdown lacks an identified option list')
    element.click(timeout=2500)
    if element.evaluate("e=>e.tagName==='INPUT'&&!e.readOnly"):
        element.fill(str(plan['record']['answer']), timeout=2500)
    selector = ','.join('[id='+json_quote(c)+'] [role=option]' for c in controls.split())
    options = frame.locator(selector).filter(has_text=re.compile('^'+re.escape(str(plan['record']['answer']))+'$', re.I))
    options.first.wait_for(state='visible', timeout=2500)
    if options.count() != 1:
        raise RuntimeError('Custom dropdown answer is ambiguous')
    options.click(timeout=2500)
    settle_field(frame)
    selected = element.evaluate(r'''e=>{
        const p=e.closest('.select__container,[class*="select-container"],.field,.form-group')||e.parentElement?.parentElement;
        const label=p?.querySelector('[class*="singleValue"],[class*="single-value"]')?.textContent?.trim();
        return {value:label||e.value||e.innerText||'',expanded:e.getAttribute('aria-expanded')};
    }''')
    if meaning(selected['value']) != meaning(plan['record']['answer']) or selected['expanded'] == 'true':
        raise RuntimeError('Custom dropdown selection did not persist')
    return {'ok': True, 'value': selected['value'], 'checked': False, 'choice_committed': True}


def json_quote(value):
    import json
    return json.dumps(value)


def fill_together(page, plans, state, timings):
    """Fill known controls, then verify live state after UI event processing."""
    results = []
    start_url = page.url
    with timings.phase('filling'):
        for p in plans:
            fi = p['frame']
            if page.url != start_url or fi >= len(page.frames):
                raise FormNavigation('Navigation during filling; inspect the new document')
            frame = page.frames[fi]
            element = frame.locator(f'[data-gecko-index="{p["index"]}"]')
            try:
                if element.count() != 1:
                    raise RuntimeError('Field replaced during filling; fresh inspection required')
                current = element.evaluate("e=>({name:e.name||'',id:e.id,type:e.type||'',value:e.tagName==='SELECT'&&!e.selectedOptions[0]?.text.trim()?'':e.value||'',checked:!!e.checked})")
                if any(current[k] != p[k] for k in ('id', 'name', 'type')):
                    raise RuntimeError('Field identity changed')
                if p['field'].get('role') == 'combobox':
                    result = fill_combo(frame, element, p)
                else:
                    if current['value'].strip() and p['type'] not in ('radio', 'checkbox'):
                        raise RuntimeError('Preserved existing answer')
                    if p['type'] in ('radio', 'checkbox'):
                        if p['field'].get('label_click'):
                            # Styled native choices are intentionally hidden. Click
                            # their associated visible label, never force the input.
                            labels = frame.locator('label').filter(visible=True)
                            candidates = [labels.nth(i) for i in range(labels.count())
                                          if labels.nth(i).evaluate('(l,id)=>l.control?.id===id', p['id'])]
                            if len(candidates) != 1:
                                raise RuntimeError('Visible choice label missing or ambiguous')
                            if not current['checked']:
                                candidates[0].click(timeout=2500)
                        else:
                            element.check(timeout=2500)
                    elif p['field']['tag'] == 'SELECT':
                        element.select_option(p['value'], timeout=2500)
                    else:
                        element.fill(p['value'], timeout=2500)
                        element.blur(timeout=2500)
                    settle_field(frame)
                    if page.url != start_url:
                        raise FormNavigation('Navigation during filling; inspect the new document')
                    current = element.evaluate("e=>({value:e.value||'',checked:!!e.checked})", timeout=2500)
                    result = dict(current, ok=current['checked'] if p['type'] in ('radio','checkbox') else current['value']==p['value'])
                if result['ok']:
                    p['field']['value'] = result['value']
                    p['field']['checked'] = result['checked']
                    if result.get('choice_committed'):
                        p['field']['choice_committed'] = True
                    audit = {'frame': fi, 'index': p['index'], 'question': p['question'],
                             'answer': p['record']['answer'], 'answer_id': p['record']['id'],
                             'source': p['record']['source'], 'confirmed_on': p['record']['confirmed_on'],
                             'scope': p['record']['scope'],
                             'choice_committed': bool(result.get('choice_committed'))}
                    state.setdefault('filled', []).append(audit)
                else:
                    raise RuntimeError('Filled value did not persist after form update')
            except Exception as exc:
                if isinstance(exc, FormNavigation) or page.url != start_url or frame.is_detached():
                    raise FormNavigation('Navigation during filling; inspect the new document') from exc
                result = {'ok': False, 'error': str(exc)[:250]}
                state.setdefault('field_errors', []).append({'question': p['question'], 'error': result['error']})
            results.append(result)
    return results


def wait_page(page, timings, *, selector=None, timeout=12000):
    with timings.phase('waiting'):
        page.wait_for_load_state('domcontentloaded', timeout=timeout)
        if selector:
            page.locator(selector).wait_for(state='visible', timeout=timeout)
        else:
            page.locator('body').wait_for(state='visible', timeout=timeout)


def upload_resume(page, packet, state, files, timings, *, timeout=20000):
    if len(files) != 1:
        raise RuntimeError('Resume upload field missing or ambiguous')
    fi, f = files[0]
    if profile_uploader(f):
        raise RuntimeError('Account-wide profile resume uploader is not an employer application')
    start_url = page.url
    path = Path(packet['resume'])
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    prepared = packet.get('resume_sha256')
    if prepared and prepared != digest:
        raise RuntimeError('Prepared resume changed before upload')
    el = page.frames[fi].locator(f'[data-gecko-index="{f["index"]}"]')
    expected = {'name': path.name, 'size': len(data)}
    with timings.phase('upload'):
        selected = el.evaluate('(e)=>[...(e.files||[])].map(f=>({name:f.name,size:f.size}))')
        if selected and selected != [expected]:
            raise RuntimeError('Existing attachment differs; preserve draft for review')
        previous=state.get('resume',{})
        acknowledged=page.frames[fi].locator('body').inner_text()
        reused=not selected and previous.get('upload_verified') and previous.get('sha256')==digest and path.name in acknowledged and re.search(r'upload complete|file uploaded|success|remove',acknowledged,re.I)
        state['resume_selection'] = dict(expected, sha256=digest, url=start_url)
        if not selected:
            if not reused:
                # Observe browser-assigned metadata in capture phase, before an
                # employer's change handler can remove the input.
                el.evaluate('''e=>{document.addEventListener('change',function capture(event){
                    if(event.target!==e)return;
                    window.__geckoSelectedResume=[...e.files].map(f=>({name:f.name,size:f.size}));
                    document.removeEventListener('change',capture,true);
                },true)}''')
                page.frames[fi].evaluate('window.__geckoSelectedResume=null')
                el.set_input_files(str(path))
        # Capture actual browser name and size before a site clears its input.
        if page.url != start_url:
            raise FormNavigation('Navigation during resume upload; verify the destination before continuing')
        selected = el.evaluate('(e)=>[...(e.files||[])].map(f=>({name:f.name,size:f.size}))', timeout=2500) if el.count() else []
        captured = page.frames[fi].evaluate('window.__geckoSelectedResume || []')
        # Upload handlers may replace/clear the input synchronously. Acknowledge
        # only after the exact filename and a completion control are observed.
        acknowledged = page.frames[fi].locator('body').inner_text()
        replaced_ack = path.name in acknowledged and re.search(r'upload complete|file uploaded|remove.*resume|remove.*file', acknowledged, re.I)
        if selected != [expected] and not reused and not (replaced_ack and captured == [expected]):
            raise RuntimeError('Selected browser filename/size not verified')
    frame = page.frames[fi]
    with timings.phase('waiting'):
        result=frame.wait_for_function(r'''p=>{
            const e=document.querySelector('[data-gecko-index="'+p.index+'"]');
            const text=document.body.innerText;
            const error=text.match(/invalid file type|upload failed|file too large|error uploading/i);
            if(error) return {error:error[0]};
            const busy=[...document.querySelectorAll('[aria-busy=true],.dz-processing,.upload-progress,progress')]
                .some(x=>x.getClientRects().length && !x.classList.contains('dz-complete') &&
                    !(x.tagName==='PROGRESS' && x.value>=x.max));
            const selected=e?.files?.length===1&&e.files[0].name===p.name&&e.files[0].size===p.size;
            const ack=text.includes(p.name)&&/upload complete|file uploaded|success|remove/i.test(text);
            const employerBusy=[...document.querySelectorAll('button[ng-disabled*="uploadingResume"]')]
                .some(x=>x.disabled && x.getClientRects().length);
            return !busy && !employerBusy && (selected||ack);
        }''', arg=dict(expected, index=f['index']), timeout=timeout)
        outcome=result.json_value()
        result.dispose()
        if isinstance(outcome,dict) and outcome.get('error'):
            raise RuntimeError('Resume upload failed: '+outcome['error'])
    with timings.phase('upload'):
        state['resume'] = {'filename': path.name, 'bytes': len(data), 'sha256': digest,
                           'selected_verified': True, 'upload_verified': True}
        f['files'] = [expected]
        f['value'] = path.name
    return state['resume']


def missing_questions(snap):
    questions = []
    for fr in snap['frames']:
        if fr.get('error'):
            questions.append({'frame': fr['frame'], 'question': 'Frame inspection unavailable', 'error': fr['error']})
        for f in fr.get('fields', []):
            if not f['visible'] or not f['required'] or f.get('disabled') or f['type'] == 'hidden':
                continue
            if f['type'] == 'radio':
                present = any(x['name'] == f['name'] and x['checked'] for x in fr['fields'])
            elif f['type'] == 'checkbox':
                group=[x for x in fr['fields'] if x['type']=='checkbox' and f['name'] and x['name']==f['name']]
                present = any(x['checked'] for x in group) if len(group)>1 else f['checked']
            elif f['type'] == 'file':
                present = bool(f['files'])
            else:
                present = bool(f['value'].strip())
            if not present:
                item = {'frame': fr['frame'], 'question': f.get('question') or f['label'] or f['name'],
                        'name': f['name'], 'id': f['id'], 'type': f['type']}
                if not any(q['frame'] == item['frame'] and q['question'] == item['question'] for q in questions):
                    questions.append(item)
    return questions
