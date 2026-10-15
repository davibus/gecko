from current_batch_ui import UI
from native_browser import call
from pathlib import Path
import json,time
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');rows={str(r['Scout ID']):r for n,r in json.loads((Q/'batch-rows2-100-20261014-snapshot.json').read_text())['rows']};out=[]
for j in ['2231','2232','2233','2234','2235','2238','2239']:
 try:
  listing=rows[j]['Job URL'];tabs=call(['tabs']).get('tabs',[]);matches=[x for x in tabs if x['url']==listing];t=matches[0]['targetId'] if matches else call(['open',listing,'--label','route20261014-'+j])['targetId'];u=UI(t);u.call(['evaluate','--fn','() => ({title:document.title,text:document.body.innerText})']);s=u.snap();before={x['targetId'] for x in call(['tabs']).get('tabs',[])};u.call(['click',u.ref(s,'button','Apply Now')]);time.sleep(2);tabs=call(['tabs']).get('tabs',[]);new=[x for x in tabs if x['targetId'] not in before];current=next((x for x in tabs if x['targetId']==t),None);item={'id':j,'listing_url':listing,'opened_tabs':[{'targetId':x['targetId'],'url':x['url'],'title':x['title']} for x in new],'current_tab':{k:current[k] for k in ['targetId','url','title']} if current else None};(Q/j/'observed-employer-route-20261014.json').write_text(json.dumps(item,indent=2));out.append(item);print(json.dumps(item),flush=True)
 except Exception as e:item={'id':j,'error':str(e)};out.append(item);print(json.dumps(item),flush=True)
 (Q/'jobicy-employer-routes-20261014.json').write_text(json.dumps(out,indent=2))
