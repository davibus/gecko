from native_browser import call
import json,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
q=Path('/mnt/c/gecko_main/openclaw/application-queue/2234');e=json.loads((q/'submission-result.json').read_text());p=json.loads((q/'application-package.json').read_text());t=e['targetId'];r=json.loads((q/'current-form-20261014.json').read_text())['result'];assert not r['invalid'];assert e['uploaded_filename'] in r['text'];v={x['id']:x['value'] for x in r['fields']};assert v['first_name']=='Dave' and v['last_name']=='Call' and v['email']=='mdavidcall@gmail.com' and v['question_9125578005']=='Director of Marketing';assert r['url']==p['company_application_url'];s=call(['snapshot','--target-id',t,'--format','ai','--interactive','--compact']);hits=[k for k,v in s['refs'].items() if v['role']=='button' and v.get('name')=='Submit application'];assert len(hits)==1
call(['click',hits[0],'--target-id',t]);time.sleep(3);r=call(['evaluate','--target-id',t,'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText})'])['result'];(q/'after-submit-20261014.json').write_text(json.dumps(r,indent=2));e.update(timestamp=datetime.now(ZoneInfo('America/Denver')).isoformat(),application_url=p['company_application_url'])
if r['url'].endswith('/confirmation') and 'Your application has been received' in r['text']:e.update(outcome='submitted',confirmation_url=r['url'],confirmation_text=r['text'])
elif 'verification code' in r['text'].lower() or 'Security code' in r['text']:e.update(outcome='verification_pending',form_response=r['text'])
else:e.update(outcome='confirmation_review',confirmation_url=r['url'],confirmation_text=r['text'])
(q/'submission-result.json').write_text(json.dumps(e,indent=2));print(json.dumps({'id':'2234','outcome':e['outcome'],'url':r['url'],'response':r['text'][-2500:]}))
