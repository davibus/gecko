"""Authorized all-tracker resume run; canonical queue/render/writer, visual gate."""
import sys,os,json,time,hashlib,traceback
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
ROOT=Path('C:/gecko_main')
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'job-scout')]
sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
from google_tracker import GoogleTracker,Config,load_environment
from run_gecko import run_lock
import generate_apply_queue as queue
import gecko_v2
from storage import JobStore,DEFAULT_DB
from resume_match import assess,record,explanation,thresholds
from description_readiness import assess as readiness_assess
from link_validation import DailyLinkValidator
from hard_filters import deterministic_filter
from preferences import load_preferences
from codex_runner import CodexJsonClient
import codex_runner
load_environment()
bins=sorted((Path(os.environ['LOCALAPPDATA'])/'OpenAI/Codex/bin').glob('*/codex.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
if bins:os.environ['PATH']=str(bins[0].parent)+os.pathsep+os.environ['PATH']
os.environ['GECKO_AI_RUNNER']='codex'
# The existing runner/model/evidence checks are unchanged; allow normal latency.
class PatientClient(CodexJsonClient):
    def __init__(self,*args,**kwargs):kwargs.setdefault('timeout_seconds',600);super().__init__(*args,**kwargs)
    def complete(self,**kwargs):
        from resume_match import validate
        for attempt in range(2):
            answer=super().complete(**kwargs)
            if 'master_resume' not in kwargs['payload'] or 'jobs' not in kwargs['payload']:return answer
            try:
                for review in answer.get('reviews',[]):
                    item=next(j for j in kwargs['payload']['jobs'] if str(j['id'])==str(review['id']))
                    validate(review,item,kwargs['payload']['master_resume'])
                return answer
            except (ValueError,KeyError,StopIteration) as exc:
                if attempt:raise
                kwargs={**kwargs,'system':kwargs['system']+' Failed exact quotation validation: '+str(exc)+'. Use short contiguous verbatim source quotes; do not paraphrase or combine quotations. Reassess faithfully.','payload':{**kwargs['payload'],'invalid_preceding_response':answer}}
codex_runner.CodexJsonClient=PatientClient
OUT=ROOT/'reports/resume-batch-20261025';OUT.mkdir(exist_ok=True)
if (OUT/'run-status.json').exists():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    (OUT/('prior-run-status-'+stamp+'.json')).write_bytes((OUT/'run-status.json').read_bytes())
state={'started_at':datetime.now(timezone.utc).isoformat(),'completed':sorted(int(p.stem.split('-')[-1]) for p in OUT.glob('completed-*.json')),'blocked':[],'excluded':[],'visual_pending':None}
def save(name,value):
    path=OUT/name;temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)
def event(stage,ident=None,detail=''):
    state.update(stage=stage,current_id=ident,detail=detail,checked_at=datetime.now(timezone.utc).isoformat());save('run-status.json',state)
    print(json.dumps({'stage':stage,'id':ident,'detail':detail,'completed':len(state['completed']),'blocked':len(state['blocked'])}),flush=True)
def generator(item,db):
    event('description',item.scout_id,item.company+' / '+item.title)
    gecko_v2.validate_required_sources()
    # Every generation rereads the DOCX directly through the canonical planner.
    with JobStore(db) as store:
        job=store.get(item.scout_id)
        if job is not None and not queue._stored_job_matches_row(job,item):
            raise RuntimeError('Stored identity differs from exact live posting; description review required')
        if job is None:job=queue._job_from_sheet_row(item)
        allowed,reason=deterministic_filter(job,load_preferences())
        if not allowed:
            state['excluded'].append({'id':item.scout_id,'reason':reason})
            raise RuntimeError('Eligibility exclusion: '+reason)
        checked=validator.check(job)
        save('availability-'+str(item.scout_id)+'.json',checked.__dict__)
        proofs=[]
        for name in ('firecrawl-posting-','firecrawl-details-'):
            proof_path=OUT/(name+str(item.scout_id)+'.json')
            if proof_path.exists():proofs.append(json.loads(proof_path.read_text(encoding='utf-8')))
        proof=next((p for p in proofs if p.get('verified') and p.get('id')==item.scout_id),None)
        if checked.status!='valid' and not proof:raise RuntimeError('Posting availability '+checked.status+': '+checked.reason+'; Firecrawl exact-posting retrieval did not resolve this blocker')
        if proof:
            if queue._identity_text(proof['company'])!=queue._identity_text(item.company) or queue._identity_text(proof['title'])!=queue._identity_text(item.title):raise RuntimeError('Firecrawl proof identity differs from live posting')
            from normalize import posting_identity
            if posting_identity(proof.get('original_url') or proof['url'])!=posting_identity(item.job_url):raise RuntimeError('Firecrawl proof URL differs from live posting')
            if not proof.get('document',{}).get('status')=='complete':raise RuntimeError('Firecrawl full description incomplete')
            store.save_job_document(job.id,proof['document'])
            job.description=proof['document']['full_description_markdown']
            save('availability-'+str(item.scout_id)+'.json',{'status':'valid','method':'Firecrawl exact-posting recovery','url':item.job_url,'source_url':proof['url']})
        document=store.get_job_document(job.id)
        if isinstance(document,dict) and document.get('status')=='complete':
            fields=document.get('fields') or {}
            if fields.get('location'):job.location=fields['location']
            if fields.get('work_arrangement'):job.work_arrangement=fields['work_arrangement']
            if fields.get('application_fee_required') is True:
                state['excluded'].append({'id':item.scout_id,'reason':'Required application fee in verified full posting'})
                raise RuntimeError('Eligibility exclusion: verified full posting requires an application fee')
            if queue.resume_approval_value(job.location,job.work_arrangement,(item.fields or {}).get('Cost'))!='Yes':
                state['excluded'].append({'id':item.scout_id,'reason':'Verified full-posting location is not eligible: '+job.location+' / '+job.work_arrangement})
                raise RuntimeError('Eligibility exclusion: verified full-posting location is not eligible: '+job.location+' / '+job.work_arrangement)
        listing,attempts=queue._archive_listing(job,item,store)
    text=listing.read_text(encoding='utf-8-sig')
    meta=gecko_v2.listing_metadata(text,listing)
    if queue._identity_text(meta['company'])!=queue._identity_text(item.company) or queue._identity_text(meta['title'])!=queue._identity_text(item.title):
        raise RuntimeError('Archived description identity differs from exact live posting')
    job.description=queue._archived_description(text)
    if not queue.description_is_sufficient(job.description):raise RuntimeError('No job description: complete exact-posting text unavailable')
    # Recheck salary and all deterministic rules against newly retrieved content,
    # before any scoring or generation; never let an old snippet hide new pay.
    job.enriched_description=''
    allowed,reason=deterministic_filter(job,load_preferences())
    if not allowed:
        state['excluded'].append({'id':item.scout_id,'reason':reason})
        raise RuntimeError('Eligibility exclusion after full-description retrieval: '+reason)
    event('content review',item.scout_id,item.company)
    ready=readiness_assess([{'id':str(item.scout_id),'company':job.company,'title':job.title,'description':job.description}],client=PatientClient())[str(item.scout_id)]
    save('readiness-'+str(item.scout_id)+'.json',ready)
    if ready.get('value')!='Yes' or ready.get('status')!='reviewed':raise RuntimeError('Description review blocked: '+ready.get('reason',''))
    event('match review',item.scout_id,item.company)
    match=assess([record(job)],client=PatientClient())['job'];save('match-'+str(item.scout_id)+'.json',match)
    if not match.get('accepted'):
        if match.get('status')=='reviewed':state['excluded'].append({'id':item.scout_id,'reason':explanation(match)})
        raise RuntimeError(explanation(match))
    # Recover this run's already validated/visually reviewed artifact after a
    # transient writer failure. Never rebuild or overwrite it, and never touch X.
    request_path=OUT/('visual-request-'+str(item.scout_id)+'.json')
    approval_path=OUT/('visual-'+str(item.scout_id)+'.json')
    if request_path.exists() and approval_path.exists():
        request=json.loads(request_path.read_text(encoding='utf-8'));approval=json.loads(approval_path.read_text(encoding='utf-8'))
        final=Path(request['resume'])
        if final.is_file() and approval.get('approved') and approval.get('sha256')==request.get('sha256')==hashlib.sha256(final.read_bytes()).hexdigest():
            scratch=Path(request['qa']['native_validation']).parent
            plan_path=scratch/'tailoring-plan.json'
            plan=json.loads(plan_path.read_text(encoding='utf-8'))
            gecko_v2.verify_plan(plan)
            qa=gecko_v2.native_qa(plan,final,scratch)
            if qa['status']!='pass':raise RuntimeError('Recovered artifact failed fresh native validation: '+str(qa['issues']))
            approval_path.replace(OUT/('prior-visual-'+str(item.scout_id)+'-'+datetime.now(timezone.utc).strftime('%H%M%S%f')+'.json'))
            event('recovered validated artifact',item.scout_id,item.company)
            return queue.Artifacts(final,listing,True,attempts)
    event('tailoring and native Word validation',item.scout_id,item.company)
    return queue._finish_generation(item,listing,attempts)
def recorder(item,artifacts,tracker):
    import fitz
    from resume_performance import phase
    if artifacts.review_context:
        scratch=artifacts.review_context['scratch']
    else:
        meta=gecko_v2.listing_metadata(artifacts.listing.read_text(encoding='utf-8-sig'),artifacts.listing)
        scratch=ROOT/'scratch'/(meta['safe_company']+'+'+meta['job_number'])
    pdf=scratch/'word-export.pdf'
    # native_qa writes this PDF; require its independent native result first.
    qa=json.loads((scratch/'v2-qa.json').read_text(encoding='utf-8'))
    if qa['status']!='pass' or qa['word_pages']!=2 or qa['pdf_pages']!=2:raise RuntimeError('Native validation missing or failed')
    images=[]
    with fitz.open(pdf) as rendered:
        if len(rendered)!=2:raise RuntimeError('Word-exported PDF must have two pages')
        for i,page in enumerate(rendered):
            image=scratch/('final-page-'+str(i+1)+'.png');page.get_pixmap(matrix=fitz.Matrix(1.4,1.4)).save(image);images.append(str(image))
    approval=OUT/('visual-'+str(item.scout_id)+'.json')
    # Every render needs a fresh decision, even for an unchanged DOCX. Preserve
    # prior evidence rather than allowing an older approval to skip this wait.
    if approval.exists():
        approval.replace(OUT/('prior-visual-'+str(item.scout_id)+'-'+datetime.now(timezone.utc).strftime('%H%M%S%f')+'.json'))
    request={'id':item.scout_id,'company':item.company,'title':item.title,'resume':str(artifacts.resume),'listing':str(artifacts.listing),'images':images,'sha256':hashlib.sha256(artifacts.resume.read_bytes()).hexdigest(),'pdf_sha256':hashlib.sha256(pdf.read_bytes()).hexdigest(),'qa':qa}
    save('visual-request-'+str(item.scout_id)+'.json',request)
    state['visual_pending']=request;event('visual inspection',item.scout_id,item.company)
    with phase('review_wait'):
        while not approval.exists():time.sleep(1)
    decision=json.loads(approval.read_text(encoding='utf-8'))
    if decision.get('sha256')!=request['sha256'] or not decision.get('approved'):raise RuntimeError('Visual inspection failed; completion preserved blank')
    if hashlib.sha256(artifacts.resume.read_bytes()).hexdigest()!=request['sha256']:raise RuntimeError('Document changed after visual inspection')
    if hashlib.sha256(pdf.read_bytes()).hexdigest()!=request['pdf_sha256']:raise RuntimeError('PDF changed after visual inspection')
    event('publishing completion',item.scout_id,item.company)
    queue.record_success(item,artifacts,tracker)
    rows=tracker.scout().rows;hits=[v for _,v in rows if str(v.get('Scout ID',''))==str(item.scout_id)]
    if len(hits)!=1:raise RuntimeError('Completion readback identity is ambiguous')
    row=hits[0];today=datetime.now(ZoneInfo('America/Denver')).date().isoformat()
    if str(row.get('Resume Created','')).strip().upper()!='X' or row.get('Resume Link')!=artifacts.resume.resolve().as_uri() or row.get('Resume Created Date')!=today:
        raise RuntimeError('Marker/link/completion date independent readback failed')
    if not queue._valid_resume_link(row['Resume Link']):raise RuntimeError('Saved link does not resolve to the completed DOCX')
    receipt={**request,'readback':{k:row.get(k) for k in ('Scout ID','Company','Job Title','Resume Created','Resume Link','Resume Created Date')}}
    save('completed-'+str(item.scout_id)+'.json',receipt);state['completed'].append(item.scout_id);state['visual_pending']=None;event('completed',item.scout_id,item.company)
def failure(ident,row,reason,tracker):
    state['blocked'].append({'id':ident,'reason':reason});state['visual_pending']=None;event('blocked',ident,reason)
    queue.manage_job_tracker.record_queue_failure(ident,row,reason,tracker)
with run_lock():
    remote=GoogleTracker(config=Config.from_environment())
    validator=DailyLinkValidator()
    gecko_v2.validate_required_sources()
    # Reconcile a possible successful atomic write whose receipt was interrupted.
    rows={int(v['Scout ID']):v for _,v in remote.scout().rows if str(v.get('Scout ID','')).isdigit()}
    for path in OUT.glob('visual-request-*.json'):
        request=json.loads(path.read_text(encoding='utf-8'));ident=request['id'];row=rows.get(ident,{})
        if (OUT/('completed-'+str(ident)+'.json')).exists():continue
        approved=OUT/('visual-'+str(ident)+'.json')
        if not approved.exists():continue
        approval=json.loads(approved.read_text(encoding='utf-8'));final=Path(request['resume'])
        if queue.resume_already_created(row.get('Resume Created')) and row.get('Resume Link')==final.resolve().as_uri() and row.get('Resume Created Date') and final.exists() and hashlib.sha256(final.read_bytes()).hexdigest()==request['sha256']==approval.get('sha256') and approval.get('approved'):
            native=json.loads(Path(request['qa']['native_validation']).read_text(encoding='utf-8-sig'))
            if native['status']!='native-valid' or native['word_pages']!=2 or native['pdf_pages']!=2:raise RuntimeError('Native proof missing for pending completion '+str(ident))
            save('completed-'+str(ident)+'.json',{**request,'readback':{k:row.get(k) for k in ('Scout ID','Company','Job Title','Resume Created','Resume Link','Resume Created Date')},'reconciled_after_writer_error':True})
            state['completed'].append(ident)
            event('verified saved completion',ident,row.get('Company',''))
    initial=queue.read_queue(remote,auto_approve_geographic=True)
    save('queue-before.json',{'counts':{'pending':len(initial.pending),'already_created':len(initial.already_created),'excluded':len(initial.not_approved)+len(initial.cost_excluded)+len(initial.rejected_excluded)+len(initial.duplicate_excluded)},'pending_ids':[i.scout_id for i in initial.pending]})
    event('starting',detail=str(len(initial.pending))+' pending jobs across the entire tracker')
    # Current scored jobs first; older unscored jobs remain in the same full queue.
    policy=thresholds()
    requested={int(v) for v in sys.argv[2:]} if len(sys.argv)>1 and sys.argv[1]=='--ids' else None
    selected=[j for j in initial.pending if requested is None or j.scout_id in requested]
    ids={j.scout_id for j in selected}
    def scored(item):
        try:return all(float(item.fields.get(k,''))>=v for k,v in {'Match Score':60,'Responsibilities Match':50,'Required Skills Match':50}.items())
        except (ValueError,TypeError):return False
    groups=[{j.scout_id for j in selected if scored(j)},{j.scout_id for j in selected if not scored(j)}]
    results=[]
    for group in groups:
        if not group:continue
        result=queue.run_queue(remote,DEFAULT_DB,eligible_scout_ids=group,auto_approve_geographic=True,generator=generator,recorder=recorder,failure_recorder=failure,logger=lambda s:print(s,flush=True))
        results.append({'created':result.created,'recovered':result.recovered,'success_ids':[j.scout_id for j,a in result.successes],'failures':[{'id':f.item.scout_id,'reason':f.reason} for f in result.failures],'unexpected':[j.scout_id for j in result.unexpected]})
        save('queue-result.json',results)
    from sheet_sync import sync,ensure_frozen_headers
    save('final-sync.json',sync());ensure_frozen_headers(remote)
    event('finished',detail='All queue candidates processed; blocked jobs preserved')
