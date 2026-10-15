import json,socket,subprocess,time,uuid
from pathlib import Path
cli='/home/dcall/.openclaw/bin/openclaw'
root=Path('/mnt/c/gecko_main/openclaw/application-queue')
for attempt in range(12):
 try:
  with socket.create_connection(('127.0.0.1',18789),timeout=2): pass
  break
 except OSError:
  if attempt==11: raise SystemExit('Gateway did not become ready; no applications started.')
  if attempt%3==0: print('Waiting for the existing OpenClaw gateway to finish startup...',flush=True)
  time.sleep(4)
def call(args):
 r=subprocess.run([cli]+args,capture_output=True,text=True)
 try: d=json.loads(r.stdout)
 except ValueError: d={'error':r.stderr[-1800:] or r.stdout[-1800:]}
 return r.returncode,d
code,check=call(['agent','--agent','gecko-resume-application-assistant','--session-key','agent:gecko-resume-application-assistant:retry-check-'+uuid.uuid4().hex,'--message','Reply exactly GECKO_CONNECTION_OK. Do not call tools.','--timeout','120','--json'])
if code or check.get('status')!='ok':
 print(json.dumps(check)[:2500],flush=True);raise SystemExit('Connection check failed; no applications started.')
print('OpenAI connection verified through Gecko default model.',flush=True)
code,aborted=call(['gateway','call','chat.abort','--params',json.dumps({'sessionKey':'agent:gecko-resume-application-assistant:gecko-request-45d5479cc9644ba484fc1894847f1401','agentId':'gecko-resume-application-assistant','preserveSideRuns':True}),'--json'])
print('Old run stop result: '+json.dumps(aborted),flush=True)
if code: raise SystemExit('Could not verify old-run stop; no application retry started.')
print('Starting all six authorized applications sequentially.',flush=True)
code,result=call(['agent','--agent','gecko-resume-application-assistant','--session-key','agent:gecko-resume-application-assistant:retry-1262-1268-'+uuid.uuid4().hex,'--message-file',str(root/'batch-retry-1262-1268-20261012.txt'),'--timeout','1800','--json'])
(root/'batch-retry-20261012-result.json').write_text(json.dumps(result,indent=2)+'\n')
if result.get('result'): print(json.dumps(result['result'].get('payloads',[])),flush=True)
else: print(json.dumps(result)[:2500],flush=True)
raise SystemExit(code)
