import subprocess
from pathlib import Path
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['1358','1360','1362','1363']:
 print('START ANSWERED APPLICATION '+j,flush=True)
 r=subprocess.run(['python3','-u',str(q/'complete-known-next.py'),j],capture_output=True,text=True,timeout=300);print(r.stdout or r.stderr,flush=True)
print('ANSWERED APPLICATION PASS DONE',flush=True)
