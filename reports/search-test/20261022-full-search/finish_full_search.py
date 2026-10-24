"""Resume this search's saved ordinary candidates, then run budgeted Firecrawl."""
import sys,json,re
from pathlib import Path
from datetime import datetime,timezone,timedelta
ROOT=Path('C:/gecko_main');HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
import scout,sheet_sync,unified_search
from google_tracker import GoogleTracker,Config,resume_approval_value
from storage import JobStore,DEFAULT_DB
from preferences import load_preferences
from hard_filters import deterministic_filter
from firecrawl_state import config,History
from sources.firecrawl import FirecrawlClient
from firecrawl_discovery import run_discovery,extract_listing
from normalize import posting_identity
from url_resolution import best_job_url
from job_extraction import markdown,sheet_description
from description_columns import description_value,description_column
from description_retrieval import description_is_sufficient
from run_gecko import run_lock
from sqlite_daily_report import backup_workspace
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
settings=config();settings.update(enabled=True,daily_enabled=True,daily_soft_credits=200,daily_hard_credits=200)
history=History(settings=settings);client=FirecrawlClient(history=history,settings=settings)
report={'started_at':datetime.now(timezone.utc).isoformat(),'ordinary_baseline_max_id':2884,'ordinary':[],'resumes_generated':0,'applications_submitted':0}
with run_lock():
    initial=sheet_sync.sync();report['backup_before']=backup_workspace()
    tracker=GoogleTracker();remote=GoogleTracker(config=Config.from_environment());tab=remote.scout()
    with JobStore(DEFAULT_DB) as store:
        # The one Adzuna snippet was retrieved once within this same credit cap.
        saved=json.loads((HERE/'maximus-description.json').read_text(encoding='utf-8'))
        raw,_,_=extract_listing(saved,'https://www.adzuna.com/details/5937216525')
        j=store.get(2885)
        assert raw and raw.company==j.company and raw.title==j.title
        j.original_description=j.original_description or j.description
        j.enriched_description=markdown(raw.description);j.enriched_source_url='https://www.adzuna.com/details/5937216525'
        j.enrichment_status='succeeded';j.enrichment_error='';j.enriched_at=datetime.now(timezone.utc).isoformat()
        store.save_enrichment(j)
        rejected=remote.rejected_jobs_index();eligible=[]
        # These exact IDs were allocated by this search's two interrupted attempts.
        for job_id in range(2885,2923):
            job=store.get(job_id)
            if not job:continue
            accepted,reason=deterministic_filter(job,load_preferences())
            if accepted and resume_approval_value(job.location,job.work_arrangement,'')!='Yes':
                accepted=False;reason='Location/remote eligibility needs review'
            if accepted and rejected.matches_job(job):accepted=False;reason='Permanent rejection history'
            full=max((job.description or '',job.enriched_description or ''),key=len)
            if accepted and not description_is_sufficient(full):accepted=False;reason='Full description needs review'
            item={'id':job.id,'company':job.company,'title':job.title,'source':job.source,'url':job.url,'included':accepted,'reason':reason}
            report['ordinary'].append(item)
            if accepted:eligible.append(job.id)
        # Discard no records: excluded candidates remain in discovery storage.
        pending=unified_search._pending()
        assert set(pending['job_ids']).issubset(set(range(2885,2923))), 'Unrelated publication pending; preserve it for review'
        pending['job_ids']=eligible
        unified_search._save(unified_search.PENDING,pending)
        (HERE/'ordinary-assessment.json').write_text(json.dumps(report['ordinary'],indent=2),encoding='utf-8')
        print(json.dumps({'ordinary_qualified':len(eligible),'ordinary_held':len(report['ordinary'])-len(eligible),'usage_before_firecrawl':history.usage()}),flush=True)
        # Publish the verified ordinary results independently of paid availability.
        report['ordinary_publication']=unified_search.deliver(store,remote=remote)
        sheet_sync.sync()
        print('Ordinary qualified jobs published and read back; Firecrawl search starting',flush=True)
        smart=run_discovery(store,load_preferences(),history=history,client=client,tracker=remote,publish=False)
        report['firecrawl']=smart
        print('FIRECRAWL '+json.dumps(smart),flush=True)
        # Outbox publication retries reuse stored responses and spend no credits.
        pending=unified_search._pending()
        pending['job_ids']=list(dict.fromkeys(pending['job_ids']+smart.get('new_job_ids',[])))
        unified_search._save(unified_search.PENDING,pending)
        report['firecrawl_publication']=unified_search.deliver(store,remote=remote)
        report['sync']=sheet_sync.sync()
        final=remote.scout();by_id={str(r.get('Scout ID')):r for _,r in final.rows}
        ids=list(dict.fromkeys(eligible+smart.get('new_job_ids',[])))
        report['verified_jobs']=[]
        for job_id in ids:
            job=store.get(job_id);row=by_id[str(job_id)]
            assert row['Company']==job.company and posting_identity(row['Job URL'])==posting_identity(best_job_url(job))
            target=description_column(final.headers,job.found_using or 'Gecko')
            assert description_is_sufficient(row.get(target,'')),(job_id,target)
            accepted,reason=deterministic_filter(job,load_preferences())
            assert accepted,(job_id,reason)
            report['verified_jobs'].append({'id':job_id,'company':job.company,'title':job.title,'found_using':job.found_using,'url':row['Job URL'],'description_column':target,'description_characters':len(row[target])})
        report['new_job_ids']=ids;report['new_unique_jobs']=len(ids)
        report['credit_usage']=history.usage();assert report['credit_usage']['total_credits_accounted']<=200
        report['status']='verified';report['finished_at']=datetime.now(timezone.utc).isoformat();report['backup_after']=backup_workspace()
        (HERE/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        lines=['# Full Gecko search — October 22, 2026','','Four-day window; contracts included; starting annual base over $120,000 excluded. All listed jobs and their source-specific full-description fields were independently verified. No resumes/applications run.','','| ID | Employer | Role | Found using |','| --- | --- | --- | --- |']
        for row in report['verified_jobs']:lines.append(f"| {row['id']} | {row['company']} | [{row['title'].replace('|','/')} ]({row['url']}) | {row['found_using']} |")
        lines+=['', 'Credits accounted today: '+str(report['credit_usage']['total_credits_accounted'])+' / 200; confirmed: '+str(report['credit_usage']['provider_confirmed_credits'])+'; reserved/estimated: '+str(report['credit_usage']['estimated_or_reserved_credits'])+'.']
        (HERE/'results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print('COMPLETE '+json.dumps({'new_jobs':len(ids),'ids':ids,'usage':report['credit_usage']}),flush=True)
