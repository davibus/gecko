import json,subprocess,re
from pathlib import Path
cli='/home/dcall/.openclaw/bin/openclaw';target='retry-1262'
def call(args):
 r=subprocess.run([cli,'browser']+args+['--json'],capture_output=True,text=True,timeout=90)
 if r.returncode:raise RuntimeError(r.stderr or r.stdout)
 return json.loads(r.stdout)
def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def choose(name,value):
 s=snap();lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if 'combobox '+json.dumps(name,ensure_ascii=False) in x)
 k=re.search(r'ref=(e\d+)',lines[i+1]).group(1)
 call(['click',k,'--target-id',target]);s=snap();hits=[k for k,v in s['refs'].items() if v['role']=='option' and v['name']==value];assert len(hits)==1
 call(['click',hits[0],'--target-id',target])
r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,text:document.querySelector('form').innerText,invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"])
q=Path('/mnt/c/gecko_main/openclaw/application-queue/1262');(q/'pending-form.json').write_text(json.dumps(r,indent=2));e=json.loads((q/'submission-result.json').read_text());e['blocking_questions']=['Are you willing and able to travel approximately 25–30% for this role?'];(q/'submission-result.json').write_text(json.dumps(e,indent=2));print(json.dumps(r))
