from pathlib import Path
import json,time
from native_browser import call
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');scope=json.loads((Q/'batch-rows2-100-20261014-snapshot.json').read_text());out=[]
for n,row in scope['rows']:
 j=str(row['Scout ID'])
 if str(row.get('Applied','')).strip().lower() not in ['','no','false'] or j=='2240':continue
 q=Q/j;q.mkdir(exist_ok=True)
 try:
  tabs=call(['tabs']).get('tabs',[]);existing=[t for t in tabs if t.get('label')=='batch20261014-'+j];t=existing[0]['targetId'] if existing else call(['open',row['Job URL'],'--label','batch20261014-'+j])['targetId'];time.sleep(1)
  r=call(['evaluate','--target-id',t,'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText,links:Array.from(document.querySelectorAll("a[href]")).map(e=>({text:e.innerText,url:e.href})).filter(e=>/apply|application/i.test(e.text)),iframes:Array.from(document.querySelectorAll("iframe[src]")).map(e=>e.src)})']);f=r['result'];security=any(x in (f['title']+' '+f['text']).lower() for x in ['verify you are human','security verification','checking your browser','just a moment...']);item={'id':j,'row':n,'company':row['Company'],'job_title':row['Job Title'],'targetId':t,'page':f,'security_verification':security};(q/'browser-inspection-20261014.json').write_text(json.dumps(item,indent=2));out.append(item);print(json.dumps({'id':j,'title':f['title'],'url':f['url'],'security':security,'apply_links':f['links'][:3],'text_length':len(f['text'])}),flush=True)
 except Exception as e:
  item={'id':j,'row':n,'runtime_error':str(e)};out.append(item);print(json.dumps(item),flush=True)
 (Q/'batch-rows2-100-20261014-browser-inspections.json').write_text(json.dumps(out,indent=2))
