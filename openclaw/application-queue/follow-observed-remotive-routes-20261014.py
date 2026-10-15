from pathlib import Path
import json
from native_browser import call
Q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['467','469','470','472','473','475','477','480','484','709','2228']:
 try:
  r=json.loads((Q/j/'browser-inspection-20261014.json').read_text());urls=list(dict.fromkeys(x['url'] for x in r['page']['links'] if x['text'].strip() in ['Apply for this position','Apply now »','Apply now','Apply for this role']));assert len(urls)==1,{'observed_apply_urls':urls}
  t=call(['open',urls[0],'--label','direct-apply-20261014-'+j])['targetId'];v=call(['evaluate','--target-id',t,'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText,links:Array.from(document.querySelectorAll("a[href]")).map(e=>({text:e.innerText,url:e.href})).filter(e=>/apply|application/i.test(e.text))})'])['result'];(Q/j/'outbound-route-20261014.json').write_text(json.dumps({'id':j,'targetId':t,'page':v},indent=2));print(json.dumps({'id':j,'url':v['url'],'title':v['title'],'excerpt':v['text'][:800]}),flush=True)
 except Exception as e:print(json.dumps({'id':j,'error':str(e)[:200]}),flush=True)
