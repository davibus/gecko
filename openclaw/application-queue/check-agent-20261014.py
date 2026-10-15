import subprocess,json,uuid
cli='/home/dcall/.openclaw/bin/openclaw'
r=subprocess.run([cli,'agent','--agent','gecko-resume-application-assistant','--session-key','agent:gecko-resume-application-assistant:rows2-100-check-'+uuid.uuid4().hex,'--message','Reply exactly GECKO_CONNECTION_OK. Do not call tools.','--timeout','120','--json'],capture_output=True,text=True,timeout=150)
try:d=json.loads(r.stdout)
except ValueError:d={}
print(json.dumps({'exit_code':r.returncode,'connection_ok':'GECKO_CONNECTION_OK' in r.stdout,'status':d.get('status'),'error':d.get('error'),'stderr_tail':r.stderr[-900:]}))
