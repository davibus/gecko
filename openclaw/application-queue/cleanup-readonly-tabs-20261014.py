from pathlib import Path
import json
from native_browser import call,request
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');scope=set(json.loads((Q/'batch-rows2-100-20261014-approved-ids.json').read_text()));tabs=call(['tabs']).get('tabs',[]);closed=[]
for t in tabs:
 label=t.get('label','')
 if not label.startswith('batch20261014-'):continue
 j=label[len('batch20261014-'):]
 if j not in scope or j=='2240':continue
 f=Q/j/'browser-inspection-20261014.json'
 if not f.exists():continue
 inspection=json.loads(f.read_text());assert inspection['id']==j
 request('DELETE','/tabs/'+t['targetId']);closed.append({'id':j,'targetId':t['targetId'],'url':t['url']})
(Q/'browser-readonly-tab-cleanup-20261014.json').write_text(json.dumps(closed,indent=2));print(json.dumps({'closed_own_readonly_tabs':len(closed),'application_drafts_preserved':True}))
