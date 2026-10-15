import sys,os,json
from pathlib import Path
R=Path('C:/gecko_main');Q=R/'openclaw/application-queue';sys.path.insert(0,str(R/'job-scout'));from google_tracker import load_environment;from discover_ats_employers import _brave_search
load_environment();key=os.getenv('BRAVE_SEARCH_API_KEY','').strip();assert key
queries={'2225': 'Vasion "Senior Growth Marketing Manager" careers', '2226': 'Leland "Performance Marketing Manager" careers', '2255': 'John Gore "Regional Director of Marketing" careers', '39': 'Five Star Franchising "Director of Performance Marketing" careers', '50': 'Aptive "Sr. Manager, Marketing Analytics" careers', '57': 'Front Climbing Club "Senior Sales and Marketing Manager" careers', '559': 'Pattern "Paid Media Manager" careers', '564': 'RainFocus "Product Marketing Manager" "Events" careers', '567': 'Hire Resolve "Mid-Senior Sales" Marketing application', '568': 'Digital Marketing "Director of Business Development" "National SEO"', '726': 'CAI World-Wide "Marketing Manager" careers', '474': 'Mitre Media "Tech Lead" "Rails" careers'};out=[]
for j,query in queries.items():
 try:results=_brave_search(query,key);item={'job_id':j,'search_ok':True,'query':query,'results':[{'title':r.get('title'),'url':r.get('url'),'description':r.get('description')} for r in results]}
 except Exception as error:item={'job_id':j,'search_ok':False,'error':str(error).replace(key,'[redacted]')[:450]}
 out.append(item);(Q/'brave-remaining-routes-20261014.json').write_text(json.dumps(out,indent=2),encoding='utf-8');print(json.dumps({'job_id':j,'search_ok':item['search_ok'],'candidates':[{'title':r['title'],'url':r['url']} for r in item.get('results',[])[:4]]}),flush=True)
