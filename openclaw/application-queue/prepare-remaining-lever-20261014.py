import json,subprocess
from pathlib import Path
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');scope=json.loads((Q/'remaining-lever-preparation-20261014.json').read_text());out=[]
for j in scope['ids']:
 old=Q/j/'submission-result.json'
 if old.exists() and json.loads(old.read_text(encoding='utf-8-sig')).get('outcome') in ('submitted','already_applied_verified'):continue
 print('Preparing approved remaining job '+j,flush=True)
 run=subprocess.run(['python3',str(Q/'prepare-or-submit-lever-20261014.py'),j],cwd=Q,text=True,capture_output=True)
 item={'job_id':j,'exit_code':run.returncode,'output':run.stdout[-12000:],'error':run.stderr[-2500:]};out.append(item);(Q/'remaining-lever-results-20261014.json').write_text(json.dumps(out,indent=2));print(json.dumps(item),flush=True)

