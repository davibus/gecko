import sys,json
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('C:/gecko_main'); HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8')
import scout,sheet_sync
from google_tracker import GoogleTracker,Config
from storage import JobStore,DEFAULT_DB
from normalize import clean_text
from run_gecko import run_lock
from sqlite_daily_report import backup_workspace
from description_retrieval import description_is_sufficient
page=json.loads((HERE/'ait-firecrawl-evidence.json').read_text(encoding='utf-8'))
assert page['metadata']['statusCode']==200
markdown=page['markdown'];assert '# 656 - Product Marketing Manager, Staff' in markdown and '[AIT Global inc.]' in markdown
body='Job Title:'+markdown.split('**Job Title:',1)[1].split('[Apply for this job]',1)[0]
assert 'Preferred Qualifications' in body and description_is_sufficient(body)
original=next(x for x in json.loads((HERE/'gecko-raw.json').read_text(encoding='utf-8')) if x['source_job_id']=='5937235436')
with run_lock():
    sheet_sync.sync()
    tracker=GoogleTracker();tab=tracker.scout()
    matches=[(slot,row) for slot,row in tab.rows if str(row.get('Scout ID'))=='2880']
    assert len(matches)==1
    slot,row=matches[0]
    assert row['Company']=='AIT Global inc.' and row['Job URL']==original['url'] and row['Work Arrangement']=='remote'
    assert row['Job Description']==clean_text(original['description']),'Description changed since discovery; preserve it'
    tracker.dashboard_edit(row,{'Job Description':body})
    with JobStore(DEFAULT_DB) as store:
        job=store.get(2880);assert job.source_job_id=='5937235436'
        job.original_description=job.original_description or job.description
        job.original_url=job.original_url or job.url
        job.enriched_description=body;job.enriched_source_url='https://www.adzuna.com/details/5937235436'
        job.enrichment_status='succeeded';job.enrichment_error=''
        job.enriched_at=datetime.now(timezone.utc).isoformat(timespec='seconds')
        store.save_enrichment(job)
    sync=sheet_sync.sync()
    remote=GoogleTracker(config=Config.from_environment()).scout()
    actual=[r for _,r in remote.rows if str(r.get('Scout ID'))=='2880']
    assert len(actual)==1 and actual[0]['Job Description']==body and actual[0]['Work Arrangement']=='remote'
    result={'tracker_id':2880,'description_characters':len(body),'retrieved_via':'Firecrawl','found_using':'Gecko','verified':True,'sync':sync,'backup':backup_workspace()}
    (HERE/'ait-description-readback.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
