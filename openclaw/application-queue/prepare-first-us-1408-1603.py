import subprocess,json
from pathlib import Path
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['1431','1441','1447','1477','1499','1506','1509','1524']:
 r=subprocess.run(['python3',str(q/'prepare-current-1408-1603.py'),j],capture_output=True,text=True,timeout=240);print(r.stdout or r.stderr,flush=True)
print('FIRST US DRAFT PASS COMPLETE',flush=True)
