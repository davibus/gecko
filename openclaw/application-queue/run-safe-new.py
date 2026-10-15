import subprocess,json
from pathlib import Path
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['1384','1381','1380']:
 print('START SAFE COMPLETION '+j,flush=True)
 r=subprocess.run(['python3','-u',str(q/'complete-safe-new.py'),j],capture_output=True,text=True,timeout=300);print(r.stdout or r.stderr,flush=True)
print('SAFE COMPLETION PASS DONE',flush=True)
