"""Recheck the two contract listings after Dave opted contracts in."""
import sys,json,re
from pathlib import Path
from dataclasses import asdict
ROOT=Path('C:/gecko_main');HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8')
import scout,sheet_sync
from models import RawListing
from storage import JobStore,DEFAULT_DB
from google_tracker import GoogleTracker,Config
from run_gecko import run_lock
from preferences import load_preferences
from normalize import normalize
from hard_filters import deterministic_filter
from description_retrieval import description_is_sufficient
from deduplicate import find_duplicate
from service import discover_listings
from link_validation import LinkResult
from types import SimpleNamespace
from sqlite_daily_report import backup_workspace
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
selected={'5937236056':'Tek Ninjas','5937234879':'DivIHN Integration Inc'}
raws=[];evidence={}
for item in json.loads((HERE/'gecko-raw.json').read_text(encoding='utf-8')):
    if item['source_job_id'] not in selected:continue
    raw=RawListing(**item);page=json.loads((HERE/('contract-'+raw.source_job_id+'.json')).read_text(encoding='utf-8'))
    m=page['markdown'];assert page['metadata']['statusCode']==200 and raw.company in m and '# Field Marketing Manager - SLED' in m
    start=re.search(r'\[Apply for this job\]\(https?://[^)\n]+\)\s*',m)
    assert start
    raw.description=m[start.end():].split('[Apply for this job]',1)[0].strip()
    raw.employment_type='contract'
    assert description_is_sufficient(raw.description) and 'Location: Remote' in raw.description and 'Field Marketing Contractor' in raw.description
    assert deterministic_filter(normalize(raw),load_preferences())[0]
    raws.append(raw);evidence[raw.url]=LinkResult('valid',raw.url,raw.url,'Fresh job-specific Adzuna posting, full description and application link retrieved through Firecrawl',200)
assert len(raws)==2
validator=SimpleNamespace(require_verified=True,check=lambda job:evidence[job.url])
with run_lock():
    sheet_sync.sync();before_backup=backup_workspace();tracker=GoogleTracker();tab=tracker.scout();results=[]
    rejected=tracker.rejected_jobs_index()
    with JobStore(DEFAULT_DB) as store:
        ids=[int(r['Scout ID']) for _,r in tab.rows if str(r.get('Scout ID') or '').isdigit()]
        if ids:store.observe_scout_id(max(ids))
        added=[]
        for raw in raws:
            job=normalize(raw);duplicate=find_duplicate(job,store.all())
            if duplicate:
                results.append({'company':raw.company,'id':duplicate.id,'outcome':'already tracked'});continue
            summary=discover_listings([raw],store,require_content=True,preserve_existing=True,link_validator=validator,preferences=load_preferences(),rejected_jobs=rejected)
            results.append({'company':raw.company,'ids':summary.new_job_ids,'outcome':'added' if summary.added else 'excluded','decisions':summary.decisions})
            added.extend(summary.new_job_ids)
        if added:
            notes={i:'Contract jobs included at Dave’s request on October 22. Remote, short-term contract. Full source description retrieved and saved; no resume or application started. Similar SLED role appears through another staffing agency; employer identity is not confirmed.' for i in added}
            scout.sync_tracker(store,jobs=[store.get(i) for i in added],append_only=True,discovery_notes=notes,audit_dir=HERE/'contract-audit')
    sync=sheet_sync.sync();remote=GoogleTracker(config=Config.from_environment()).scout()
    for item in results:
        for job_id in item.get('ids',[]):
            rows=[r for _,r in remote.rows if str(r.get('Scout ID'))==str(job_id)]
            assert len(rows)==1
            r=rows[0];assert r['Company']==item['company'] and r['Employment Type']=='contract' and r['Work Arrangement']=='remote' and description_is_sufficient(r['Job Description'])
            item.update(tracker_id=job_id,description_characters=len(r['Job Description']))
    report={'verified':True,'results':results,'sync':sync,'backup_before':before_backup,'backup_after':backup_workspace()}
    (HERE/'contract-readback.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)
