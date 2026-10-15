import subprocess,json
from pathlib import Path
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
ids=['1295','1296','1297','1298','1299','1301','1302','1303','1304','1305','1306','1308','1309','1310']
for j in ids:
 if not (q/j/'application-package.json').exists():print('Package not available yet: '+j,flush=True);continue
 e=q/j/'submission-result.json'
 if e.exists() and json.loads(e.read_text()).get('outcome')=='submitted':print('Already confirmed: '+j,flush=True);continue
 r=subprocess.run(['python3',str(q/'prepare-batch-greenhouse.py'),j],capture_output=True,text=True,timeout=420);print(r.stdout or r.stderr,flush=True)
print('PREPARATION PASS COMPLETE',flush=True)
