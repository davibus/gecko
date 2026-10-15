import subprocess,json,time
from pathlib import Path
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['1297','1298','1299','1301','1303']:
 print('START COMPLETION '+j,flush=True)
 p=subprocess.Popen(['python3','-u',str(q/'finish-known-batch.py'),j],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 for line in p.stdout:print(line,end='',flush=True)
 p.wait();e=json.loads((q/j/'submission-result.json').read_text())
 if e.get('outcome')=='verification_pending':
  print('READY FOR EMAIL VERIFICATION '+j,flush=True)
  deadline=time.monotonic()+180
  while time.monotonic()<deadline:
   e=json.loads((q/j/'submission-result.json').read_text())
   if e.get('outcome')=='submitted':break
   time.sleep(1)
  print('Verification gate result '+j+': '+e['outcome'],flush=True)
print('KNOWN-ANSWER COMPLETION PASS DONE',flush=True)
