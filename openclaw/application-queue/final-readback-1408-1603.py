import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];Q=ROOT/'openclaw/application-queue';sys.path.insert(0,str(ROOT/'job-scout'))
from google_tracker import GoogleTracker
ids=json.loads((Q/'batch-1408-1603-approved-ids.json').read_text(encoding='utf-8'));original={str(r['Scout ID']):r for n,r in json.loads((Q/'batch-1408-1603-tracker-snapshot.json').read_text(encoding='utf-8'))['rows']};t=GoogleTracker();t.discover_workbook(required=(t.config.scout_tab,));tab=t.tab(t.config.scout_tab);result=[]
for j in ids:
 e=json.loads((Q/j/'submission-result.json').read_text(encoding='utf-8'));hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1;n,r=hits[0]
 for k in ['Company','Job Title','Job URL','Resume Created','Resume Link']:assert r.get(k)==original[j].get(k),j+' '+k+' changed'
 assert e['outcome'] in ['submitted','pending_user','held_location','manual_attention','blocked']
 assert r.get('Applied','')==('X' if e['outcome']=='submitted' else '')
 if e['outcome']=='submitted':
  p=json.loads((Q/j/'application-package.json').read_text(encoding='utf-8'));assert e['tracker_readback_result']['Applied']=='X' and e['uploaded_filename']==Path(p['verified_resume_file_path']).name
 if e['outcome'] in ['held_location','manual_attention','blocked']:
  assert e['reason'] in r.get('Notes','')
  if 'security-verification page' in e['reason']:assert r.get('Apply?','')!='No' and 'Manual application link: '+r['Job URL'] in r.get('Notes','')
  else:assert r.get('Apply?')=='No'
 result.append({'job_id':j,'company':r['Company'],'job_title':r['Job Title'],'row':n,'outcome':e['outcome'],'Applied':r.get('Applied',''),'Apply?':r.get('Apply?'),'reason':e.get('reason'),'questions':e.get('blocking_questions',[])})
(Q/'final-readback-1408-1603.json').write_text(json.dumps(result,indent=2),encoding='utf-8');counts={x:sum(r['outcome']==x for r in result) for x in sorted(set(r['outcome'] for r in result))};print(json.dumps({'counts':counts,'verified_jobs':len(result),'submitted_ids':[r['job_id'] for r in result if r['outcome']=='submitted'],'pending_ids':[r['job_id'] for r in result if r['outcome']=='pending_user']}))
