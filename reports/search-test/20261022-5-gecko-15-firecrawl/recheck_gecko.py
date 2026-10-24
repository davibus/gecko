"""Recheck only the five saved Adzuna identities after arrangement repair."""
import sys,json,re,sqlite3
from pathlib import Path
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
ROOT=Path('C:/gecko_main'); HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8')
import scout
from models import RawListing
from normalize import normalize
from hard_filters import deterministic_filter
from preferences import load_preferences
from description_retrieval import retrieve_full_description,description_is_sufficient
from link_validation import DailyLinkValidator

scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
raws=[RawListing(**x) for x in json.loads((HERE/'gecko-raw.json').read_text(encoding='utf-8'))]
assert len(raws)==5 and {r.source_job_id for r in raws}=={'5937359468','5937236056','5937235836','5937235436','5937234879'}
prefs=load_preferences()

def inspect(raw):
    job=normalize(raw)
    outcome=retrieve_full_description(job,prefer_fuller=True)
    if outcome.status=='succeeded' and description_is_sufficient(outcome.description):
        raw.description=outcome.description
    # Two original provider snippets explicitly describe a three-month field
    # marketing contractor role. Unknown metadata must not bypass that evidence.
    contract=re.search(r'\bField Marketing Contractor\b',raw.description,re.I)
    if contract and not raw.employment_type:raw.employment_type='contract'
    job=normalize(raw); accepted,reason=deterministic_filter(job,prefs)
    item={'source_job_id':raw.source_job_id,'company':raw.company,'title':raw.title,
          'work_arrangement':job.work_arrangement,'employment_type':job.employment_type,
          'passed_filters':accepted,'filter_reason':reason,'full_description':description_is_sufficient(raw.description),
          'retrieval':asdict(outcome)}
    print(json.dumps({k:v for k,v in item.items() if k!='retrieval'}),flush=True)
    return raw,item

def main():
    inspected=list(ThreadPoolExecutor(max_workers=5).map(inspect,raws))
    validator=DailyLinkValidator();validator.require_verified=True
    eligible=[normalize(raw) for raw,item in inspected if item['passed_filters']]
    validator.check_existing(eligible,workers=5)
    from run_gecko import run_lock
    from storage import JobStore,DEFAULT_DB
    from google_tracker import GoogleTracker,Config
    from deduplicate import find_duplicate
    from service import discover_listings
    from sqlite_daily_report import backup_workspace
    import sheet_sync
    with run_lock():
        before=sheet_sync.sync();backup_before=backup_workspace()
        tracker=GoogleTracker();live=tracker.scout();rejected=tracker.rejected_jobs_index()
        with JobStore(DEFAULT_DB) as store:
            ids=[int(row['Scout ID']) for _,row in live.rows if str(row.get('Scout ID') or '').isdigit()]
            if ids:store.observe_scout_id(max(ids))
            added=[]
            for raw,item in inspected:
                job=normalize(raw)
                if not item['passed_filters']:item['outcome']='filtered';continue
                if rejected.matches_job(job):item['outcome']='rejection history';continue
                duplicate=find_duplicate(job,store.all())
                if duplicate:item.update(outcome='already tracked',scout_id=duplicate.id);continue
                verification=validator.check(job);item['availability']=asdict(verification)
                if verification.status!='valid':item['outcome']='needs availability review';continue
                summary=discover_listings([raw],store,require_content=True,preserve_existing=True,
                    link_validator=validator,preferences=prefs,rejected_jobs=rejected)
                item.update(outcome='added' if summary.added else 'not added',scout_ids=summary.new_job_ids)
                added.extend(summary.new_job_ids)
            if added:
                notes={i:'Bounded recheck of October 22 Gecko test. Explicit remote-work evidence recognized; description and employment terms checked. No resume or application requested.' for i in added}
                scout.sync_tracker(store,jobs=[store.get(i) for i in added],append_only=True,discovery_notes=notes,audit_dir=HERE/'remote-recheck-audit')
        after=sheet_sync.sync()
        remote=GoogleTracker(config=Config.from_environment()).scout()
        local=GoogleTracker().scout()
        for raw,item in inspected:
            if item['outcome']=='added':
                matches=[r for _,r in remote.rows if r.get('Job URL')==raw.url and r.get('Company')==raw.company]
                assert len(matches)==1,(raw.source_job_id,matches)
                record=matches[0];item['tracker_id']=record.get('ID') or record.get('Scout ID')
                assert record['Work Arrangement']=='remote',record
                assert any(r.get('Job URL')==raw.url and r.get('Work Arrangement')=='remote' for _,r in local.rows)
        backup_after=backup_workspace()
        result={'rows':[item for raw,item in inspected],'before_sync':before,'after_sync':after,'backup_before':backup_before,'backup_after':backup_after,'verified':True}
        (HERE/'remote-recheck.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
