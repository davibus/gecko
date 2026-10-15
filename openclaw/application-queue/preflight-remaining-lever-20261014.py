import sys,json
from pathlib import Path
R=Path('C:/gecko_main');Q=R/'openclaw/application-queue';sys.path.insert(0,str(R/'job-scout'))
from google_tracker import GoogleTracker
t=GoogleTracker();tab=t.tab('Job List');approved=set(json.loads((Q/'batch-rows2-100-20261014-approved-ids.json').read_text()));original={str(r['Scout ID']):r for n,r in json.loads((Q/'batch-rows2-100-20261014-snapshot.json').read_text())['rows']}
ids=['2243','692','703','704','707','708','710','714','716','721','722','847'];ready=[]
for j in ids:
 assert j in approved;hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1;n,r=hits[0];assert 2<=n<=100
 for k in ['Company','Job Title','Job URL','Resume Link']:assert r.get(k)==original[j].get(k)
 if str(r.get('Apply?','')).strip().lower()!='yes' or str(r.get('Applied','')).strip().lower() not in ['','no','false']:continue
 p=json.loads((Q/j/'application-package.json').read_text());assert p['application_preparation_approved'] and r['Resume Created'].strip().lower()=='x'
 inspection=json.loads((Q/j/'browser-inspection-20261014.json').read_text());assert p['job_title'] in inspection['page']['title'];ready.append(j)
(Q/'remaining-lever-preparation-20261014.json').write_text(json.dumps({'ids':ready,'rows':[(n,r) for n,r in tab.rows if str(r.get('Scout ID')) in ready]},indent=2));print(json.dumps({'freshly_approved_remaining_ids':ready}))
