import sys,json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
R=Path('C:/gecko_main');Q=R/'openclaw/application-queue';sys.path.insert(0,str(R/'job-scout'))
from google_tracker import GoogleTracker,_a1,_col
j='2241';q=Q/j;p=json.loads((q/'application-package.json').read_text(encoding='utf-8'));e=json.loads((q/'submission-result.json').read_text(encoding='utf-8-sig'))
assert p['company']=='Filevine' and p['job_title']=='VP, Performance Marketing'
assert e['uploaded_filename']==Path(p['verified_resume_file_path']).name
receipt={'url':'https://jobs.lever.co/filevine/6a3a9f5b-c380-4c03-b6a8-eab125f176c2/thanks','heading':'Application submitted!','company':'Filevine','job_title':'VP, Performance Marketing','evidence':'Live in-chat browser tab 3, verified after Dave completed human security verification and submitted.'}
assert receipt['url']==p['company_application_url'].rstrip('/')+'/thanks'
(q/'confirmation-20261014.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
e.update(outcome='submitted',confirmation_url=receipt['url'],confirmation_text=receipt['heading'],security_verification=False,timestamp=datetime.now(ZoneInfo('America/Denver')).isoformat(),reason='Employer receipt confirmed after Dave completed human verification and submitted the completed application.')
(q/'submission-result.json').write_text(json.dumps(e,indent=2)+'\n',encoding='utf-8')
scope=json.loads((Q/'batch-rows2-100-20261014-snapshot.json').read_text(encoding='utf-8'));original={str(r['Scout ID']):r for n,r in scope['rows']};assert j in original
t=GoogleTracker();t.discover_workbook(required=('Job List',));tab=t.tab('Job List');formula=t.tab('Job List',value_render_option='FORMULA');assert tab.headers==formula.headers and tab.sheet_id==formula.sheet_id
hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1;n,r=hits[0];assert 2<=n<=100
for k in ['Company','Job Title','Job URL','Resume Link']:assert r.get(k)==original[j].get(k)
assert r.get('Applied','') in ('','X','x');fr=next(rr for nn,rr in formula.rows if nn==n)
expected={'Applied':'X','Notes':'Application submitted and employer receipt verified. Matching tailored resume uploaded. Human security verification completed by Dave. Confirmation: '+receipt['url'],'Last Updated':e['timestamp']+' | Gecko / OpenClaw application'};updates=[]
for field,value in expected.items():
 assert not str(fr.get(field,'')).startswith('=');col=tab.headers[field]
 for rn,raw in formula.raw_rows.items():
  for cn,v in enumerate(raw,1):assert not(isinstance(v,str) and 'ARRAYFORMULA' in v.upper() and n>=rn and col>=cn)
 updates.append({'range':_a1(tab.title,f'{_col(col)}{n}'),'values':[[value]]})
audit={'job_id':j,'before':r,'updates':updates};(q/'tracker-write-audit-20261014.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
t.api.values().batchUpdate(spreadsheetId=t.config.spreadsheet_id,body={'valueInputOption':'RAW','data':updates}).execute();after=t.tab('Job List');assert after.headers==tab.headers
rr=next(rr for nn,rr in after.rows if nn==n);assert str(rr['Scout ID'])==j
for k,v in r.items():assert rr.get(k)==expected.get(k,v),'Unexpected field changed: '+k
e['tracker_readback_result']={'tab':'Job List','row':n,'Applied':'X','Notes':rr['Notes'],'Last Updated':rr['Last Updated'],'verified':True};(q/'submission-result.json').write_text(json.dumps(e,indent=2)+'\n',encoding='utf-8');print(json.dumps(e['tracker_readback_result']))
