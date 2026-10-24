"""Publish exactly the 20 assessed Firecrawl jobs through the existing tracker writer."""
import sys,json
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
ROOT=Path('C:/gecko_main');P=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
import scout,sheet_sync
from models import JobListing
from storage import JobStore,DEFAULT_DB
from google_tracker import GoogleTracker,Config,resume_approval_value
from run_gecko import run_lock
from sqlite_daily_report import backup_workspace
from normalize import posting_identity
from deduplicate import find_duplicate
from service import _same_source_identity_conflicts
from description_columns import description_column
from description_retrieval import description_is_sufficient
from job_extraction import tracker_notes,sheet_description
from hard_filters import deterministic_filter
from preferences import load_preferences
from url_resolution import best_job_url,classify_url

scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
selected=[x for x in json.loads((P/'prepared.json').read_text(encoding='utf-8')) if x['selected']]
assert len(selected)==20
now=datetime.now(ZoneInfo('America/Denver'));date=now.date().isoformat()
report={'started_at':now.isoformat(),'discovery':'Firecrawl only; saved evidence, no provider searches during publication',
        'resumes_generated':0,'applications_submitted':0,'jobs':[]}
with run_lock():
    report['initial_sync']=sheet_sync.sync()
    report['backup_before']=backup_workspace()
    remote=GoogleTracker(config=Config.from_environment());tab=remote.scout()
    existing_by_id={str(v.get('Scout ID')):dict(v) for _,v in tab.rows if v.get('Scout ID')}
    (P/'tracker-before.json').write_text(json.dumps(existing_by_id,indent=2),encoding='utf-8')
    with JobStore(DEFAULT_DB) as store:
        primary_ids=[int(v) for v in existing_by_id if v.isdigit()]
        if primary_ids:store.observe_scout_id(max(primary_ids))
        rejection=remote.rejected_jobs_index();known=store.all();jobs=[];notes={}
        recovery=json.loads((P/'staged.json').read_text(encoding='utf-8')) if (P/'staged.json').exists() else {}
        for item in selected:
            key=item['candidate_key'];job=JobListing.from_dict(item['job']);doc=item['document']
            job.details=doc;job.found_using='Firecrawl';job.last_seen=date;job.date_discovered=date
            job.original_url=job.url
            official=item['application_url']
            job.authoritative_url=official;job.authoritative_url_confidence=100
            job.url_verification_status='verified';job.url_destination_type=classify_url(official)
            job.url_resolved_at=now.isoformat()
            job.source_links=[{'source':job.source,'source_job_id':job.source_job_id,'url':job.url},
                              {'source':'employer','source_job_id':'','url':official}]
            assert deterministic_filter(job,load_preferences())[0],(key,'preferences')
            assert resume_approval_value(job.location,job.work_arrangement,'')=='Yes',(key,'location')
            assert description_is_sufficient(job.description) and doc['status']=='complete'
            assert not rejection.matches_job(job),(key,'permanent rejection')
            if key in recovery:
                prior=store.get(recovery[key]);assert prior and posting_identity(prior.url)==posting_identity(job.url)
                job.id=prior.id
            else:
                duplicate=find_duplicate(job,[j for j in known if not _same_source_identity_conflicts(job,j)])
                assert duplicate is None,(key,'Existing identity discovered at final check',duplicate.id if duplicate else None)
                candidates={posting_identity(u) for u in [job.url,official]}
                assert not any(posting_identity(v.get('Job URL','')) in candidates for v in existing_by_id.values() if v.get('Job URL')),(key,'already in primary tracker')
                job.id=store.highest_scout_id()+1;store.observe_scout_id(job.id)
                store.save(job,job_id=job.id);store.save_job_document(job.id,doc)
                recovery[key]=job.id
                (P/'staged.json').write_text(json.dumps(recovery,indent=2),encoding='utf-8')
                known.append(job)
            jobs.append(job)
            restrictions=doc['fields'].get('remote_eligibility_restrictions') or ''
            salary=doc['fields'].get('salary') or {}
            note=(now.strftime('%m-%d-%Y | %-I:%M %p') if sys.platform!='win32' else now.strftime('%m-%d-%Y | %I:%M %p'))+' MDT | Firecrawl-only discovery. '
            note+='Original posting evidence: '+item['date_evidence']+'; '+str(item['raw']['date_posted'])+'. '
            note+='Full job description saved; existing tracker/rejection checks passed. No resume or application started.\n'
            note+='Direct application URL: '+official+'\n'
            if salary.get('evidence'):note+='Published pay evidence: '+salary['evidence']+'\n'
            note+=tracker_notes(doc)
            notes[job.id]=note
        (P/'publication-plan.json').write_text(json.dumps([{'id':j.id,'company':j.company,'title':j.title,'url':best_job_url(j),'description_characters':len(j.description)} for j in jobs],indent=2),encoding='utf-8')
        report['publication']=remote.upsert_scout(jobs,append_only=True,discovery_notes=notes,audit_dir=P/'publication-audit')
        assert report['publication'].get('readback_verified') and not report['publication'].get('skipped'),report['publication']
        report['sync']=sheet_sync.sync()
        after=remote.scout();rows={str(v.get('Scout ID')):v for _,v in after.rows if v.get('Scout ID')}
        for job in jobs:
            row=rows[str(job.id)];target=description_column(after.headers,'Firecrawl')
            assert row['Company']==job.company and row['Job Title']==job.title
            assert posting_identity(row['Job URL'])==posting_identity(best_job_url(job))
            assert row['Found Using']=='Firecrawl' and row.get(target)==sheet_description(job.description)
            assert row.get('Apply?')=='Yes'
            for field in ['Applied','Applied Date','Resume Created','Resume Link','Resume Created Date','Cover Letter','Cover Letter Link','Previous Applied Date','Personal priority']:
                assert not str(row.get(field) or '').strip(),(job.id,'Unexpected lifecycle value',field)
            report['jobs'].append({'id':job.id,'company':job.company,'title':job.title,'url':row['Job URL'],
                'description_characters':len(row[target]),'salary':row.get('Salary'),'company_website':row.get('Company Website'),
                'date_posted':row.get('Date Posted'),'arrangement':row.get('Work Arrangement'),'employment_type':row.get('Employment Type')})
        # Verify protected history on every pre-existing row after the append.
        protected=['Applied','Applied Date','Resume Created','Resume Link','Resume Created Date','Cover Letter','Cover Letter Link','Previous Applied Date','Personal priority','Previous Notes','Gecko Job Description','FireCrawl Job Description']
        for old_id,before in existing_by_id.items():
            assert old_id in rows,('Missing prior job',old_id)
            for field in protected:assert rows[old_id].get(field,'')==before.get(field,''),(old_id,'Existing field changed',field)
        sheet_sync.ensure_frozen_headers(remote)
        report['backup_after']=backup_workspace()
        report.update(status='verified',new_jobs=len(jobs),finished_at=datetime.now(ZoneInfo('America/Denver')).isoformat())
        (P/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)
