import json,subprocess,time
from pathlib import Path
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
ids=['1311', '1313', '1314', '1321', '1358', '1360', '1362', '1363', '1376', '1379', '1380', '1381', '1384', '1391', '1399', '1400']
for j in ids:
 deadline=time.monotonic()+600
 while not (q/j/'application-package.json').exists() and time.monotonic()<deadline:
  preflight=q/'batch-1311-1407-preflight.json'
  if preflight.exists() and any(r['id']==j and r['outcome']=='blocked' for r in json.loads(preflight.read_text())):break
  time.sleep(2)
 if not (q/j/'application-package.json').exists():print('Package unavailable: '+j,flush=True);continue
 e=q/j/'submission-result.json'
 if e.exists() and json.loads(e.read_text()).get('outcome')=='submitted':print('Already confirmed: '+j,flush=True);continue
 r=subprocess.run(['python3',str(q/'prepare-new-greenhouse.py'),j],capture_output=True,text=True,timeout=420);print(r.stdout or r.stderr,flush=True)
print('CONTACT AND MATCHING RESUME PASS COMPLETE',flush=True)
