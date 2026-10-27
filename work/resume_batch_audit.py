import sys,json,os
from pathlib import Path
from collections import Counter
ROOT=Path('C:/gecko_main')
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'job-scout')]
from google_tracker import GoogleTracker,Config,load_environment,resume_already_created
from run_gecko import run_lock
from generate_apply_queue import read_queue,_valid_resume_link
load_environment()
OUT=ROOT/'reports/resume-batch-20261025'
OUT.mkdir(exist_ok=True)
with run_lock():
    remote=GoogleTracker(config=Config.from_environment())
    tab=remote.scout()
    (OUT/'live-tracker-before.json').write_text(json.dumps({'headers':tab.headers,'rows':tab.rows},ensure_ascii=False,indent=2),encoding='utf-8')
    snapshot=read_queue(remote,auto_approve_geographic=True)
    groups={name:[{'id':j.scout_id,'company':j.company,'title':j.title,'fields':j.fields} for j in getattr(snapshot,name)] for name in ('pending','already_created','not_approved','duplicate_excluded','missing_identity','cost_excluded','rejected_excluded')}
    policy={'Match Score':60,'Responsibilities Match':50,'Required Skills Match':50}
    ready=[];unscored=[];below=[]
    for j in groups['pending']:
        try:passes=all(float(j['fields'].get(k,''))>=v for k,v in policy.items())
        except (ValueError,TypeError):unscored.append(j);continue
        (ready if passes else below).append(j)
    issues=[{'id':j.scout_id,'company':j.company,'marker':j.fields.get('Resume Created'),'link':j.fields.get('Resume Link'),'reason':'Existing completion/link requires review; preserved'} for j in snapshot.already_created if not _valid_resume_link(j.fields.get('Resume Link')) or not resume_already_created(j.fields.get('Resume Created'))]
    report={'total_rows':len(tab.rows),'counts':{k:len(v) for k,v in groups.items()},'score_qualified':ready,'unscored':unscored,'below_threshold':below,'existing_link_issues':issues,'decisions':[{'id':j.scout_id,'reason':r} for j,r in snapshot.decisions]}
    (OUT/'preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('score_qualified','unscored','below_threshold','decisions','existing_link_issues')}))
    print(json.dumps({'score_qualified':[{'id':j['id'],'company':j['company'],'title':j['title']} for j in ready],'unscored_count':len(unscored),'below_threshold_count':len(below),'existing_link_issues':issues}))
