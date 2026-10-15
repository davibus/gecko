import subprocess,json,sys
from pathlib import Path
q=Path('/mnt/c/gecko_main/openclaw/application-queue')
args=json.loads((q/'browser-action-args.json').read_text())
commands=args if args and isinstance(args[0],list) else [args]
for command in commands:
 r=subprocess.run(['/home/dcall/.openclaw/bin/openclaw','browser']+command,capture_output=True,text=True,timeout=90)
 if r.returncode: break
(q/'browser-last-response.json').write_text(r.stdout or json.dumps({'stderr':r.stderr,'exit':r.returncode}))
try:
 d=json.loads(r.stdout)
 if 'snapshot' in d:
  print(d.get('url',''));print(d['snapshot'])
 else:print(json.dumps(d))
except ValueError:print(r.stderr or r.stdout)
raise SystemExit(r.returncode)
