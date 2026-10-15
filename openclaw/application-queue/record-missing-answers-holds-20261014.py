import json,sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
R=Path('C:/gecko_main');Q=R/'openclaw/application-queue';sys.path.insert(0,str(R/'job-scout'))
from google_tracker import GoogleTracker,_a1,_col
holds={}
for j,reason in {'2231': 'Awaiting full legal name and confirmation of audit/advisory/CPA practitioner experience. U.S. remote work is allowed; a draft with the matching resume is preserved in the in-chat browser.', '2237': 'Awaiting a factual subscription-launch example and subscriber-acquisition channel experience. A draft with the matching resume is preserved in the in-chat browser.', '703': 'Awaiting confirmation of at least three years of product marketing specifically for B2B SaaS. Demand-generation experience alone does not answer this requirement.', '707': 'Awaiting confirmation of measurable content results in both traditional SEO and AI-powered search, and availability to start.', '710': 'Awaiting full legal name and a concrete autonomous marketing/sales AI workflow example with actual tools. Electronic signature and reference-investigation authorization also require applicant review before acceptance.', '722': 'Awaiting confirmation of the latest company where Dave owned growth and the core metrics he owned there.'}.items():
 p=json.loads((Q/j/"application-package.json").read_text());url=p["company_application_url"];url=url.rstrip("/")+("/application" if "ashbyhq" in url else "/apply");holds[j]=(reason,url)
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
(Q/'missing-answers-held-reasons-20261014.json').write_text(json.dumps({'before':before,'updates':updates},indent=2),encoding='utf-8')
if updates:t.api.values().batchUpdate(spreadsheetId=t.config.spreadsheet_id,body={'valueInputOption':'RAW','data':updates}).execute()
after=t.tab('Job List');assert after.headers==tab.headers
for j in before:
 n=before[j]['row'];r=next(rr for nn,rr in after.rows if nn==n);assert str(r['Scout ID'])==j
 for k,v in before[j]['values'].items():assert r.get(k)==expected[j].get(k,v)
 q=Q/j;e=json.loads((q/'submission-result.json').read_text(encoding='utf-8-sig')) if (q/'submission-result.json').exists() else {};e.update(job_id=j,company=r['Company'],job_title=r['Job Title'],outcome='held',security_verification=False,reason=holds[j][0],application_url=holds[j][1] or r['Job URL'],timestamp=now,tracker_readback_result={'row':n,'Applied':r['Applied'],'Apply?':r['Apply?'],'Notes':r['Notes'],'verified':True});(q/'submission-result.json').write_text(json.dumps(e,indent=2),encoding='utf-8')
print(json.dumps({'verified_held_ids':list(before),'Applied_unchanged':True,'unrelated_fields_unchanged':True}))
