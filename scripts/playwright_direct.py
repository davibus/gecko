"""Short-lived Playwright commands against Gecko's dedicated local Chrome.

Chrome uses a separate profile and loopback debugging port. Disconnecting this
client preserves open tabs. No OpenClaw or AI service is called.
"""
import argparse
import hashlib
import json
import pathlib
import time
import sys
from application_runtime import Timings, prior_attempt, save
from application_browser import request_tab_session
from application_forms import wait_page, upload_resume, verify_answer_action
from playwright.sync_api import sync_playwright
from playwright_batch import ROOT, fresh_row, snapshot, fill_supported, missing_fields, submit, supported_answer


def main():
    if not __debug__:
        raise RuntimeError('Run without Python -O: browser guards require assertions')
    if not any(a=='--request' or a.startswith('--request=') for a in sys.argv):
        from playwright_fast import main as run_batch
        return run_batch()
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--request',required=True,type=pathlib.Path)
    ap.add_argument('--evidence-dir',type=pathlib.Path)
    args=ap.parse_args();request=json.loads(args.request.read_text(encoding='utf-8-sig'))
    base=(args.evidence_dir or ROOT/'reports/playwright-pilot/direct-20261023').resolve()
    assert base.parent == (ROOT/'reports/playwright-pilot').resolve(), 'Evidence must remain in the application audit directory'
    base.mkdir(exist_ok=True)
    ident=int(request['id']);out=base/str(ident);out.mkdir(exist_ok=True)
    packets={p['id']:p for p in json.loads((base/'packets.json').read_text(encoding='utf-8'))};packet=packets[ident]
    assert packet['status']=='queued'
    state=json.loads((out/'state.json').read_text(encoding='utf-8')) if (out/'state.json').exists() else {'id':ident,'company':packet['company'],'title':packet['title'],'status':'pending'}
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9333')
        context=browser.contexts[0]
        with request_tab_session(context,base,packet,state) as lifecycle:
            page=lifecycle.page if lifecycle.data.get('current_job')==ident else None
            results=[]
            for action in request['actions']:
                record={'action':action['action']}
                try:
                    if action['action'] not in ('inspect','inspect_dom','front'):
                        assert not prior_attempt(packet,out), 'Prior submission attempt must be reconciled before further actions'
                    if action['action']=='open':
                        assert page is None,'Draft already exists; inspect it instead'
                        assert not prior_attempt(packet,out), 'Prior submission attempt must be reconciled, never repeated'
                        fresh=fresh_row(ident)
                        assert fresh['Company']==packet['company'] and fresh['Job Title']==packet['title']
                        assert fresh['Resume Link']==packet['row']['Resume Link'], 'Prepared resume link changed'
                        from playwright_batch import sources_for_batch
                        state['prepared_answers']=sources_for_batch().for_job(packet)
                        resume=pathlib.Path(packet['resume'])
                        assert resume.parent==ROOT/'output/resumes' and resume.is_file() and resume.stat().st_size>0
                        page=lifecycle.begin(packet,state)
                        page.evaluate('(name)=>window.name=name',f'gecko-{ident}')
                        state['draft_opened']=True
                        save(out/'state.json',state)
                        page.evaluate('(name)=>window.name=name',f'gecko-{ident}')
                        wait_page(page,Timings())
                    else:
                        assert page is not None,'No exact draft tab found'
                        page.set_default_timeout(8000)
                        frame=page.frames[action.get('frame',0)]
                        if action['action']=='inspect': pass
                        elif action['action']=='navigate':
                            observed=snapshot(page)
                            allowed={fr['url'] for fr in observed['frames']}
                            allowed.update(f['href'] for fr in observed['frames'] for f in fr.get('fields',[]) if f['tag']=='A')
                            assert action['url'] in allowed,'Navigation URL must be observed on the current employer page'
                            assert not (out/'submission-attempt.json').exists()
                            page.goto(action['url'],wait_until='domcontentloaded');wait_page(page,Timings())
                            page.evaluate('(name)=>window.name=name',f'gecko-{ident}')
                        elif action['action']=='inspect_dom':
                            save(out/'dom.json',frame.locator(action['selector']).evaluate_all('(els)=>els.map(e=>e.outerHTML.slice(0,18000))'))
                        elif action['action']=='decline_cookies':
                            frame.get_by_role('button',name='Decline all non-necessary cookies',exact=True).click()
                            frame.get_by_role('button',name='Decline all non-necessary cookies',exact=True).wait_for(state='hidden',timeout=8000)
                        elif action['action']=='dismiss_zip':
                            frame.locator('#skip-zip-code').click();frame.locator('#skip-zip-code').wait_for(state='hidden',timeout=8000)
                        elif action['action']=='decline_frame_cookies':
                            frame.locator('#decline_cookies_button').click();frame.locator('#decline_cookies_button').wait_for(state='hidden',timeout=8000)
                        elif action['action']=='next_step':
                            target=frame.locator(action['selector'])
                            assert target.count()==1 and target.inner_text().strip() in ('Next','Next Step','Save & Continue')
                            from playwright_fast import mutation_signature,wait_transition
                            before=mutation_signature(frame)
                            target.click(no_wait_after=True);wait_transition(frame,before,Timings())
                        elif action['action']=='show_application':
                            target=frame.get_by_role('button',name='Apply for this job',exact=True).first
                            assert target.is_visible()
                            target.click();frame.locator('input,textarea,select').first.wait_for(state='attached',timeout=12000)
                        elif action['action']=='prepare': fill_supported(page,packet,state)
                        elif action['action']=='known_dropdowns':
                            snap=snapshot(page)
                            for fr in snap['frames']:
                                for f in fr.get('fields',[]):
                                    if not f['visible'] or f['tag'] not in ('INPUT','SELECT'):continue
                                    value=supported_answer(f,packet)
                                    if value is None:continue
                                    if not f['id'] and not f['name']:continue
                                    sel='[id='+json.dumps(f['id'])+']' if f['id'] else '[name='+json.dumps(f['name'])+']'
                                    el=page.frames[fr['frame']].locator(sel)
                                    if el.count()!=1:continue
                                    if el.get_attribute('role')!='combobox':continue
                                    try:
                                        el.click()
                                        opts=page.frames[fr['frame']].get_by_role('option')
                                        names=opts.all_text_contents()
                                        candidates=[(i,n) for i,n in enumerate(names) if n.strip().lower()==value.lower() or (value=='United States' and n.replace(' ','')=='UnitedStates+1')]
                                        if len(candidates)==1:opts.nth(candidates[0][0]).click()
                                        else:el.press('Escape')
                                    except Exception as exc:
                                        state.setdefault('dropdown_errors',[]).append({'question':f['label'],'error':str(exc)[:100]})
                        elif action['action']=='submit': submit(page,packet,state,action,out)
                        elif action['action']=='front': page.bring_to_front()
                        else:
                            element=frame.locator(action['selector']);assert element.count()==1
                            if action['action'] in ('fill','type','check','select','choose'):
                                from playwright_batch import sources_for_batch
                                confirmed=verify_answer_action(element,action,packet,sources_for_batch(),frame.url)
                                state.setdefault('fallback_answers',[]).append({'question':action['selector'],'answer_id':confirmed['id'],'source':confirmed['source'],'confirmed_on':confirmed['confirmed_on'],'scope':confirmed['scope']})
                            if action['action']=='fill': element.fill(action['value'])
                            elif action['action']=='type': element.fill('');element.press_sequentially(action['value'],delay=30);element.press('Tab')
                            elif action['action']=='cover_letter':
                                letter=out/'cover-letter.txt'
                                assert letter.is_file() and letter.stat().st_size>100
                                element.set_input_files(str(letter));assert element.evaluate('(e)=>e.files[0].size')==letter.stat().st_size
                            elif action['action']=='press':
                                assert action['value'] not in ('Enter','NumpadEnter'), 'Use guarded submit or Next action'
                                element.press(action['value'])
                            elif action['action']=='check': element.set_checked(action['value'])
                            elif action['action']=='select': element.select_option(label=action['value'])
                            elif action['action']=='choose':
                                option=frame.get_by_role('option',name=action['value'],exact=True)
                                if option.count()!=1 or not option.is_visible():element.click()
                                option.wait_for(state='visible',timeout=8000)
                                assert option.count()==1,'Option is not uniquely available'
                                option.click()
                            elif action['action']=='click':
                                assert element.get_attribute('type')!='submit'
                                import re
                                assert not re.search(r'\bsubmit\b|send application|\bfinish\b|\bapply\b',element.inner_text(),re.I), 'Use guarded submit or application-opening action'
                                from playwright_fast import mutation_signature,wait_transition
                                before=mutation_signature(frame)
                                element.click();wait_transition(frame,before,Timings())
                            elif action['action']=='upload':
                                resume=pathlib.Path(packet['resume'])
                                if action.get('pdf'):
                                    validation=json.loads((out/'pdf-validation.json').read_text(encoding='utf-8-sig'))
                                    assert validation['status']=='native-valid' and validation['word_pages']==validation['pdf_pages']==2
                                    assert pathlib.Path(validation['docx'])==resume
                                    resume=resume.with_suffix('.pdf')
                                    assert pathlib.Path(validation['pdf'])==resume
                                assert resume.parent==ROOT/'output/resumes' and resume.is_file()
                                if action.get('short_name'):
                                    assert ident in (2934,2936)
                                    original=resume
                                    resume=out/'Dave-Call-Resume.docx'
                                    resume.write_bytes(original.read_bytes())
                                    assert hashlib.sha256(resume.read_bytes()).digest()==hashlib.sha256(original.read_bytes()).digest()
                                observed=snapshot(page)
                                selector=action['selector']
                                indexed=element.get_attribute('data-gecko-index')
                                matches=[(fr['frame'],f) for fr in observed['frames'] for f in fr.get('fields',[]) if fr['frame']==action.get('frame',0) and str(f['index'])==indexed and f['type']=='file']
                                upload_packet=dict(packet,resume=str(resume))
                                if action.get('pdf'):upload_packet.pop('resume_sha256',None)
                                upload_resume(page,upload_packet,state,matches,Timings())
                            else:raise ValueError('Unknown action')
                    record['ok']=True
                except Exception as exc:
                    record.update(ok=False,error=str(exc));state['status']='Needs attention'
                    results.append(record)
                    break
                results.append(record)
                save(out/'state.json',state)
            page=lifecycle.page if lifecycle.data.get('current_job')==ident else page
            if page:
                snap=snapshot(page);save(out/'latest.json',snap)
                state.update(url=page.url,missing_required=missing_fields(snap))
                try:page.screenshot(path=str(out/'latest.png'),full_page=True,timeout=15000)
                except Exception:pass
            save(out/'state.json',state);save(args.request.with_suffix('.result.json'),results)
            print(json.dumps({'id':ident,'results':results,'missing_required':[x.split('\n')[0][:150] for x in state.get('missing_required',[])]}))


if __name__=='__main__':main()
