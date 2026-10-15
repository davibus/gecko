from pathlib import Path
import json
from native_browser import call
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');scope=json.loads((Q/'batch-rows2-100-20261014-snapshot.json').read_text());allowed=set(json.loads((Q/'batch-rows2-100-20261014-approved-ids.json').read_text()))
for n,row in scope['rows']:
 j=str(row['Scout ID']);q=Q/j;pkg=q/'application-package.json'
 if not pkg.exists() or j in ['2241','2242','696']:continue
 p=json.loads(pkg.read_text());url=p['company_application_url']
 if 'jobs.lever.co/' not in url:continue
 if str(row.get('Applied','')).strip().lower() not in ['','no','false']:continue
 if (q/'submission-result.json').exists() and json.loads((q/'submission-result.json').read_text(encoding='utf-8-sig')).get('outcome')=='submitted':continue
 assert j in allowed and 2<=n<=100
 try:
  t=call(['open',url,'--label','employer-inspect-20261014-'+j])['targetId']
  r=call(['evaluate','--target-id',t,'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText,links:Array.from(document.querySelectorAll("a[href]")).map(e=>({text:e.innerText,url:e.href})).filter(e=>/apply|application/i.test(e.text))})'])['result']
  e={'id':j,'row':n,'company':p['company'],'job_title':p['job_title'],'targetId':t,'page':r};(q/'browser-inspection-20261014.json').write_text(json.dumps(e,indent=2));print(json.dumps({'id':j,'title':r['title'],'location_excerpt':r['text'][:550],'apply_links':r['links']}),flush=True)
 except Exception as error:print(json.dumps({'id':j,'runtime_error':str(error)}),flush=True)
