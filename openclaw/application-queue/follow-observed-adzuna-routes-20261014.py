from pathlib import Path
import json
from native_browser import call
Q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['2225','2226','2255','39','50','57','559','564','567','568','726']:
 try:
  r=json.loads((Q/j/'browser-inspection-20261014.json').read_text());urls=list(dict.fromkeys(x['url'] for x in r['page']['links'] if x['text'].strip()=='Apply for this job'));assert len(urls)==1
  t=call(['open',urls[0],'--label','source-apply-20261014-'+j])['targetId'];v=call(['evaluate','--target-id',t,'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText,links:Array.from(document.querySelectorAll("a[href]")).map(e=>({text:e.innerText,url:e.href})).filter(e=>/apply|application/i.test(e.text))})'])['result'];(Q/j/'outbound-route-20261014.json').write_text(json.dumps({'id':j,'targetId':t,'page':v},indent=2));print(json.dumps({'id':j,'url':v['url'],'title':v['title'],'excerpt':v['text'][:260],'apply_links':v['links'][:3]}),flush=True)
 except Exception as e:print(json.dumps({'id':j,'error':str(e)[:180]}),flush=True)
