import sys,json,os,hashlib
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
ROOT=Path('C:/gecko_main')
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts'),str(ROOT/'work')]
from google_tracker import GoogleTracker,Config,load_environment,resume_approval_value
load_environment()
native_bins=sorted((Path(os.environ['LOCALAPPDATA'])/'OpenAI/Codex/bin').glob('*/codex.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
if native_bins:os.environ['PATH']=str(native_bins[0].parent)+os.pathsep+os.environ['PATH']
DAY=datetime.now(ZoneInfo('America/Denver')).date().isoformat()
os.environ['GECKO_UNLIMITED_USAGE']=DAY
from firecrawl_state import History,config
from sources.firecrawl import FirecrawlClient
from firecrawl_discovery import known,seed_history,remember,extract_listing
from firecrawl_postings import public_listing,reject_result
from job_extraction import extract as original_extract,salary_display,tracker_notes
def extract(data,raw,evidence):
    import re
    doc=original_extract(data,raw,evidence)
    from link_validation import EXPIRED,BOT
    if (data.get('metadata') or {}).get('statusCode',200)!=200 or BOT.search(doc['full_description_markdown'][:3000]) or EXPIRED.search(doc['full_description_markdown']):
        doc['issues'].append('Posting availability or access requires review')
    for issue in list(doc['issues']):
        prefix='Published section is empty: '
        if issue.startswith(prefix):
            label=issue[len(prefix):]
            sections=list(re.finditer(r'(?im)^#{1,6}\s*'+re.escape(label)+r'\s*$',doc['full_description_markdown']))
            if any((body:=doc['full_description_markdown'][s.end():].strip()) and not body.startswith('#') for s in sections):
                doc['issues'].remove(issue)  # A populated original section resolves an empty duplicated heading.
    doc['status']='review' if doc['issues'] else 'complete'
    header=re.search(r'(?im)^#{1,6}\s*(?:Location Type|Workplace Type|Work Arrangement)\s*\n+\s*(Remote|Hybrid|On[ -]site)\b',doc['full_description_markdown'])
    if header:
        doc['fields']['work_arrangement']=header[1].lower().replace(' ','-')
        doc['fields']['work_arrangement_evidence']=header[0]
    salary=doc['fields']['salary']
    if not raw.metadata.get('baseSalary') and re.search(r'\b(?:spend|budget|revenue)\b',str(salary.get('evidence') or ''),re.I):
        doc['fields']['salary']={'minimum':None,'maximum':None,'currency':None,'pay_period':None,'evidence':None}
    return doc
from storage import JobStore,DEFAULT_DB
from preferences import load_preferences
from normalize import normalize,posting_identity
from hard_filters import deterministic_filter
from resume_match import check,explanation,assess,record as match_record,validate,thresholds as match_thresholds
from codex_runner import CodexJsonClient
class ValidatedClient(CodexJsonClient):
    def __init__(self):super().__init__(timeout_seconds=600)
    def complete(self,*,model,system,payload):
        answer=super().complete(model=model,system=system,payload=payload)
        try:
            for review in answer.get('reviews',[]):
                item=next(j for j in payload['jobs'] if str(j['id'])==str(review['id']))
                validate(review,item,payload['master_resume'])
        except (ValueError,KeyError,StopIteration) as exc:
            answer=super().complete(model=model,system=system+' Your preceding response failed exact quotation validation: '+str(exc)+'. Copy shorter contiguous verbatim source quotes; do not paraphrase or combine excerpts. Reassess all material requirements faithfully.',payload={**payload,'invalid_preceding_response':answer})
        return answer
from deduplicate import find_duplicate
from service import _same_source_identity_conflicts
from sheet_sync import ensure_frozen_headers
from watch_gecko_search import LABELS
OUT=ROOT/'work/codex-focused-search'
TARGET=20
OUT.mkdir(exist_ok=True)
remote=GoogleTracker(config=Config.from_environment())
history=History()
client=FirecrawlClient(history=history)
def save(name,value):
    import uuid
    p=OUT/name;temporary=p.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8');temporary.replace(p)
def ids():return json.loads((OUT/'published.json').read_text()) if (OUT/'published.json').exists() else [2953,2954]
def panel(activity,status='RUNNING - directed search',progress=False):
    now=datetime.now(ZoneInfo('America/Denver')).strftime('%m-%d-%Y | %I:%M %p %Z')
    p=ROOT/'reports/discovery/live-status.json'
    old=json.loads(p.read_text()) if p.exists() else {}
    last=now if progress else old.get('last_progress_display',now)
    value={'run_id':'codex-directed-'+DAY,'status':status,'verified_job_ids':ids(),'published_jobs_verified':len(ids()),'target_jobs':TARGET,'activity':activity,'last_progress_display':last,'checked_at':datetime.now(timezone.utc).isoformat(),'usage_unlimited_date':DAY}
    cells=[LABELS,[status,f'{len(ids())} / {TARGET}',activity,last,now]]
    remote.api.values().update(spreadsheetId=remote.config.spreadsheet_id,range="'Daily Run'!H1:L2",valueInputOption='RAW',body={'values':cells}).execute()
    assert remote.api.values().get(spreadsheetId=remote.config.spreadsheet_id,range="'Daily Run'!H1:L2").execute()['values']==cells
    p.write_text(json.dumps(value,indent=2),encoding='utf-8')
def log(record):
    with (OUT/'decisions.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
    print(json.dumps(record,ensure_ascii=False),flush=True)
def search(query):
    print(json.dumps({'search_started':query}),flush=True)
    payload={'query':query,'limit':50,'sources':['web']}
    result=client.call('search',payload)
    web=result.get('web',[]) if isinstance(result,dict) else result
    candidates=[{**r,'actual_query':query} for r in web if not known(history,r.get('url',''))]
    name=datetime.now().strftime('%H%M%S')+'-directed-search.json'
    save(name,{'payload':payload,'results':web,'candidates':candidates})
    print(json.dumps({'file':name,'results':len(web),'new_candidates':[{'url':r['url'],'title':r.get('title'),'description':r.get('description','')[:250]} for r in candidates]}),flush=True)
def gather(paths,hydrate=False):
    from concurrent.futures import ThreadPoolExecutor,as_completed
    from role_filter import is_relevant_role
    entries={}
    for path in paths:
        payload=json.loads(Path(path).read_text(encoding='utf-8'))
        for e in payload['candidates']:
            if is_relevant_role(e.get('title','')) and not known(history,e['url']):entries.setdefault(e['url'],e)
    def fetch(entry):
        url=entry['url'];key=hashlib.sha256(url.encode()).hexdigest()
        if reject_result(url,entry.get('title',''),datetime.now(timezone.utc)):return None
        p=OUT/(key+'-source.json')
        if p.exists():data=json.loads(p.read_text(encoding='utf-8'))['data'];raw,ev,final=extract_listing(data,url)
        else:
            public=public_listing(url,{})
            if public is None:
                if not hydrate:return {'entry':entry,'url':url,'title':entry['title'],'status':'needs scrape'}
                data=client.call('scrape',{'url':url,'formats':['rawHtml','markdown'],'onlyMainContent':True,'proxy':'basic','parsers':[],'maxAge':86400000})
                raw,ev,final=extract_listing(data,url)
            else:data,raw,ev,final=public
            save(key+'-source.json',{'entry':entry,'data':data})
        if raw is None:return None
        doc=extract(data,raw,ev);raw.description=doc['full_description_markdown'];raw.salary=salary_display(doc['fields']['salary']);raw.employment_type='; '.join(doc['fields']['employment_types']);raw.remote_type=doc['fields']['work_arrangement'] or raw.remote_type
        job=normalize(raw,discovered=DAY);job.work_arrangement=doc['fields']['work_arrangement'] or job.work_arrangement
        accepted,reason=deterministic_filter(job,load_preferences())
        return {'entry':entry,'url':url,'company':job.company,'title':job.title,'location':job.location,'arrangement':job.work_arrangement,'salary':job.salary,'posted':job.date_posted,'status':doc['status'],'eligible':accepted and resume_approval_value(job.location,job.work_arrangement,'')=='Yes' and doc['fields']['application_fee_required'] is not True,'filter':reason,'chars':len(job.description),'issues':doc['issues']}
    records=[]
    with ThreadPoolExecutor(max_workers=1 if hydrate else 3) as executor:
        pending={executor.submit(fetch,e):e for e in entries.values()}
        for future in as_completed(pending):
            try:
                value=future.result()
                if value:records.append(value);print(json.dumps({k:v for k,v in value.items() if k!='entry'}),flush=True)
            except Exception as exc:print(json.dumps({'url':pending[future]['url'],'error':str(exc)[:300]}),flush=True)
            save('hydrated.json' if hydrate else 'gathered.json',records)
    ready=[r['entry'] for r in records if r.get('eligible') and r.get('status')=='complete']
    save('hydrated-ready.json' if hydrate else 'ready.json',ready)
def queue():
    import re
    decisions={}
    p=OUT/'decisions.jsonl'
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            d=json.loads(line);decisions[d['url']]=d
    ready=[]
    with JobStore(DEFAULT_DB) as store:existing_jobs=store.all()
    for path in OUT.glob('*-source.json'):
        source=json.loads(path.read_text(encoding='utf-8'));entry=source['entry'];url=entry['url']
        if known(history,url):continue
        prior=decisions.get(url,{})
        if prior.get('status')=='reviewed' and prior.get('thresholds')==match_thresholds():continue
        raw,ev,final=extract_listing(source['data'],url)
        if raw is None:continue
        doc=extract(source['data'],raw,ev)
        raw.description=doc['full_description_markdown'];raw.salary=salary_display(doc['fields']['salary']);raw.employment_type='; '.join(doc['fields']['employment_types']);raw.remote_type=doc['fields']['work_arrangement'] or raw.remote_type
        job=normalize(raw,discovered=DAY);job.work_arrangement=doc['fields']['work_arrangement'] or job.work_arrangement
        accepted,reason=deterministic_filter(job,load_preferences())
        if not accepted or doc['status']!='complete' or resume_approval_value(job.location,job.work_arrangement,'')!='Yes':continue
        if 'only hiring in the Eastern and Central time zones' in doc['full_description_markdown']:continue
        if re.search(r'\b(?:PH|Romania|Bulgaria|Philippines|LATAM|Argentina|Toronto|Remote, ON|Remote, AB)\b',job.title+' '+job.location,re.I):continue
        if job.location.strip().upper() in {'MX','CA','EG','CL','AU','NZ','BR','CO','AR','IN','PH','GB','UK','EU'}:continue
        if re.search(r',\s*(?:AU|NZ|BR|CO|AR|PH|GB|UK|IN)\s*$',job.location) or '(TN)' in job.title:continue
        if find_duplicate(job,[j for j in existing_jobs if not _same_source_identity_conflicts(job,j)]):continue
        if doc['fields']['application_fee_required'] is True:continue
        ready.append((entry,job))
    priority=['Linear Agency','H&H Group','Rise Collective','Portnox','NRTC','NowSecure','BlastX Consulting','Advantage HQ','Constructor','NMI','Digitalzone, Inc.']
    ready.sort(key=lambda p:(priority.index(p[1].company) if p[1].company in priority else 50,0 if re.search('paid search|google ads|ppc|SEM',p[1].title,re.I) else 1 if 'paid media' in p[1].title.lower() else 2,1 if decisions.get(p[0]['url'],{}).get('status')=='pending' else 0))
    save('priority-queue.json',[e for e,j in ready])
    print(json.dumps({'count':len(ready),'candidates':[{'company':j.company,'title':j.title,'url':e['url']} for e,j in ready]}))
def correct_valid_salary():
    tab=remote.scout();hits=[(r,v) for r,v in tab.rows if str(v.get('ID',v.get('Scout ID','')))=='2956']
    assert len(hits)==1
    number,row=hits[0]
    assert row['Company']=='Valid' and row['Job URL']=='https://jobs.ashbyhq.com/Valid/165d053b-a047-4bc5-9dca-7f189c8c5bca'
    note='Salary not stated. The $500,000/month figure is required managed advertising spend, not compensation.'
    if row['Salary']:
        assert '500,000' in row['Salary'] and 'month' in row['Salary']
        remote.update_manual_scout_row(tab,number,{'Salary':'','Notes':row['Notes']+'\n'+note})
    result=next(v for _,v in remote.scout().rows if str(v.get('ID',v.get('Scout ID','')))=='2956')
    assert result['Salary']=='' and note in result['Notes']
    ensure_frozen_headers(remote)
    save('salary-correction-2956.json',{'before':row,'after':result,'reason':note})
    print(json.dumps({'id':2956,'salary':'','readback_verified':True,'reason':note}))
def park_hybrid_rows():
    for ident,company in [(2956,'Valid'),(2958,'NoGood')]:
        tab=remote.scout();hits=[(r,v) for r,v in tab.rows if str(v.get('ID',v.get('Scout ID','')))==str(ident)]
        if not hits:continue
        assert len(hits)==1
        number,row=hits[0];assert row['Company']==company
        description=row.get('FireCrawl Job Description') or row.get('Firecrawl Job Description') or row.get('Job Description') or ''
        import re
        assert re.search(r'(?im)^#{1,6}\s*Location Type\s*\n+\s*Hybrid\b',description)
        note='Location review: employer posting explicitly labels this job Hybrid outside Utah. Generic remote benefits or remote-friendly wording conflict with that designation. Not counted toward the qualified-job target.'
        changes={'Work Arrangement':'hybrid'}
        if note not in row['Notes']:changes['Notes']=row['Notes']+'\n'+note
        remote.update_manual_scout_row(tab,number,changes)
        result=next(v for _,v in remote.scout().rows if str(v.get('ID',v.get('Scout ID','')))==str(ident))
        assert result['Work Arrangement']=='hybrid' and result['Apply?']=='No'
        save('location-review-'+str(ident)+'.json',{'before':row,'after':result,'reason':note})
        save('published.json',[i for i in ids() if i!=ident])
        print(json.dumps({'id':ident,'company':company,'qualification':'No','preserved':True,'readback_verified':True}))
    ensure_frozen_headers(remote)
    panel('Hybrid postings parked for review; continuing verified remote/Utah candidates',progress=True)
def batch_process(path):
    direct(path)
def review_one(entry):
    """One complete posting per independent client; canonical caches remain authoritative."""
    from description_readiness import assess as readiness_assess
    url=entry['url'];key=hashlib.sha256(url.encode()).hexdigest()
    source=json.loads((OUT/(key+'-source.json')).read_text(encoding='utf-8'))
    raw,ev,final=extract_listing(source['data'],url)
    if raw is None:return {'accepted':False,'status':'pending','reason':'No unique employer posting'}
    doc=extract(source['data'],raw,ev)
    raw.description=doc['full_description_markdown'];raw.salary=salary_display(doc['fields']['salary']);raw.employment_type='; '.join(doc['fields']['employment_types']);raw.remote_type=doc['fields']['work_arrangement'] or raw.remote_type
    job=normalize(raw,discovered=DAY);job.description=doc['full_description_markdown'];job.work_arrangement=doc['fields']['work_arrangement'] or job.work_arrangement
    allowed,reason=deterministic_filter(job,load_preferences())
    if not allowed or doc['status']!='complete' or doc['fields']['application_fee_required'] is True or resume_approval_value(job.location,job.work_arrangement,'')!='Yes':
        return {'accepted':False,'status':'filtered','reason':reason or str(doc['issues'])}
    readiness=readiness_assess([{'id':key,'company':job.company,'title':job.title,'description':job.description}],client=CodexJsonClient(timeout_seconds=600))[key]
    if readiness['status']!='reviewed' or readiness['value']!='Yes':
        return {'accepted':False,'status':'pending','reason':readiness['reason'],'readiness':readiness}
    match=assess([match_record(job,key)],client=ValidatedClient())[key]
    return {**match,'readiness':readiness,'company':job.company,'title':job.title}

def direct(candidate_path=None):
    from focused_discovery import run_round
    # Seed stable identities once before any source retrieval/review. No existing
    # job maintenance is requested by this new-job search.
    with JobStore(DEFAULT_DB) as store:seed_history(history,store,remote)
    reconcile()
    audit()
    if candidate_path is None:queue()
    candidates=json.loads(Path(candidate_path or OUT/'priority-queue.json').read_text(encoding='utf-8'))
    stopfile=OUT/'focused-search.stop'
    def checkpoint(entry,stage,result):
        key=hashlib.sha256(entry['url'].encode()).hexdigest()
        save(key+'-focused-checkpoint.json',{'entry':entry,'stage':stage,'result':result,'checked_at':datetime.now(timezone.utc).isoformat()})
        if stage=='reviewed':
            log({'url':entry['url'],'decision':'independent review','thresholds':match_thresholds(),**result})
    def publish(entry,result):
        before=set(ids());save('publish-next.json',[entry]);process(OUT/'publish-next.json')
        added=set(ids())-before
        return {'verified':len(added)==1,'ids':sorted(added)}
    def status(stage,detail):
        activity=(detail.get('title') or detail.get('url')) if isinstance(detail,dict) else str(detail)
        panel(stage+': '+activity[:170],stage.upper())
    run_round(candidates,target=TARGET,confirmed=ids,identity=lambda e:posting_identity(e['url']),known=lambda e:known(history,e['url']),review=review_one,publish=publish,checkpoint=checkpoint,status=status,stopped=stopfile.exists)
    if len(ids())>=TARGET:
        audit();panel(f'{TARGET} unique qualifying jobs verified; new discovery stopped','FINISHED',progress=True)
    elif stopfile.exists():panel('Stop requested; completed evidence saved, no new requests','STOPPED')
    else:panel('Cached candidate round exhausted; focused source expansion needed','WAITING - sources')
def reconcile():
    from focused_discovery import reconcile_pending
    from query_provenance import query_for_job
    pending=[json.loads(p.read_text(encoding='utf-8')) for p in OUT.glob('pending-*.json') if p.stem.split('-')[-1].isdigit()]
    rows=remote.scout().rows
    class CacheOnly:
        def complete(self,**kwargs):raise RuntimeError('Saved evidence review unavailable; preserve pending')
    with JobStore(DEFAULT_DB) as store:
        def verify(candidate):
            ident=candidate['id'];job=store.get(ident)
            hits=[v for _,v in rows if str(v.get('ID',v.get('Scout ID','')))==str(ident)]
            if not job or not hits:return None
            assert len(hits)==1,('Duplicate pending ID',ident)
            row=hits[0];query=query_for_job(job)
            if row.get('Apply?')!='Yes':return None
            match=assess([match_record(job)],client=CacheOnly())['job']
            if not match['accepted']:return None
            assert row['Company']==job.company and row['Job Title']==job.title
            assert posting_identity(row['Job URL'])==posting_identity(job.authoritative_url or job.url)
            assert abs(float(row['Match Score'])-match['score'])<.011
            assert query and row['Query Used to Find']==query,('Unconfirmed pending query',ident)
            policy=match_thresholds()
            assert float(row['Responsibilities Match'])>=policy['minimum_responsibilities_match'] and float(row['Required Skills Match'])>=policy['minimum_required_skills_match']
            return {'verified':True,'id':ident,'company':job.company,'title':job.title,'url':candidate['entry']['url'],'score':match['score'],'query':query,'readback':row,'query_evidence':{'authority':'query_provenance.sqlite','url':job.url,'query':query},'publication':{'reconciled_pending_writer_receipt':True}}
        def record(candidate,receipt):
            save('verified-'+str(candidate['id'])+'.json',receipt)
            published=ids();published.append(candidate['id']);save('published.json',sorted(set(published)))
            log({'decision':'pending publication independently reconciled',**{k:v for k,v in receipt.items() if k not in ('readback','publication')}})
        reconcile_pending(pending,confirmed=ids,verify=verify,record=record)
    ensure_frozen_headers(remote)

def audit():
    tab=remote.scout();verified=[];policy=match_thresholds()
    for ident in ids():
        hits=[v for _,v in tab.rows if str(v.get('ID',v.get('Scout ID','')))==str(ident)]
        assert len(hits)==1,('missing/duplicate ID',ident)
        row=hits[0]
        qualification_ok=(row['Apply?']=='Yes') or (ident in (2953,2954) and row['Apply?']=='' and resume_approval_value(row.get('Location',''),row.get('Work Arrangement',''),row.get('Cost',''))=='Yes')
        assert qualification_ok and float(row['Match Score'])>=policy['minimum_score'] and float(row['Responsibilities Match'])>=policy['minimum_responsibilities_match'] and float(row['Required Skills Match'])>=policy['minimum_required_skills_match'],(ident,{k:row.get(k) for k in ['Company','Apply?','Qualifies to Apply?','Match Score','Responsibilities Match','Required Skills Match','Location','Work Arrangement','Cost']})
        assert row['Query Used to Find']
        if ident not in (2953,2954):
            saved=json.loads((OUT/('verified-'+str(ident)+'.json')).read_text(encoding='utf-8'))
            assert row['Company']==saved['company'] and row['Job Title']==saved['title'] and row['Query Used to Find']==saved['query']
            assert posting_identity(row['Job URL'])==posting_identity(saved['readback']['Job URL']) and abs(float(row['Match Score'])-float(saved['score']))<.011
            source=OUT/(hashlib.sha256(saved['url'].encode()).hexdigest()+'-source.json')
            assert source.exists()
            source_query=json.loads(source.read_text(encoding='utf-8'))['entry']['actual_query']
            if source_query!=row['Query Used to Find']:
                from query_provenance import query_for_job
                with JobStore(DEFAULT_DB) as store:recorded_query=query_for_job(store.get(ident))
                assert saved.get('query_evidence',{}).get('query')==recorded_query==row['Query Used to Find']
        verified.append({k:row.get(k) for k in ['ID','Company','Job Title','Job URL','Match Score','Responsibilities Match','Required Skills Match','Query Used to Find','Salary','Enough Data','Last Updated']})
    props=remote._sheet_properties()
    frozen={p['title']:p.get('gridProperties',{}).get('frozenRowCount',0) for p in props}
    assert all(n>=1 for n in frozen.values())
    reviews=[{k:v.get(k) for k in ['ID','Company','Job Title','Qualifies to Apply?','Work Arrangement','Salary']} for _,v in tab.rows if str(v.get('ID',v.get('Scout ID',''))) in {'2956','2958'}]
    assert all(v['Qualifies to Apply?']=='No' for v in reviews)
    usage=history.usage(DAY)
    result={'complete':len(verified)==TARGET,'target_jobs':TARGET,'verified_total':len(verified),'added_qualified_this_continuation':len(verified)-2,'prior_verified_ids':[2953,2954],'qualified_jobs':verified,'location_review_rows':reviews,'frozen_rows':frozen,'usage_today':usage,'usage_this_continuation':{'provider_confirmed_credits':usage['provider_confirmed_credits']-272,'estimated_or_reserved_credits':usage['estimated_or_reserved_credits']-66,'total_credits_accounted':usage['total_credits_accounted']-338},'spreadsheet_id':remote.config.spreadsheet_id,'verified_at':datetime.now(timezone.utc).isoformat(),'resumes_generated':0,'applications_submitted':0}
    result['complete']=len(verified)>=TARGET
    result['shortfall']=max(0,TARGET-len(verified))
    result['above_target']=max(0,len(verified)-TARGET)
    save('final-verification.json',result)
    print(json.dumps(result,ensure_ascii=False))
def process(path):
    entries=json.loads(Path(path).read_text(encoding='utf-8'))
    if isinstance(entries,dict):entries=entries['candidates']
    with JobStore(DEFAULT_DB) as store:
        seed_history(history,store,remote)
        rejected=remote.rejected_jobs_index()
        cache={}
        for entry in entries:
            if len(ids())>=TARGET:break
            url=entry['url'];key=hashlib.sha256(url.encode()).hexdigest()
            if known(history,url):log({'url':url,'decision':'known duplicate'});continue
            from role_filter import is_relevant_role
            if not is_relevant_role(entry.get('title','')):continue
            if reject_result(url,entry.get('title',''),datetime.now(timezone.utc)):continue
            panel('Retrieving full employer posting: '+entry.get('title','')[:150])
            try:
                source=OUT/(key+'-source.json')
                if source.exists():
                    data=json.loads(source.read_text(encoding='utf-8'))['data'];raw,evidence,final=extract_listing(data,url);public=(data,raw,evidence,final)
                else:public=public_listing(url,cache)
                if public is None:
                    data=client.call('scrape',{'url':url,'formats':['rawHtml','markdown'],'onlyMainContent':True,'proxy':'basic','parsers':[],'maxAge':86400000})
                    raw,evidence,final=extract_listing(data,url)
                else:data,raw,evidence,final=public
                save(key+'-source.json',{'entry':entry,'data':data})
                if raw is None:log({'url':url,'decision':'no unique employer JobPosting'});continue
                document=extract(data,raw,evidence)
                raw.description=document['full_description_markdown']
                raw.employment_type='; '.join(document['fields']['employment_types'])
                raw.salary=salary_display(document['fields']['salary'])
                raw.remote_type=document['fields']['work_arrangement'] or raw.remote_type
                raw.metadata['_extraction']=document
                raw.metadata['_query_used_to_find']=entry['actual_query']
                from query_provenance import remember as remember_query
                remember_query([raw])
                job=normalize(raw,discovered=DAY);job.found_using='Firecrawl';job.details=document
                job.description=document['full_description_markdown']
                job.work_arrangement=document['fields']['work_arrangement'] or job.work_arrangement
                base={'url':url,'company':job.company,'title':job.title,'location':job.location,'arrangement':job.work_arrangement,'salary':job.salary,'posted':job.date_posted,'chars':len(job.description)}
                accepted,reason=deterministic_filter(job,load_preferences())
                if not accepted:log({**base,'decision':reason});remember(history,url,'focused excluded');continue
                if document['status']!='complete':log({**base,'decision':'incomplete description','issues':document['issues']});continue
                if resume_approval_value(job.location,job.work_arrangement,'')!='Yes':log({**base,'decision':'location not verified eligible'});continue
                if document['fields']['application_fee_required'] is True:log({**base,'decision':'required applicant fee'});continue
                if rejected.matches_job(job):log({**base,'decision':'rejection history'});continue
                existing=find_duplicate(job,[j for j in store.all() if not _same_source_identity_conflicts(job,j)])
                if existing:log({**base,'decision':'duplicate','existing_id':existing.id});remember(history,url,'focused duplicate');continue
                panel('Scoring complete posting against Word master: '+job.company+' / '+job.title)
                match=assess([match_record(job)],client=ValidatedClient())['job']
                save(key+'-review.json',{'job':base,'match':match})
                if not match['accepted']:log({**base,'decision':explanation(match),'status':match['status']});continue
                job.authoritative_url=final;job.url_verification_status='verified';job.url_destination_type='official_ats'
                job.id=store.save(job);store.save_url_resolution(job);store.save_job_document(job.id,document)
                save('pending-'+str(job.id)+'.json',{'id':job.id,'entry':entry})
                panel('Publishing qualified job '+str(job.id)+': '+job.company)
                result=remote.upsert_scout([job],discovery_notes={job.id:tracker_notes(document)},fill_blanks_only=True)
                if result.get('skipped') or not result.get('readback_verified') or result.get('added')!=1:raise RuntimeError('Publication not confirmed: '+str(result))
                rows=remote.scout().rows
                hits=[v for _,v in rows if str(v.get('ID',v.get('Scout ID','')))==str(job.id)]
                assert len(hits)==1
                row=hits[0]
                assert row['Company']==job.company and row['Job Title']==job.title
                assert posting_identity(row['Job URL'])==posting_identity(final)
                assert abs(float(row['Match Score'])-float(match['score']))<.011
                from query_provenance import query_for_job
                recorded_query=query_for_job(job)
                assert recorded_query and row['Query Used to Find']==recorded_query,('Unconfirmed discovery query',job.id)
                assert row.get('Apply?',row.get('Qualifies to Apply?'))=='Yes'
                ensure_frozen_headers(remote)
                published=ids();published.append(job.id);save('published.json',published)
                remember(history,url,'focused published',company=job.company,job_id=job.source_job_id)
                record={**base,'decision':'published and read back','id':job.id,'score':row['Match Score'],'query':row['Query Used to Find'],'readback':row,'publication':result}
                record['query_evidence']={'authority':'query_provenance.sqlite','url':job.url,'query':recorded_query}
                save('verified-'+str(job.id)+'.json',record);log({k:v for k,v in record.items() if k not in ['readback','publication']})
                panel('Verified '+str(job.id)+' '+job.company+' / '+job.title,progress=True)
            except Exception as exc:
                import traceback
                log({'url':url,'decision':'pending/error','error':type(exc).__name__+': '+str(exc)[:800],'traceback':traceback.format_exc()})
                raise
if __name__=='__main__':
    mode=sys.argv[1]
    if mode=='search':
        queries=json.loads((OUT/'queries.json').read_text(encoding='utf-8'))
        for index in map(int,sys.argv[2:]):search(queries[index])
    elif mode=='process':
        for path in sys.argv[2:]:
            process(path)
            if len(ids())>=TARGET:break
    elif mode=='panel':panel(sys.argv[2],sys.argv[3] if len(sys.argv)>3 else 'RUNNING - directed search')
    elif mode=='usage':print(json.dumps(history.usage(DAY)))
    elif mode=='gather':gather(sys.argv[2:])
    elif mode=='hydrate':gather(sys.argv[2:],hydrate=True)
    elif mode=='queue':queue()
    elif mode=='verify':
        rows=remote.scout().rows
        wanted=set(ids()+[int(p.stem.split('-')[-1]) for p in OUT.glob('pending-*.json') if p.stem.split('-')[-1].isdigit()])
        print(json.dumps([{k:v.get(k) for k in ['ID','Scout ID','Company','Job Title','Job URL','Match Score','Responsibilities Match','Required Skills Match','Query Used to Find','Enough Data','Apply?','Location','Work Arrangement']} for _,v in rows if str(v.get('ID',v.get('Scout ID',''))) in set(map(str,wanted))]))
    elif mode=='correct-valid-salary':correct_valid_salary()
    elif mode=='batch':batch_process(sys.argv[2])
    elif mode=='park-hybrid':park_hybrid_rows()
    elif mode=='direct':direct()
    elif mode=='heartbeat':
        snapshot=json.loads((ROOT/'reports/discovery/live-status.json').read_text(encoding='utf-8'))
        panel(snapshot['activity'],snapshot['status'])
    elif mode=='audit':audit()
    elif mode=='reconcile':reconcile()
