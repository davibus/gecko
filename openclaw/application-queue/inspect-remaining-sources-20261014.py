from pathlib import Path
import json
from native_browser import call
Q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['2225','2226','2228','2255','39','50','57','559','564','567','568','726','709','467','469','470','472','473','474','475','477','478','480','484','2236']:
 p=json.loads((Q/j/'application-package.json').read_text());t=call(['open',p['company_application_url'],'--label','recovered-employer-20261014-'+j])['targetId'];r=call(['evaluate','--target-id',t,'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText,links:Array.from(document.querySelectorAll("a[href]")).map(e=>({text:e.innerText,url:e.href})).filter(e=>/apply|application/i.test(e.text)),iframes:Array.from(document.querySelectorAll("iframe")).map(e=>({title:e.title,src:e.src}))})'])['result'];(Q/j/'browser-inspection-20261014.json').write_text(json.dumps({'id':j,'targetId':t,'page':r},indent=2));print(json.dumps({'id':j,'title':r['title'],'excerpt':r['text'][:600],'apply_links':r['links'],'iframes':r['iframes']}),flush=True)
