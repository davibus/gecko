import json,sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
R=Path('C:/gecko_main');Q=R/'openclaw/application-queue';sys.path.insert(0,str(R/'job-scout'))
from google_tracker import GoogleTracker,_a1,_col
holds={'2225': ('The exact employer application URL redirects to Vasion current openings with not_found=true. Senior Growth Marketing Manager is not among the displayed current openings. The archived posting is no longer available for submission.', 'https://apply.workable.com/vasion/j/B079EF2975'), '559': ('The recovered live employer posting is Senior Paid Media Manager, while the tracker and existing tailored resume identify Paid Media Manager. Confirm the revised role and matching resume before submission.', 'https://jobs.lever.co/pattern/7b031c0b-5479-46f7-a063-7b24bf57876f')}
original={str(r['Scout ID']):r for n,r in json.loads((Q/'batch-rows2-100-20261014-snapshot.json').read_text())['rows']};t=GoogleTracker();tab=t.tab('Job List');formula=t.tab('Job List',value_render_option='FORMULA');assert tab.headers==formula.headers and tab.sheet_id==formula.sheet_id;updates=[];before={};expected={};now=datetime.now(ZoneInfo('America/Denver')).isoformat()
for j,(reason,url) in holds.items():
 assert j in original;hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1;n,r=hits[0];assert 2<=n<=100
 for k in ['Company','Job Title','Job URL','Resume Link']:assert r.get(k)==original[j].get(k)
 if str(r.get('Applied','')).strip().lower() not in ['','no','false']:continue
 before[j]={'row':n,'values':r};expected[j]={'Apply?':'No','Notes':'Held: '+reason+'\nApplication link: '+(url or r['Job URL']),'Last Updated':now+' | Gecko / OpenClaw application review'};fr=next(rr for nn,rr in formula.rows if nn==n)
 for field,value in expected[j].items():
  assert not str(fr.get(field,'')).startswith('=');col=tab.headers[field]
  for rn,raw in formula.raw_rows.items():
   for cn,v in enumerate(raw,1):assert not(isinstance(v,str) and 'ARRAYFORMULA' in v.upper() and n>=rn and col>=cn)
  updates.append({'range':_a1(tab.title,f'{_col(col)}{n}'),'values':[[value]]})
(Q/'new-employer-status-holds-20261014.json').write_text(json.dumps({'before':before,'updates':updates},indent=2),encoding='utf-8')
if updates:t.api.values().batchUpdate(spreadsheetId=t.config.spreadsheet_id,body={'valueInputOption':'RAW','data':updates}).execute()
after=t.tab('Job List');assert after.headers==tab.headers
for j in before:
 n=before[j]['row'];r=next(rr for nn,rr in after.rows if nn==n);assert str(r['Scout ID'])==j
 for k,v in before[j]['values'].items():assert r.get(k)==expected[j].get(k,v)
 q=Q/j;e=json.loads((q/'submission-result.json').read_text(encoding='utf-8-sig')) if (q/'submission-result.json').exists() else {};e.update(job_id=j,company=r['Company'],job_title=r['Job Title'],outcome='held',security_verification=False,reason=holds[j][0],application_url=holds[j][1] or r['Job URL'],timestamp=now,tracker_readback_result={'row':n,'Applied':r['Applied'],'Apply?':r['Apply?'],'Notes':r['Notes'],'verified':True});(q/'submission-result.json').write_text(json.dumps(e,indent=2),encoding='utf-8')
print(json.dumps({'verified_held_ids':list(before),'Applied_unchanged':True,'unrelated_fields_unchanged':True}))
