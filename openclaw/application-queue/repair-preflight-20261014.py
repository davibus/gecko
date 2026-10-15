import sys,json
from pathlib import Path
ROOT=Path('C:/gecko_main');sys.path.insert(0,str(ROOT/'scripts'));sys.path.insert(0,str(ROOT/'job-scout'))
from prepare_application_package import prepare,save_package,GoogleTracker,PackageBlocked
ids=json.loads((ROOT/'openclaw/application-queue/batch-rows2-100-20261014-approved-ids.json').read_text());live=GoogleTracker();tabs=live.discover_workbook(required=(live.config.scout_tab,'Rejected Jobs'));tab=live.tab(live.config.scout_tab);rejected=live.rejected_jobs_index()
class SnapshotTracker:
 config=live.config
 def discover_workbook(self,required):
  assert all(x in tabs for x in required);return tabs
 def tab(self,name):
  assert name==self.config.scout_tab;return tab
 def rejected_jobs_index(self):return rejected
t=SnapshotTracker();result=[]
import prepare_application_package as package_module
old_description_for=package_module.description_for
archive_map={x['id']:x['matching_descriptions'] for x in json.loads((ROOT/'openclaw/application-queue/batch-rows2-100-20261014-archive-map.json').read_text())}
def scoped_description(job_id,row,root):
 try:return old_description_for(job_id,row,root)
 except PackageBlocked as error:
  if error.code!='description_missing_or_ambiguous':raise
  candidates=archive_map.get(job_id,[])
  if len(candidates)!=1:raise
  c=candidates[0];path=Path(c['path']).resolve();assert path.parent==(root/'input/job-descriptions').resolve();text=path.read_text(encoding='utf-8-sig');assert row['Company'].casefold() in text[:2500].casefold() and row['Job Title'].casefold() in text[:2500].casefold();print('Resolved exact resume posting key '+job_id+' -> '+c['key'],flush=True);return path,c['key']
package_module.description_for=scoped_description
prior={x['id']:x for x in json.loads((ROOT/'openclaw/application-queue/batch-rows2-100-20261014-preflight.json').read_text())}
(ROOT/'openclaw/application-queue/batch-rows2-100-20261014-preflight-snapshot.json').write_text(json.dumps({'headers':tab.headers,'rows':[(n,r) for n,r in tab.rows if str(r.get('Scout ID')) in ids]},indent=2),encoding='utf-8')
print('Live headers '+json.dumps(tab.headers),flush=True)
for j in ids:
 if prior.get(j,{}).get('outcome')=='prepared' or prior.get(j,{}).get('blocker')=='already_applied':result.append(prior[j]);continue
 hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1
 n,r=hits[0];summary={k:r.get(k,'') for k in ['Company','Job Title','Job URL','Applied','Apply?','Resume Created','Location','Resume Link']};assert 2<=n<=100 and str(r.get('Apply?','')).strip().lower()=='yes';print(json.dumps({'id':j,'row':n,'company':r['Company'],'title':r['Job Title']}),flush=True)
 try:
  p=prepare(t,job_id=j,physical_row=None,approved_job_id=j,company_url=(archive_map.get(j,[{}])[0].get('authoritative_url') if len(archive_map.get(j,[]))==1 else None));save_package(p);result.append({'id':j,'outcome':'prepared','row':n,**summary});print('Prepared '+j,flush=True)
 except PackageBlocked as e:result.append({'id':j,'outcome':'blocked','blocker':e.code,'row':n,**summary});print('BLOCKED '+j+': '+e.code,flush=True)
 (ROOT/'openclaw/application-queue/batch-rows2-100-20261014-repaired-preflight.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
(ROOT/'openclaw/application-queue/batch-rows2-100-20261014-repaired-preflight.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
