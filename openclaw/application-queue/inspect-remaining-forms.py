import subprocess,json
from pathlib import Path
q=Path('/mnt/c/gecko_main/openclaw/application-queue');cli='/home/dcall/.openclaw/bin/openclaw'
for jid in ['1266','1267','1268']:
 p=json.loads((q/jid/'application-package.json').read_text());target='inspect-'+jid
 for args in [['open',p['company_application_url'],'--label',target],['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,text:document.querySelector('form')?.innerText})"]]:
  r=subprocess.run([cli,'browser']+args+['--json'],capture_output=True,text=True,timeout=90)
  if r.returncode:print(jid,r.stderr,flush=True);break
 else:
  d=json.loads(r.stdout)['result'];(q/jid/'form-inspection.json').write_text(json.dumps(d,indent=2));print(jid,json.dumps(d),flush=True)
