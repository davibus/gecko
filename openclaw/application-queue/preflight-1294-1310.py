import sys,json
from pathlib import Path
ROOT=Path('C:/gecko_main');sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'job-scout'))
from prepare_application_package import prepare,save_package,GoogleTracker,PackageBlocked
ids=['1294','1295','1296','1297','1298','1299','1301','1302','1303','1304','1305','1306','1308','1309','1310'];live=GoogleTracker();tabs=live.discover_workbook(required=(live.config.scout_tab,'Rejected Jobs'));tab=live.tab(live.config.scout_tab);rejected=live.rejected_jobs_index()
class SnapshotTracker:
 config=live.config
 def discover_workbook(self,required):
  assert all(x in tabs for x in required);return tabs
 def tab(self,name):
  assert name==self.config.scout_tab;return tab
 def rejected_jobs_index(self):return rejected
t=SnapshotTracker();result=[]
(ROOT/'openclaw/application-queue/batch-1294-1310-tracker-snapshot.json').write_text(json.dumps({'headers':tab.headers,'rows':[(n,r) for n,r in tab.rows if str(r.get('Scout ID')) in ids]},indent=2),encoding='utf-8')
print('Live headers '+json.dumps(tab.headers),flush=True)
for j in ids:
 hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1
 n,r=hits[0];summary={k:r.get(k,'') for k in ['Company','Job Title','Job URL','Applied','Apply?','Resume Created','Location','Resume Link']};print(json.dumps({'id':j,'row':n,**summary}),flush=True)
 try:
  p=prepare(t,job_id=j,physical_row=None,approved_job_id=j);save_package(p);result.append({'id':j,'outcome':'prepared','row':n,**summary});print('Prepared '+j,flush=True)
 except PackageBlocked as e:result.append({'id':j,'outcome':'blocked','blocker':e.code,'row':n,**summary});print('BLOCKED '+j+': '+e.code,flush=True)
 (ROOT/'openclaw/application-queue/batch-1294-1310-preflight.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
(ROOT/'openclaw/application-queue/batch-1294-1310-preflight.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
