"""Finish source-backed geography/pay corrections and independent readback."""
import sys,json
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('C:/gecko_main');HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8')
import scout,sheet_sync
from google_tracker import GoogleTracker,Config,resume_approval_value
from storage import JobStore,DEFAULT_DB
from normalize import clean_text,posting_identity
from firecrawl_discovery import extract_listing
from description_columns import description_column
from description_retrieval import description_is_sufficient
from preferences import load_preferences
from hard_filters import deterministic_filter
from run_gecko import run_lock
from sqlite_daily_report import backup_workspace
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
with run_lock():
    sheet_sync.sync();tracker=GoogleTracker()
    with JobStore(DEFAULT_DB) as store:
        job=store.get(2885);page=json.loads((HERE/'maximus-description.json').read_text(encoding='utf-8'))
        raw,_,_=extract_listing(page,'https://www.adzuna.com/details/5937216525')
        assert raw and raw.company==job.company and raw.title==job.title
        assert raw.metadata['jobLocation']['address']['addressRegion']=='UT'
        assert resume_approval_value(raw.location,job.work_arrangement,'')=='Yes'
        before=job.location
        store.connection.execute('UPDATE jobs SET location=? WHERE id=? AND location=? AND source_job_id=?',(raw.location,2885,before,'5937216525'))
        store.connection.commit();job=store.get(2885)
        job.description=job.enriched_description
        assert description_is_sufficient(job.description) and deterministic_filter(job,load_preferences())[0]
        scout.sync_tracker(store,jobs=[job],append_only=True,discovery_notes={2885:'Original JobPosting explicitly identifies Salt Lake City, UT, US (postal code 84101). Full description verified. Adzuna pay is an estimate, not confirmed employer base salary. No resume or application started.'},audit_dir=HERE/'maximus-audit')
        # Restore estimate provenance for the earlier Carhartt test result.
        carhartt=store.get(2883)
        if carhartt and carhartt.company=='Carhartt' and carhartt.source_job_id=='5934060747':
            store.connection.execute('UPDATE jobs SET salary=? WHERE id=? AND salary=?',('Estimated $96,113',2883,carhartt.salary));store.connection.commit()
    tab=tracker.scout();matches=[r for _,r in tab.rows if str(r.get('Scout ID'))=='2883']
    if len(matches)==1 and matches[0]['Company']=='Carhartt':
        row=matches[0];note='Adzuna marked the $96,113 salary as a provider estimate; the verified employer posting did not state base pay.'
        if note not in row.get('Notes',''):
            tracker.dashboard_edit(row,{'Notes':row.get('Notes','').rstrip()+'\n'+note})
    sync=sheet_sync.sync();remote=GoogleTracker(config=Config.from_environment());live=remote.scout()
    rows={str(r.get('Scout ID')):r for _,r in live.rows}
    row=rows['2885'];target=description_column(live.headers,'Gecko')
    assert row['Company']=='Maximus' and 'UT' in row['Location'] and description_is_sufficient(row[target])
    report=json.loads((HERE/'results.json').read_text(encoding='utf-8'))
    if 2885 not in report['new_job_ids']:
        report['new_job_ids'].append(2885);report['new_unique_jobs']+=1
        report['verified_jobs'].append({'id':2885,'company':row['Company'],'title':row['Job Title'],'found_using':'Gecko','url':row['Job URL'],'description_column':target,'description_characters':len(row[target])})
    for item in report['ordinary']:
        if item['id']==2885:item.update(included=True,reason='Original JobPosting proves Salt Lake City, UT; full description verified')
    for item in report['verified_jobs']:
        actual=rows[str(item['id'])]
        assert actual['Company']==item['company'] and posting_identity(actual['Job URL'])==posting_identity(item['url'])
        assert description_is_sufficient(actual[item['description_column']])
    report['status']='ordinary_verified_firecrawl_paused';report['new_credits_accounted_this_request']=report['credit_usage']['total_credits_accounted']-24
    report['final_sync']=sync;report['backup_after']=backup_workspace();report['finished_at']=datetime.now(timezone.utc).isoformat()
    report['limitations']=['Firecrawl API HTTP 403 paused extraction; only 1 of 16 base query groups completed. No retries of the failed request.', 'Five regional Launch Potato postings have distinct employer job IDs; they may represent regional variants of the same role.']
    (HERE/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    lines=['# Full Gecko search — October 22, 2026','',f"{report['new_unique_jobs']} new listings saved and independently verified with full Gecko descriptions. Ordinary-provider search completed with inaccessible connectors reported; Firecrawl paused early on API HTTP 403 (1 of 16 query groups completed). No resumes or applications.",'','Four-day posting window; contracts included; posted starting annual base above $120,000 excluded. Estimates remain identified in Notes. Five Launch Potato rows have distinct regional posting IDs and may represent variants of one role.','','| ID | Employer | Role |','| --- | --- | --- |']
    for item in sorted(report['verified_jobs'],key=lambda x:x['id']):lines.append(f"| {item['id']} | {item['company']} | [{item['title'].replace('|','/')} ]({item['url']}) |")
    lines+=['',f"Credits accounted: {report['new_credits_accounted_this_request']} for this request; 69 total today / 200 cap. Provider confirmed today: 12; conservatively reserved/estimated: 57. Unresolved billing remains reserved."]
    (HERE/'results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'verified':True,'new_listings':report['new_unique_jobs'],'credits_this_request':report['new_credits_accounted_this_request'],'credits_today':69,'firecrawl':'paused HTTP 403','backup':report['backup_after']}))
