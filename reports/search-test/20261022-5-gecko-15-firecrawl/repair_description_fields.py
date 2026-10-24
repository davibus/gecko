"""Fill only blank description cells for the four newly discovered jobs."""
import sys,json
from pathlib import Path
ROOT=Path('C:/gecko_main');HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8')
import scout,sheet_sync
from google_tracker import GoogleTracker,Config
from storage import JobStore,DEFAULT_DB
from run_gecko import run_lock
from sqlite_daily_report import backup_workspace
from description_retrieval import description_is_sufficient
from job_extraction import sheet_description
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
expected={2876:'Coinbase',2877:'Upstart',2878:'AirGarage',2879:'PayNearMe'}
with run_lock():
    sheet_sync.sync();before_backup=backup_workspace()
    tracker=GoogleTracker();tab=tracker.scout();before={};changed=[]
    with JobStore(DEFAULT_DB) as store:
        for job_id,company in expected.items():
            matches=[row for _,row in tab.rows if str(row.get('Scout ID'))==str(job_id)]
            assert len(matches)==1,job_id
            row=matches[0];job=store.get(job_id)
            assert row['Company']==company and row['Job URL']==(job.authoritative_url or job.url)
            before[str(job_id)]=dict(row)
            description=sheet_description(max((job.description or '',job.enriched_description or ''),key=len))
            assert description_is_sufficient(description),job_id
            if row.get('Job Description','').strip():
                assert row['Job Description']==description,'Preserve a new user edit'
            else:
                tracker.dashboard_edit(row,{'Job Description':description});changed.append(job_id)
    sync=sheet_sync.sync()
    remote=GoogleTracker(config=Config.from_environment()).scout()
    local={str(r.get('Scout ID')):r for _,r in GoogleTracker().scout().rows}
    result=[]
    for job_id,company in expected.items():
        rows=[r for _,r in remote.rows if str(r.get('Scout ID'))==str(job_id)]
        assert len(rows)==1
        row=rows[0]
        assert description_is_sufficient(row['Job Description']) and local[str(job_id)]['Job Description']==row['Job Description']
        for field in ('Company','Job Title','Job URL','Resume Created','Resume Link','Applied','Applied Date','Notes','Previous Notes','Qualifies to Apply?'):
            assert row.get(field,'')==before[str(job_id)].get(field,''),(job_id,field)
        result.append({'job_id':job_id,'company':company,'description_characters':len(row['Job Description'])})
    ait=[r for _,r in remote.rows if str(r.get('Scout ID'))=='2880']
    assert len(ait)==1 and description_is_sufficient(ait[0]['Job Description'])
    result.append({'job_id':2880,'company':'AIT Global inc.','description_characters':len(ait[0]['Job Description']),'already_present':True})
    report={'verified':True,'changed_ids':changed,'jobs':result,'sync':sync,'backup_before':before_backup,'backup_after':backup_workspace()}
    (HERE/'description-fields-readback.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)
