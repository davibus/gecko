"""Retry one invalid evidence review, without tracker or resume writes."""
import sys,os,json
from pathlib import Path
ROOT=Path('C:/gecko_main');sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'job-scout')]
from google_tracker import load_environment
from codex_runner import CodexJsonClient
from resume_match import assess,record,validate
from storage import JobStore,DEFAULT_DB
import generate_apply_queue as queue
load_environment()
bins=sorted((Path(os.environ['LOCALAPPDATA'])/'OpenAI/Codex/bin').glob('*/codex.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
if bins:os.environ['PATH']=str(bins[0].parent)+os.pathsep+os.environ['PATH']
class ExactClient(CodexJsonClient):
    def __init__(self):super().__init__(timeout_seconds=600)
    def complete(self,**kwargs):
        for attempt in range(2):
            answer=super().complete(**kwargs)
            try:
                for review in answer.get('reviews',[]):
                    item=next(j for j in kwargs['payload']['jobs'] if str(j['id'])==str(review['id']))
                    validate(review,item,kwargs['payload']['master_resume'])
                return answer
            except (ValueError,KeyError,StopIteration) as exc:
                if attempt:raise
                kwargs={**kwargs,'system':kwargs['system']+' Your preceding response failed exact quotation validation: '+str(exc)+'. Copy short, contiguous verbatim quotes from the supplied master and posting. Do not paraphrase or join quotations. Reassess faithfully.','payload':{**kwargs['payload'],'invalid_preceding_response':answer}}
with JobStore(DEFAULT_DB) as store:
    job=store.get(int(sys.argv[1]))
    paths=[p for p in (ROOT/'input/job-descriptions').glob('*.md') if '- **Scout ID:** '+str(job.id)+'\n' in p.read_text(encoding='utf-8-sig',errors='replace')]
    if not paths:
        expected=ROOT/'input/job-descriptions'/(job.company.replace(' ','-')+'+'+queue._job_number(job)+'.md')
        if expected.exists():paths=[expected]
    if len(paths)!=1:raise RuntimeError('Exact archived listing ambiguous')
    meta=queue.gecko_v2.listing_metadata(paths[0].read_text(encoding='utf-8-sig'),paths[0])
    if queue._identity_text(meta['company'])!=queue._identity_text(job.company) or queue._identity_text(meta['title'])!=queue._identity_text(job.title):raise RuntimeError('Archived posting identity differs')
    job.description=queue._archived_description(paths[0].read_text(encoding='utf-8-sig'))
    result=assess([record(job)],client=ExactClient())['job']
    out=ROOT/'reports/resume-batch-20261025'/('retry-match-'+str(job.id)+'.json')
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('categories','job')}))
