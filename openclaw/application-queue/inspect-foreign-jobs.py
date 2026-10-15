from native_browser import call
from pathlib import Path
import json
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['1318','1320','1383','1396','1407']:
 p=json.loads((q/j/'application-package.json').read_text());target='geo-'+j
 if (q/j/'live-location-review.json').exists():continue
 tabs=call(['tabs'])['tabs'];hits=[t for t in tabs if t.get('label')==target]
 if not hits:call(['open',p['company_application_url'],'--label',target])
 r=call(['evaluate','--target-id',target,'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText.slice(0,16000)})']);(q/j/'live-location-review.json').write_text(json.dumps(r,indent=2));print(json.dumps({'id':j,'url':r['result']['url'],'heading':r['result']['text'][:420]}),flush=True)
