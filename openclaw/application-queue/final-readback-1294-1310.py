import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'job-scout'))
from google_tracker import GoogleTracker
ids=['1294','1295','1296','1297','1298','1299','1301','1302','1303','1304','1305','1306','1308','1309','1310']
t=GoogleTracker();t.discover_workbook(required=(t.config.scout_tab,));tab=t.tab(t.config.scout_tab)
results=[]
for j in ids:
 q=ROOT/'openclaw/application-queue'/j
 p=json.loads((q/'application-package.json').read_text(encoding='utf-8'));e=json.loads((q/'submission-result.json').read_text(encoding='utf-8'))
 hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1
 n,r=hits[0]
 assert r['Company']==p['company'] and r['Job Title']==p['job_title'] and r['Job URL']==p['company_application_url']
 assert e['outcome'] in ['submitted','pending_user']
 assert r.get('Applied','')==('X' if e['outcome']=='submitted' else '')
 if e['outcome']=='submitted':assert e['tracker_readback_result']['Applied']=='X' and e['uploaded_filename']==Path(p['verified_resume_file_path']).name
 results.append({'job_id':j,'company':r['Company'],'row':n,'outcome':e['outcome'],'Applied':r.get('Applied','')})
(ROOT/'openclaw/application-queue/final-readback-1294-1310.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results))
