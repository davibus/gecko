"""Short-lived Playwright commands against Gecko's dedicated local Chrome.

Chrome uses a separate profile and loopback debugging port. Disconnecting this
client preserves open tabs. No OpenClaw or AI service is called.
"""
import argparse
import hashlib
import json
import pathlib
import time
from playwright.sync_api import sync_playwright
from playwright_batch import ROOT, fresh_row, snapshot, fill_supported, missing_fields, submit, supported_answer
from playwright_application import save


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--request',required=True,type=pathlib.Path)
    args=ap.parse_args();request=json.loads(args.request.read_text(encoding='utf-8-sig'))
    base=ROOT/'reports/playwright-pilot/direct-20261023';base.mkdir(exist_ok=True)
    ident=int(request['id']);out=base/str(ident);out.mkdir(exist_ok=True)
    packets={p['id']:p for p in json.loads((base/'packets.json').read_text())};packet=packets[ident]
    assert packet['status']=='queued'
    state=json.loads((out/'state.json').read_text()) if (out/'state.json').exists() else {'id':ident,'company':packet['company'],'title':packet['title'],'status':'pending'}
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9333')
        context=browser.contexts[0]
        pages=[p for p in context.pages if p.evaluate('window.name')==f'gecko-{ident}']
        page=pages[0] if len(pages)==1 else None
        results=[]
        for action in request['actions']:
            record={'action':action['action']}
            try:
                if action['action']=='open':
                    assert page is None,'Draft already exists; inspect it instead'
                    assert not any((ROOT/'reports/playwright-pilot').glob(f'*/{ident}/submission-attempt.json')), 'Prior submission attempt must be reconciled, never repeated'
                    fresh=fresh_row(ident)
                    assert fresh['Company']==packet['company'] and fresh['Job Title']==packet['title']
                    page=context.new_page();page.set_default_timeout(8000)
                    page.goto(action.get('url',packet['url']),wait_until='domcontentloaded',timeout=35000)
                    page.evaluate('(name)=>window.name=name',f'gecko-{ident}')
                    page.wait_for_timeout(1000)
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
                        page.goto(action['url'],wait_until='domcontentloaded');page.wait_for_timeout(1000)
                    elif action['action']=='inspect_dom':
                        save(out/'dom.json',frame.locator(action['selector']).evaluate_all('(els)=>els.map(e=>e.outerHTML.slice(0,18000))'))
                    elif action['action']=='decline_cookies':
                        frame.get_by_role('button',name='Decline all non-necessary cookies',exact=True).click()
                        page.wait_for_timeout(700)
                    elif action['action']=='dismiss_zip':
                        frame.locator('#skip-zip-code').click();page.wait_for_timeout(500)
                    elif action['action']=='decline_frame_cookies':
                        frame.locator('#decline_cookies_button').click();page.wait_for_timeout(500)
                    elif action['action']=='next_step':
                        target=frame.locator(action['selector'])
                        assert target.count()==1 and target.inner_text().strip() in ('Next','Next Step','Save & Continue')
                        target.click(no_wait_after=True);page.wait_for_timeout(2000)
                    elif action['action']=='show_application':
                        target=frame.get_by_role('button',name='Apply for this job',exact=True).first
                        assert target.is_visible()
                        target.click();page.wait_for_timeout(1000)
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
                        if action['action']=='fill': element.fill(action['value'])
                        elif action['action']=='type': element.fill('');element.press_sequentially(action['value'],delay=30);element.press('Tab')
                        elif action['action']=='cover_letter':
                            letter=out/'cover-letter.txt'
                            assert letter.is_file() and letter.stat().st_size>100
                            element.set_input_files(str(letter));page.wait_for_timeout(3000)
                        elif action['action']=='press': element.press(action['value']);page.wait_for_timeout(1000)
                        elif action['action']=='check': element.set_checked(action['value'])
                        elif action['action']=='select': element.select_option(label=action['value'])
                        elif action['action']=='choose':
                            option=frame.get_by_role('option',name=action['value'],exact=True)
                            if option.count()!=1 or not option.is_visible():element.click()
                            page.wait_for_timeout(500)
                            assert option.count()==1,'Option is not uniquely available'
                            option.click()
                        elif action['action']=='click':
                            assert element.get_attribute('type')!='submit'
                            assert not any(x in element.inner_text().lower() for x in ('submit application','send application','finish'))
                            element.click();page.wait_for_timeout(800)
                        elif action['action']=='upload':
                            resume=pathlib.Path(packet['resume'])
                            if action.get('pdf'):resume=resume.with_suffix('.pdf')
                            assert resume.parent==ROOT/'output/resumes' and resume.is_file()
                            if action.get('short_name'):
                                assert ident in (2934,2936)
                                original=resume
                                resume=out/'Dave-Call-Resume.docx'
                                resume.write_bytes(original.read_bytes())
                                assert hashlib.sha256(resume.read_bytes()).digest()==hashlib.sha256(original.read_bytes()).digest()
                            received=[]
                            def on_response(response):
                                if response.request.method in ('POST','PUT') and 200<=response.status<300:received.append(response.status)
                            page.on('response',on_response)
                            try:
                                data=resume.read_bytes();element.set_input_files(str(resume));page.wait_for_timeout(4000)
                            finally:page.remove_listener('response',on_response)
                            state['resume']={'filename':resume.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'upload_http_success':bool(received)}
                        else:raise ValueError('Unknown action')
                record['ok']=True
            except Exception as exc:
                record.update(ok=False,error=str(exc));state['status']='Needs attention'
                results.append(record)
                break
            results.append(record)
        if page:
            snap=snapshot(page);save(out/'latest.json',snap)
            state.update(url=page.url,missing_required=missing_fields(snap))
            try:page.screenshot(path=str(out/'latest.png'),full_page=True,timeout=15000)
            except Exception:pass
        save(out/'state.json',state);save(args.request.with_suffix('.result.json'),results)
        print(json.dumps({'id':ident,'results':results,'missing_required':[x.split('\n')[0][:150] for x in state.get('missing_required',[])]}))


if __name__=='__main__':main()
