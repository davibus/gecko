import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'job-scout'))
from google_tracker import GoogleTracker
ids=['1311','1313','1314','1318','1320','1321','1358','1360','1362','1363','1376','1379','1380','1381','1383','1384','1391','1396','1399','1400','1407']
t=GoogleTracker();t.discover_workbook(required=(t.config.scout_tab,));tab=t.tab(t.config.scout_tab)
results=[]
for j in ids:
 q=ROOT/'openclaw/application-queue'/j
 p=json.loads((q/'application-package.json').read_text(encoding='utf-8'));e=json.loads((q/'submission-result.json').read_text(encoding='utf-8'))
 hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1
 n,r=hits[0]
 assert r['Company']==p['company'] and r['Job Title']==p['job_title'] and r['Job URL']==p['company_application_url']
 assert e['outcome'] in ['submitted','pending_user','held_location','manual_attention']
 assert r.get('Applied','')==('X' if e['outcome']=='submitted' else '')
 if e['outcome']=='submitted':assert e['tracker_readback_result']['Applied']=='X' and e['uploaded_filename']==Path(p['verified_resume_file_path']).name
 if e['outcome'] in ['held_location','manual_attention']:
  assert r.get('Apply?')=='No' and 'Held: '+e['reason'] in r.get('Notes','')
 results.append({'job_id':j,'company':r['Company'],'row':n,'outcome':e['outcome'],'Applied':r.get('Applied',''),'Apply?':r.get('Apply?'),'Notes':r.get('Notes','')})
(ROOT/'openclaw/application-queue/final-readback-1311-1407.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results))
