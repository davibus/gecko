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
routes={'2234':'https://job-boards.greenhouse.io/goatgroup/jobs/4739429005','2232':'https://jobs.ashbyhq.com/netboxlabs/0fd98e8a-54f6-4109-ae6c-22f97db450bc','2231':'https://jobs.ashbyhq.com/fieldguide/75c958a4-fe53-458b-b0cf-9e8400639f60'}
for j,url in routes.items():
 assert j in ids
 hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==j];assert len(hits)==1
 n,r=hits[0];assert 2<=n<=100 and r['Apply?'].strip().lower()=='yes'
 try:
  p=prepare(t,job_id=j,physical_row=None,approved_job_id=j,company_url=url);save_package(p);print('Prepared official employer '+j,flush=True)
 except PackageBlocked as e:print('BLOCKED '+j+': '+e.code,flush=True)
