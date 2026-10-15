from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from native_browser import call
Q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['2243','704','708']:
 q=Q/j;e=json.loads((q/'submission-result.json').read_text());p=json.loads((q/'application-package.json').read_text());r=call(['evaluate','--target-id',e['targetId'],'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText,iframes:Array.from(document.querySelectorAll("iframe")).map(e=>e.title)})'])['result'];(q/'current-submission-state-20261014.json').write_text(json.dumps(r,indent=2))
 if r['url']==p['company_application_url'].rstrip('/')+'/thanks' and 'Application submitted!' in r['text']:e.update(outcome='submitted',confirmation_url=r['url'],confirmation_text=r['text'],timestamp=datetime.now(ZoneInfo('America/Denver')).isoformat(),security_verification=False);(q/'submission-result.json').write_text(json.dumps(e,indent=2))
 print(json.dumps({'id':j,'outcome':e['outcome'],'url':r['url'],'receipt':'Application submitted!' in r['text'],'security_widgets':r['iframes']}),flush=True)
