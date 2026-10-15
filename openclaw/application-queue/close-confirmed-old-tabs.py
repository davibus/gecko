from native_browser import request
from pathlib import Path
import json,time
q=Path('/mnt/c/gecko_main/openclaw/application-queue');ids=['1294','1295','1296','1297','1298','1299','1301','1302','1303','1304','1305','1306','1308','1309','1310'];tabs=request('GET','/tabs')['tabs'];closed=[]
for j in ids:
 e=json.loads((q/j/'submission-result.json').read_text());assert e['outcome']=='submitted' and e['tracker_readback_result']['Applied']=='X'
 hits=[t for t in tabs if t.get('label')=='retry-'+j and t['url']==e['confirmation_url'] and t['title']=='Thank you for applying']
 assert len(hits)<=1
 for t in hits:
  request('DELETE','/tabs/'+t['targetId']);closed.append({'id':j,'targetId':t['targetId'],'confirmation_url':t['url']});print('Closed saved confirmation tab '+j,flush=True)
after=request('GET','/tabs')['tabs'];assert not any(t['targetId'] in [r['targetId'] for r in closed] for t in after);(q/'closed-confirmation-tabs-20261013.json').write_text(json.dumps(closed,indent=2));print('Preserved current drafts; closed '+str(len(closed))+' verified receipt tabs.',flush=True)
