import json,subprocess,re
from pathlib import Path
cli='/home/dcall/.openclaw/bin/openclaw';target='retry-1267'
def call(args):
 r=subprocess.run([cli,'browser']+args+['--json'],capture_output=True,text=True,timeout=90)
 if r.returncode:raise RuntimeError(r.stderr or r.stdout)
 return json.loads(r.stdout)
def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def choose(prefix,value):
 s=snap();refs=s['refs'];hits=[(k,v['name']) for k,v in refs.items() if v['role']=='combobox' and v['name'].strip().startswith(prefix)];assert len(hits)==1
 k,name=hits[0];lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if f'[ref={k}]' in x);following=lines[i+1:];toggle=next(x for x in following if 'button "Toggle flyout"' in x);k=re.search(r'ref=(e\d+)',toggle).group(1)
 call(['click',k,'--target-id',target]);s=snap();opts=[(k,v['name']) for k,v in s['refs'].items() if v['role']=='option'];hits=[k for k,n in opts if n.strip()==value]
 if len(hits)!=1:print(json.dumps({'field':name,'options':opts}),flush=True);raise SystemExit(2)
 call(['click',hits[0],'--target-id',target]);print('Completed '+prefix,flush=True)

q=Path('/mnt/c/gecko_main/openclaw/application-queue/1267');pre=json.loads((q/'pre-submit-form.json').read_text())['result'];package=json.loads((q/'application-package.json').read_text());assert not pre['invalid'];assert Path(package['verified_resume_wsl_path']).name in pre['text'];assert any(x['value']=='70000' for x in pre['inputs']);assert any(x['value']=='No employee referred me.' for x in pre['inputs'])
s=snap();hits=[k for k,v in s['refs'].items() if v['role']=='button' and v['name']=='Submit application'];assert len(hits)==1;call(['click',hits[0],'--target-id',target]);r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,text:document.body.innerText})"]);(q/'post-submit-response.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
