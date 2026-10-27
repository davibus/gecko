"""Read-only preflight for older queue jobs, caching one exact-job review at a time.

The main resume worker owns Gecko's run lock and remains the only tracker writer.
This helper never archives/retrieves descriptions, generates documents or writes
tracker rows; uncertain/missing descriptions stay with the canonical main queue.
"""
import sys,json,os
from pathlib import Path
ROOT=Path('C:/gecko_main');sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'job-scout')]
from google_tracker import load_environment
from storage import JobStore,DEFAULT_DB
from resume_match import assess,record
from description_readiness import assess as readiness_assess
from link_validation import DailyLinkValidator
from hard_filters import deterministic_filter
from preferences import load_preferences
import generate_apply_queue as q
from codex_runner import CodexJsonClient
load_environment()
bins=sorted((Path(os.environ['LOCALAPPDATA'])/'OpenAI/Codex/bin').glob('*/codex.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
if bins:os.environ['PATH']=str(bins[0].parent)+os.pathsep+os.environ['PATH']
class ExactClient(CodexJsonClient):
    def __init__(self):super().__init__(timeout_seconds=600)
    def complete(self,**kwargs):
        from resume_match import validate
        for attempt in range(2):
            answer=super().complete(**kwargs)
            if 'master_resume' not in kwargs['payload']:return answer
            try:
                for review in answer.get('reviews',[]):
                    item=next(j for j in kwargs['payload']['jobs'] if str(j['id'])==str(review['id']))
                    validate(review,item,kwargs['payload']['master_resume'])
                return answer
            except (ValueError,KeyError,StopIteration) as exc:
                if attempt:raise
                kwargs={**kwargs,'system':kwargs['system']+' Failed exact quotation validation: '+str(exc)+'. Copy short contiguous verbatim source quotes, never paraphrase quotations.','payload':{**kwargs['payload'],'invalid_preceding_response':answer}}
OUT=ROOT/'reports/resume-batch-20261025'
before=json.loads((OUT/'preflight.json').read_text(encoding='utf-8'))
validator=DailyLinkValidator()
results=[]
for raw in before['unscored']:
    ident=raw['id'];fields=raw['fields'];item=q.QueueRow(0,ident,raw['company'],raw['title'],fields.get('Job URL',''),fields.get('Source',''),fields,fields.get('Job Description',''))
    result={'id':ident}
    try:
        with JobStore(DEFAULT_DB) as store:
            job=store.get(ident)
            if not job or not q._stored_job_matches_row(job,item):raise ValueError('Exact stored job unavailable; leave to main queue')
            allowed,reason=deterministic_filter(job,load_preferences())
            if not allowed:raise ValueError('Eligibility exclusion: '+reason)
            live=validator.check(job)
            if live.status!='valid':raise ValueError('Availability '+live.status+': '+live.reason)
            document=store.get_job_document(ident)
            if isinstance(document,dict) and document.get('status')=='complete':description=document['full_description_markdown']
            else:
                saved=q._saved_listing(item,known_urls=tuple(str(l.get('url','')) for l in job.source_links),known_job_number=q._job_number(job))
                if not saved:raise ValueError('No verified full archive; leave retrieval to main queue')
                description=q._archived_description(saved.read_text(encoding='utf-8-sig'))
        if not q.description_is_sufficient(description):raise ValueError('Full description unavailable')
        job.description=description
        ready=readiness_assess([{'id':str(ident),'company':job.company,'title':job.title,'description':description}],client=ExactClient())[str(ident)]
        result['readiness']=ready
        if ready.get('value')=='Yes' and ready.get('status')=='reviewed':result['match']=assess([record(job)],client=ExactClient())['job']
    except Exception as exc:result['deferred']=str(exc)
    results.append(result)
    (OUT/'older-review-prefetch.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'id':ident,'cached_result':result.get('match',{}).get('status'),'accepted':result.get('match',{}).get('accepted'),'deferred':result.get('deferred')}),flush=True)
