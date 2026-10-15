import sys,os,json
from pathlib import Path
R=Path('C:/gecko_main');Q=R/'openclaw/application-queue';sys.path.insert(0,str(R/'job-scout'));from google_tracker import load_environment;from discover_ats_employers import _brave_search
load_environment();key=os.getenv('BRAVE_SEARCH_API_KEY','').strip();assert key
queries={'2222':'site:jobs.siemens.com "Product Marketing Lead" "ICX"','2229':'site:careers.zoom.us "Product Growth Marketing Manager"','4':'"Digital Marketing" "Paid Search Specialist" "Utah" job application','36':'"Marrina Decisions" "Senior Marketing Operations Lead" job','47':'"Cambia Health Solutions" "Manager Clinical Pharmacy Services" careers','476':'"iMerit" "AI Response Evaluator" careers'};out=[]
for j,query in queries.items():
 try:results=_brave_search(query,key);item={'job_id':j,'search_ok':True,'query':query,'results':[{'title':r.get('title'),'url':r.get('url'),'description':r.get('description')} for r in results]}
 except Exception as error:item={'job_id':j,'search_ok':False,'error':str(error).replace(key,'[redacted]')[:450]}
 out.append(item);(Q/'brave-application-routes-retry-20261014.json').write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps({'job_id':j,'search_ok':item['search_ok'],'candidates':[{'title':r['title'],'url':r['url']} for r in item.get('results',[])[:4]]}),flush=True)
