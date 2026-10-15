import sys,json
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2];Q=ROOT/'openclaw/application-queue';sys.path.insert(0,str(ROOT/'job-scout'))
from google_tracker import GoogleTracker,_col,_a1
ids=['1418', '1448', '1472', '1478', '1480', '1490', '1495', '1597', '1589', '1596', '1408', '1411', '1519', '1521'];held=json.loads((Q/'pending-user-1408-1603.json').read_text(encoding='utf-8'))['held'];assert set(ids)==set(held)
t=GoogleTracker();t.discover_workbook(required=(t.config.scout_tab,));tab=t.tab(t.config.scout_tab);formula=t.tab(tab.title,value_render_option='FORMULA');assert tab.headers==formula.headers and tab.sheet_id==formula.sheet_id
assert tab.title=='Job List', 'Expected the Job List tab'
assert 'Apply?' in tab.headers and 'Notes' in tab.headers
print(json.dumps({'tab':tab.title,'managed_column':tab.headers['Notes'],'Apply?_column':tab.headers['Apply?']}),flush=True)
updates=[];before={};skipped=[];expected={}
for j in ids:
 pf=Q/j/'application-package.json'
 if pf.exists():p=json.loads(pf.read_text(encoding='utf-8'))
 else:
  original=next(rr for nn,rr in json.loads((Q/'batch-1408-1603-tracker-snapshot.json').read_text(encoding='utf-8'))['rows'] if str(rr.get('Scout ID'))==j);p={'company':original['Company'],'job_title':original['Job Title'],'company_application_url':original['Job URL']}
 original=next(rr for nn,rr in json.loads((Q/'batch-1408-1603-tracker-snapshot.json').read_text(encoding='utf-8'))['rows'] if str(rr.get('Scout ID'))==j);assert original['Company']==p['company'] and original['Job Title']==p['job_title'];p['company_application_url']=original['Job URL']
 e=json.loads((Q/j/'submission-result.json').read_text(encoding='utf-8'));assert e['outcome'] in ['held_location','manual_attention'];hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1;n,r=hits[0];assert r['Company']==p['company'] and r['Job Title']==p['job_title'] and r['Job URL']==p['company_application_url'];assert r.get('Applied','')=='';fh=[(nn,rr) for nn,rr in formula.rows if str(rr.get('Scout ID'))==j];assert len(fh)==1 and fh[0][0]==n;fr=fh[0][1];before[j]={'row':n,'values':r};expected[j]={}
 security_review='security-verification page' in held[j]
 notes='Held: '+held[j]
 if security_review:
  link_note='Manual application link: '+r['Job URL']
  if link_note not in notes:notes=notes.rstrip()+'\n'+link_note
 apply_value=('' if r.get('Apply?')=='No' else r.get('Apply?','')) if security_review else 'No'
 for field,value in [('Notes',notes)]:
  col=tab.headers[field];fv=fr.get(field,'');protected=isinstance(fv,str) and fv.startswith('=')
  for rn,raw in (formula.raw_rows or {}).items():
   for cn,anchor in enumerate(raw,1):
    if isinstance(anchor,str) and 'ARRAYFORMULA' in anchor.upper() and n>=rn and col>=cn:protected=True
  if protected:skipped.append({'job_id':j,'field':field,'reason':'Formula protection'});continue
  expected[j][field]=value
  if r.get(field,'')!=value:updates.append({'range':_a1(tab.title,f'{_col(col)}{n}'),'values':[[value]]})
audit=Q/'held-notes-overwrite-1408-1603-20261013-0903.json';audit.write_text(json.dumps({'before':before,'updates':updates,'skipped':skipped},indent=2),encoding='utf-8')
if updates:t.api.values().batchUpdate(spreadsheetId=t.config.spreadsheet_id,body={'valueInputOption':'RAW','data':updates}).execute()
after=t.tab(tab.title);assert after.headers==tab.headers and after.sheet_id==tab.sheet_id;verified=[]
for j in ids:
 n=before[j]['row'];hits=[(nn,rr) for nn,rr in after.rows if str(rr.get('Scout ID'))==j];assert len(hits)==1 and hits[0][0]==n;r=hits[0][1]
 for k,v in before[j]['values'].items():assert r.get(k)==expected[j].get(k,v),'Unexpected field change: '+j+' '+k
 for k,v in expected[j].items():assert r.get(k)==v
 verified.append({'job_id':j,'row':n,'Apply?':r.get('Apply?'),'Notes':r.get('Notes'),'Applied':r.get('Applied','')})
audit.write_text(json.dumps({'before':before,'updates':updates,'skipped':skipped,'verified':verified},indent=2),encoding='utf-8');print(json.dumps({'updated_jobs':len(verified),'cells_written':len(updates),'skipped':skipped,'readback_verified':True,'manual_application_links':[{'job_id':j,'company':before[j]['values']['Company'],'job_title':before[j]['values']['Job Title'],'url':before[j]['values']['Job URL']} for j in ids if 'security-verification page' in held[j]]}))
