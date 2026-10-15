import subprocess
from pathlib import Path
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['1594','1598','1603']:
 r=subprocess.run(['python3',str(q/'prepare-wiz-1408-1603.py'),j],capture_output=True,text=True,timeout=240);print(r.stdout or r.stderr,flush=True)
