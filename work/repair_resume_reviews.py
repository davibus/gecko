"""Repair invalid quotations in independent cached reviews; never write tracker."""
import json,sys,time,subprocess
from pathlib import Path
ROOT=Path('C:/gecko_main');OUT=ROOT/'reports/resume-batch-20261025'
attempted={2854,2955}
while True:
    try:state=json.loads((OUT/'run-status.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):time.sleep(5);continue
    candidates=[b['id'] for b in state['blocked'] if b['id'] not in attempted and 'Evidence is not in current master resume' in b['reason']]
    for ident in candidates:
        attempted.add(ident)
        with (OUT/('retry-'+str(ident)+'.log')).open('w',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,str(ROOT/'work/retry_resume_match.py'),str(ident)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (OUT/'review-repair-status.json').write_text(json.dumps({'attempted_ids':sorted(attempted),'last_id':ident,'exit_code':result.returncode}),encoding='utf-8')
    if state['stage']=='finished':break
    time.sleep(5)
