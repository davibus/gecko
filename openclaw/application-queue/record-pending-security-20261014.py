import sys,json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
R=Path('C:/gecko_main');Q=R/'openclaw/application-queue';sys.path.insert(0,str(R/'job-scout'));from google_tracker import GoogleTracker,_a1,_col
scope=json.loads((Q/'batch-rows2-100-20261014-snapshot.json').read_text(encoding='utf-8'));original={str(r['Scout ID']):r for n,r in scope['rows']};ids=['2241','2242','2252'];t=GoogleTracker();t.discover_workbook(required=('Job List',));tab=t.tab('Job List');formula=t.tab('Job List',value_render_option='FORMULA');assert tab.headers==formula.headers and tab.sheet_id==formula.sheet_id;updates=[];before={};expected={}
for j in ids:
 e=json.loads((Q/j/'submission-result.json').read_text(encoding='utf-8'));assert e['security_verification'] and e['outcome']=='pending_user';hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1;n,r=hits[0];assert 2<=n<=100
 for k in ['Company','Job Title','Job URL','Resume Link']:assert r.get(k)==original[j].get(k)
 assert not r.get('Applied');before[j]={'row':n,'values':r};expected[j]={'Notes':'Application pending: '+e['reason']+'\nApplication link: '+e['application_url'],'Last Updated':e['timestamp']+' | Gecko / OpenClaw application'};fr=next(rr for nn,rr in formula.rows if nn==n)
 for field,value in expected[j].items():
  assert not str(fr.get(field,'')).startswith('=');col=tab.headers[field]
  for rn,raw in formula.raw_rows.items():
   for cn,v in enumerate(raw,1):assert not(isinstance(v,str) and 'ARRAYFORMULA' in v.upper() and n>=rn and col>=cn)
  updates.append({'range':_a1(tab.title,f'{_col(col)}{n}'),'values':[[value]]})
audit=Q/'pending-security-tracker-20261014.json';audit.write_text(json.dumps({'before':before,'updates':updates},indent=2),encoding='utf-8');t.api.values().batchUpdate(spreadsheetId=t.config.spreadsheet_id,body={'valueInputOption':'RAW','data':updates}).execute();after=t.tab('Job List');assert after.headers==tab.headers
for j in ids:
 n=before[j]['row'];r=next(rr for nn,rr in after.rows if nn==n);assert str(r['Scout ID'])==j
 for k,v in before[j]['values'].items():assert r.get(k)==expected[j].get(k,v)
print(json.dumps({'verified_pending_security_ids':ids,'Apply?_unchanged':True,'Notes_and_Last_Updated_written':True}))
