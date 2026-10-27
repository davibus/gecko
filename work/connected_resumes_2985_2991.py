"""Bounded connected-agent run: one reviewed resume, private upload, verified completion at a time."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback
from datetime import datetime, timezone
from dataclasses import replace
from unittest.mock import patch

ROOT=Path('C:/gecko_main')
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'job-scout')]
sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
import gecko_v2 as v2
import generate_apply_queue as queue
import resume_performance as perf
import resume_delivery
from google_tracker import GoogleTracker,Config,load_environment,_col
from storage import DEFAULT_DB
from run_gecko import run_lock
from word_validation_client import word_session
from resume_visual_review import review
from zoneinfo import ZoneInfo

OUT=Path(os.environ.get('GECKO_CONNECTED_REPORT',str(ROOT/'reports/resume-connected-2985-2991')))
IDS=tuple(int(x) for x in os.environ.get('GECKO_CONNECTED_IDS','2985 2986 2987 2988 2989 2990 2991').split())
OUT.mkdir(exist_ok=True)
load_environment()

def save(name,value):
    path=OUT/name;temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    temporary.replace(path)

def state(stage,ident=None,**extra):
    value={'stage':stage,'id':ident,'at':datetime.now(timezone.utc).isoformat(),**extra}
    save('status.json',value);print(json.dumps(value,ensure_ascii=True,default=str),flush=True)

def wait_file(path,phase):
    with perf.phase(phase):
        while not path.exists():time.sleep(.4)
    return json.loads(path.read_text(encoding='utf-8-sig'))

def exact_row(remote,ident):
    tab=remote.scout()
    hits=[(r,d) for r,d in tab.rows if str(d.get('Scout ID',''))==str(ident)]
    if len(hits)!=1:raise ValueError(f'Expected one primary Sheet row for ID {ident}; found {len(hits)}')
    return tab,*hits[0]

def validate_reviewed_inputs(spec,item):
    from description_columns import description_value
    if spec.get('source_sha256')!=v2.source_fingerprint():
        raise ValueError('Master changed since connected tailoring review; fresh factual review required')
    actual=hashlib.sha256(description_value(item.fields).encode('utf-8')).hexdigest()
    if spec.get('description_sha256')!=actual:
        raise ValueError('Job description changed since connected tailoring review; fresh tailoring required')

def validate_reviewed_plan(spec,plan):
    expected={str(v2.MASTER.relative_to(ROOT)):spec['source_sha256']}
    if plan['source_sha256']!=expected:
        raise ValueError('Master changed during plan creation; fresh review required')

def main():
    results=[]
    batch_started=datetime.now(timezone.utc)
    if not (OUT/'batch-clock.json').exists():save('batch-clock.json',{'started_at':batch_started.isoformat()})
    with perf.batch() as metrics,word_session():
        batch_before=metrics.snapshot()
        for ident in IDS:
            before=metrics.snapshot();started=time.perf_counter()
            started_at=datetime.now(timezone.utc).isoformat()
            earlier=OUT/f'input-{ident}.json'
            prior_result=OUT/f'result-{ident}.json'
            if earlier.exists() and prior_result.exists():
                prior=json.loads(prior_result.read_text(encoding='utf-8'))
                if prior.get('status')=='blocked':
                    save(f'prior-result-{ident}-{datetime.now(timezone.utc).strftime("%H%M%S%f")}.json',prior)
                    started_at=json.loads(earlier.read_text(encoding='utf-8'))['started_at']
            try:
                remote=GoogleTracker(config=Config.from_environment())
                tab,row,data=exact_row(remote,ident)
                company=data['Company']
                if queue.resume_already_created(data.get('Resume Created')) or str(data.get('Resume Link') or '').strip():
                    prior_path=OUT/f'result-{ident}.json'
                    prior=json.loads(prior_path.read_text(encoding='utf-8')) if prior_path.exists() else {}
                    if prior.get('status')=='complete' and prior.get('link')==data.get('Resume Link'):
                        if resume_delivery.publish(Path(prior['resume']))!=prior['link']:
                            raise ValueError('Previously completed delivery changed; review required')
                        results.append(prior);state('prior completion verified without regeneration',ident,company=company)
                        continue
                    result={'id':ident,'company':company,'status':'skipped','reason':'Existing completion or Resume Link protected',
                            'link':data.get('Resume Link'),'elapsed_seconds':time.perf_counter()-started}
                    results.append(result);save(f'result-{ident}.json',result);state('skipped',ident,**result);continue
                snapshot=queue.read_queue(remote,eligible_scout_ids={ident})
                pending=[i for i in snapshot.pending if i.scout_id==ident]
                if len(pending)!=1:raise ValueError('Current canonical eligibility safeguards excluded this job: '+str(snapshot.decisions))
                item=pending[0]
                from resume_match import thresholds
                policy=thresholds()
                scores={'Match Score':policy['minimum_score'],'Responsibilities Match':policy['minimum_responsibilities_match'],
                        'Required Skills Match':policy['minimum_required_skills_match']}
                if any(float(data.get(k,-1))<floor for k,floor in scores.items()):raise ValueError('Current saved match scores do not pass all configured thresholds')
                save(f'input-{ident}.json',{'row':row,'record':data,'started_at':started_at})
                state('awaiting reviewed tailoring',ident,company=company)
                spec=wait_file(OUT/f'tailoring-{ident}.json','tailoring')
                if spec.get('blocker'):raise ValueError(spec['blocker'])
                original_create=v2.create_plan
                def connected_plan(listing,**kwargs):
                    plan=original_create(listing,defer_summary=True)
                    validate_reviewed_plan(spec,plan)
                    v2.set_reviewed_headline(plan,spec['headline'],spec['headline_rationale'])
                    if spec.get('tools_platforms'):
                        v2.set_reviewed_tools(plan,spec['tools_platforms'],spec['tools_rationale'])
                    plan['resume']['summary']=spec['summary']
                    plan['resume'].pop('summary_selection',None)
                    plan['resume']['codex_authored']=True
                    plan['resume']['codex_reviewed_summary_sha256']=hashlib.sha256(spec['summary'].encode()).hexdigest()
                    plan['review_notes'].append('Current connected Codex agent reviewed headline, summary and exact source accomplishment IDs: '+spec['factual_review'])
                    plan['resume']['selected_evidence_ids']=spec['selected_evidence_ids']
                    if spec.get('additional_evidence_ids'):
                        plan['resume']['additional_evidence_ids']=spec['additional_evidence_ids']
                    plan['resume']['selected_results_ids']=list(plan['resume']['relevant_metric_ids'])
                    used=set(plan['resume']['selected_evidence_ids'])|set(plan['resume']['selected_results_ids'])
                    for eid in plan['resume']['relevant_metric_ids']:
                        if eid not in used:plan['resume']['selected_evidence_ids'].append(eid)
                    v2.normalize_resume_format(plan);v2.verify_plan(plan)
                    save(f'agent-review-{ident}.json',{'spec':spec,'source_sha256':plan['source_sha256'],'listing_sha256':plan['listing_sha256']})
                    return plan
                state('generating and native Word validation',ident,company=company)
                generation_started=time.perf_counter()
                with run_lock(),patch.object(v2,'create_plan',side_effect=connected_plan),patch.dict(os.environ,{'GECKO_AI_RUNNER':'connected_agent'}):
                    item=queue._refresh_item(remote,item)
                    validate_reviewed_inputs(spec,item)
                    artifacts=queue.generate(item,DEFAULT_DB,tracker=remote)
                generation_seconds=time.perf_counter()-generation_started
                context=artifacts.review_context;scratch=context['scratch'];qa=context['qa']
                state('fresh visual review',ident,company=company,resume=str(artifacts.resume),scratch=str(scratch),qa=qa)
                proof=review(artifacts.resume,scratch/'word-export.pdf',scratch,qa)
                artifacts=replace(artifacts,visual_review=proof)
                delivery_started=time.perf_counter()
                state('connected private Drive delivery',ident,company=company,resume=str(artifacts.resume),
                      filename=artifacts.resume.name,size=artifacts.resume.stat().st_size,sha256=resume_delivery.digest(artifacts.resume),
                      listing=str(artifacts.listing),scratch=str(scratch),generation_seconds=generation_seconds)
                wait_file(OUT/f'uploaded-{ident}.json','drive_delivery')
                url=resume_delivery.publish(artifacts.resume)
                delivery_seconds=time.perf_counter()-delivery_started
                state('canonical completion and hyperlink verification',ident,company=company,link=url)
                tracker_started=time.perf_counter()
                with run_lock(),perf.phase('tracker_sync'):
                    fresh_tab,fresh_row,fresh=exact_row(remote,ident)
                    from description_columns import description_value
                    if description_value(fresh)!=description_value(item.fields):raise ValueError('Primary job description changed during tailoring; completion stopped')
                    queue.record_success(item,artifacts,GoogleTracker())
                    verified_tab,verified_row,verified=exact_row(remote,ident)
                    today=datetime.now(ZoneInfo('America/Denver')).date().isoformat()
                    if (not queue.resume_already_created(verified.get('Resume Created')) or verified.get('Resume Created Date')!=today
                            or verified.get('Resume Link')!=url):raise ValueError('Independent marker/date/link readback failed')
                    link_range=f"'{verified_tab.title}'!{_col(verified_tab.headers['Resume Link'])}{verified_row}"
                    hyperlink=remote.api.get(spreadsheetId=remote.config.spreadsheet_id,ranges=[link_range],includeGridData=True,
                        fields='sheets(data(rowData(values(hyperlink))))').execute()
                    targets=[c.get('hyperlink') for s in hyperlink.get('sheets',[]) for g in s.get('data',[]) for r in g.get('rowData',[]) for c in r.get('values',[])]
                    if targets!=[url]:raise ValueError('Independent actual hyperlink target did not match verified Drive URL')
                result={'id':ident,'company':company,'status':'complete','link':url,'resume':str(artifacts.resume),
                        'started_at':started_at,'completed_at':datetime.now(timezone.utc).isoformat(),
                        'elapsed_seconds':(datetime.now(timezone.utc)-datetime.fromisoformat(started_at)).total_seconds(),'generation_seconds':generation_seconds,
                        'delivery_seconds':delivery_seconds,'tracker_seconds':time.perf_counter()-tracker_started,
                        'readback':{k:verified.get(k) for k in ('Scout ID','Company','Job Title','Resume Created','Resume Created Date','Resume Link')},
                        'hyperlink_range':link_range,'hyperlink_target':targets[0],'timings':metrics.delta(before)}
                results.append(result);save(f'result-{ident}.json',result);state('resume complete',ident,**result)
            except Exception as error:
                result={'id':ident,'company':locals().get('company',''),'status':'blocked','reason':str(error),
                        'elapsed_seconds':time.perf_counter()-started,'traceback':traceback.format_exc(),'timings':metrics.delta(before)}
                results.append(result);save(f'result-{ident}.json',result);state('blocked',ident,reason=str(error))
            save('results.json',results)
        results=[json.loads((OUT/f'result-{ident}.json').read_text(encoding='utf-8')) for ident in IDS]
        original=json.loads((OUT/'batch-clock.json').read_text(encoding='utf-8'))
        elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(original['started_at'])).total_seconds()
        save('batch-timings.json',{'started_at':original['started_at'],'overall_elapsed_seconds':elapsed,
             'resumed_processing_started_at':batch_started.isoformat(),'totals':metrics.delta(batch_before),'resumes':results})
    save('results.json',results);state('batch finished',results=results)

if __name__=='__main__':main()
