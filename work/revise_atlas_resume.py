import json,os,sys,time
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
ROOT=Path('C:/gecko_main');sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'job-scout')]
import gecko_v2 as v2
import generate_apply_queue as queue
import resume_performance as perf
from google_tracker import GoogleTracker,Config,load_environment
from run_gecko import run_lock
from storage import DEFAULT_DB
from word_validation_client import word_session
from resume_visual_review import review
OUT=ROOT/'reports/resume-connected-2985-2991'
load_environment();remote=GoogleTracker(config=Config.from_environment())
tab=remote.scout();row,data=next((r,d) for r,d in tab.rows if str(d.get('Scout ID'))=='2987')
item=queue._queue_item(tab,row,data)
if not queue._still_pending(remote,item):raise ValueError('Atlas no longer pending; no revision permitted')
scratch=ROOT/'scratch/Atlas-HXM+scout-2987'
old_request=json.loads((scratch/'visual-review-request.json').read_text(encoding='utf-8'))
old_docx=Path(old_request['resume'])
plan=json.loads((scratch/'tailoring-plan.json').read_text(encoding='utf-8'))
with run_lock():
    if old_docx.is_file():old_docx.replace(scratch/('visual-rejected-'+old_docx.name))
(OUT/'atlas-rejected-visual-request.json').write_text(json.dumps(old_request,indent=2),encoding='utf-8')
tools=['Python','SQL','Funnel.io','Tableau','Power BI','Google Analytics 4','Google Tag Manager','HubSpot','Salesforce','Shopify','Excel','ChatGPT']
plan['resume']['selected_evidence_ids']=[eid for eid in plan['resume']['selected_evidence_ids'] if eid!='E108']
v2.set_reviewed_tools(plan,tools,'Atlas describes capabilities rather than product brands. These canonical tools are explicitly supported by the current master and prioritize data/reporting, CRM, integration, website operations and AI work. Marketplace platforms were replaced with the more relevant supported stack.')
plan['review_notes'].append('Removed E108: the master quotation ends mid-sentence. Do not add that source fragment during fitting.')
with perf.batch() as metrics,word_session():
    before=metrics.snapshot()
    with run_lock(),patch.object(v2,'create_plan',return_value=plan),patch.dict(os.environ,{'GECKO_AI_RUNNER':'connected_agent'}):
        artifacts=queue.generate(item,DEFAULT_DB,tracker=remote)
    (OUT/'atlas-revision-native.json').write_text(json.dumps({'resume':str(artifacts.resume),'qa':artifacts.review_context['qa'],'timings':metrics.delta(before)},indent=2),encoding='utf-8')
    print('Atlas revision ready for fresh visual review',flush=True)
    proof=review(artifacts.resume,scratch/'word-export.pdf',scratch,artifacts.review_context['qa'])
    print('Atlas revised visual review passed: '+str(proof),flush=True)
