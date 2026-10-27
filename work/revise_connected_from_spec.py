"""Revise an uncompleted, visually rejected candidate through canonical generation and fresh review."""
import json,os,sys
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone
ROOT=Path('C:/gecko_main');sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'job-scout')]
import gecko_v2 as v2
import generate_apply_queue as queue
import resume_performance as perf
from google_tracker import GoogleTracker,Config,load_environment
from run_gecko import run_lock
from storage import DEFAULT_DB
from word_validation_client import word_session
from resume_visual_review import review
ident=int(sys.argv[1]);out=ROOT/'reports/resume-connected-2985-2991'
revision=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
load_environment();remote=GoogleTracker(config=Config.from_environment());tab=remote.scout()
row,data=next((r,d) for r,d in tab.rows if str(d.get('Scout ID'))==str(ident));item=queue._queue_item(tab,row,data)
if not queue._still_pending(remote,item):raise ValueError('Job is no longer pending; no revision permitted')
safe=v2.listing_metadata(queue._archive_row_context(item).read_text(encoding='utf-8'),queue._archive_row_context(item))
scratch=ROOT/'scratch'/(safe['safe_company']+'+'+safe['job_number'])
old=json.loads((scratch/'visual-review-request.json').read_text(encoding='utf-8'))
plan=json.loads((scratch/'tailoring-plan.json').read_text(encoding='utf-8'))
stamp=datetime.now(timezone.utc).strftime('%H%M%S%f')
with run_lock():
    path=Path(old['resume'])
    if path.is_file():path.replace(scratch/('visual-rejected-'+stamp+'-'+path.name))
(out/f'rejected-review-{ident}-{stamp}.json').write_text(json.dumps(old,indent=2),encoding='utf-8')
selected=[eid for eid in plan['resume']['selected_evidence_ids'] if eid not in revision['remove_evidence_ids']]
selected.extend(eid for eid in revision['add_evidence_ids'] if eid not in selected)
plan['resume']['selected_evidence_ids']=selected
plan['resume']['additional_evidence_ids']=revision['additional_evidence_ids']
plan['review_notes'].append(revision['rationale'])
with perf.batch() as metrics,word_session():
    before=metrics.snapshot()
    with run_lock(),patch.object(v2,'create_plan',return_value=plan),patch.dict(os.environ,{'GECKO_AI_RUNNER':'connected_agent'}):
        artifacts=queue.generate(item,DEFAULT_DB,tracker=remote)
    (out/f'revision-native-{ident}.json').write_text(json.dumps({'resume':str(artifacts.resume),'qa':artifacts.review_context['qa'],'timings':metrics.delta(before)},indent=2),encoding='utf-8')
    print('Revision ready for fresh review',flush=True)
    print(review(artifacts.resume,scratch/'word-export.pdf',scratch,artifacts.review_context['qa']),flush=True)
