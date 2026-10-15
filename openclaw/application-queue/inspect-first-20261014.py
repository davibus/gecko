from pathlib import Path
import json,time
from native_browser import call
Q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['2242','2237','2225']:
 p=json.loads((Q/j/'application-package.json').read_text());r=call(['open',p['company_application_url'],'--label','batch20261014-'+j]);t=r['targetId'];time.sleep(1);r=call(['evaluate','--target-id',t,'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText,links:Array.from(document.querySelectorAll("a[href]")).map(e=>({text:e.innerText,url:e.href})).filter(e=>/apply|application/i.test(e.text))})']);(Q/j/'initial-browser-20261014.json').write_text(json.dumps({'targetId':t,'page':r},indent=2));f=r['result'];print(json.dumps({'id':j,'targetId':t,'url':f['url'],'title':f['title'],'text':f['text'][:2400],'links':f['links']}),flush=True)
