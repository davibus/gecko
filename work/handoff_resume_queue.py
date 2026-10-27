"""One owned-worker handoff at a verified publication boundary, preserving work."""
import json,subprocess,time,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('C:/gecko_main');OUT=ROOT/'reports/resume-batch-20261025'
baseline=json.loads((OUT/'current-worker-identity.json').read_text(encoding='utf-8-sig'))
pid=int(baseline['ProcessId'])
def identity():
    command="Get-CimInstance Win32_Process -Filter 'ProcessId="+str(pid)+"' | Select-Object ProcessId,CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    return json.loads(result.stdout) if result.stdout.strip() else None
while True:
    if (OUT/'handoff.cancel').exists():raise SystemExit('Handoff canceled; no process touched')
    status=json.loads((OUT/'run-status.json').read_text(encoding='utf-8'))
    receipt=OUT/'completed-2975.json'
    if receipt.exists() and status.get('current_id')==2975 and status.get('stage')=='completed':break
    if identity() is None:raise SystemExit('Original worker exited before boundary; no process touched')
    time.sleep(1)
saved=json.loads(receipt.read_text(encoding='utf-8'))
assert saved['readback']['Resume Created']=='X' and saved['readback']['Resume Created Date'] and saved['qa']['word_pages']==saved['qa']['pdf_pages']==2
current=identity()
assert current is not None and all(current[k]==baseline[k] for k in ('ProcessId','CreationDate','ExecutablePath','CommandLine')), 'Worker identity changed; no process touched'
report={'trigger':'2975 completion and independent tracker readback confirmed','verified_owned_worker':current,'preserved_completed_ids':status['completed'],'at':datetime.now(timezone.utc).isoformat()}
result=subprocess.run(['taskkill.exe','/PID',str(pid),'/T','/F'],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
report['stop_exit_code']=result.returncode;report['stop_output']=result.stdout
assert result.returncode==0,'Owned worker stop unconfirmed; no replacement started'
for _ in range(20):
    if identity() is None:break
    time.sleep(.25)
else:raise RuntimeError('Owned worker still present; replacement not started')
with (OUT/'run-recovered.log').open('a',encoding='utf-8') as log:
    process=subprocess.Popen([str(ROOT/'.tools/dashboard-python/Scripts/python.exe'),str(ROOT/'work/run_all_qualifying_resumes.py')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    report['replacement_pid']=process.pid
    (OUT/'handoff-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'handoff':'complete','new_pid':process.pid,'verified_completed':len(status['completed'])}),flush=True)
    code=process.wait()
    report['replacement_exit_code']=code;report['finished_at']=datetime.now(timezone.utc).isoformat()
    (OUT/'handoff-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
