import json,subprocess,sys,re,time
from pathlib import Path
ROOT=Path('/mnt/c/gecko_main');Q=ROOT/'openclaw/application-queue';cli='/home/dcall/.openclaw/bin/openclaw';jid='1310';target='retry-'+jid
import sys; sys.path.insert(0,str(ROOT/'job-scout')); from resume_source import read_master_text
p=json.loads((Q/jid/'application-package.json').read_text());e=json.loads((Q/jid/'submission-result.json').read_text());assert e['outcome']=='pending_user'
assert 'Confirmed standing screening answers - 2026-10-13' in (ROOT/'openclaw/application-answers.md').read_text()
assert 'American Fork, UT' in read_master_text(ROOT/'input/master-resume/master-resume-v4.docx')
def call(args):
 for attempt in range(4):
  r=subprocess.run([cli,'browser']+args+['--json'],capture_output=True,text=True,timeout=90)
  if not r.returncode:return json.loads(r.stdout)
  if 'getaddrinfo' not in r.stderr+r.stdout:raise RuntimeError(r.stderr or r.stdout)
  print(jid+': Temporary DNS failure; retry',flush=True);time.sleep(2*(attempt+1))
 raise RuntimeError(r.stderr or r.stdout)
def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def ref(s,role,name):
 hits=[k for k,v in s['refs'].items() if v['role']==role and v['name'].strip()==name];assert len(hits)==1,(role,name);return hits[0]

def choose_prefix(name,prefix):
 s=snap();k=ref(s,'combobox',name);lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if f'[ref={k}]' in x);k=re.search(r'ref=(e\d+)',next(x for x in lines[i+1:] if 'button "Toggle flyout"' in x)).group(1);call(['click',k,'--target-id',target]);s=snap();hits=[k for k,v in s['refs'].items() if v['role']=='option' and v['name'].startswith(prefix)];assert len(hits)==1, json.dumps({'field':name,'wanted_prefix':prefix,'options':[v['name'] for v in s['refs'].values() if v['role']=='option']});call(['click',hits[0],'--target-id',target])

call(['press','Escape','--target-id',target])
choose_prefix('Country','United States +1')
s=snap();call(['type',ref(s,'combobox','Location (City)'),'American Fork','--slowly','--target-id',target]);s=snap();call(['click',ref(s,'option','American Fork, Utah, United States'),'--target-id',target]);print('1310 location verified',flush=True)
s=snap();names=[v['name'].strip() for v in s['refs'].values() if v['role']=='combobox'];acts=[]
for prefix,value in [('Do you reside','Yes'),('Do you require visa','No')]:
 n=next(n for n in names if n.startswith(prefix));acts.append({'kind':'type','ref':ref(s,'combobox',n),'text':value,'slowly':True,'submit':True})
responses=json.loads((Q/jid/'confirmed-written-answers.json').read_text());names=[v['name'].strip() for v in s['refs'].values() if v['role']=='textbox'];fields=[]
for prefix,value in responses.items():
 n=next(n for n in names if n.startswith(prefix));fields.append({'ref':ref(s,'textbox',n),'value':value})
fields.append({'ref':ref(s,'textbox','LinkedIn profile'),'value':'https://www.linkedin.com/in/mdavidcall'});acts.append({'kind':'fill','fields':fields});call(['batch','--target-id',target,'--actions',json.dumps(acts)])
r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,text:document.querySelector('form').innerText,inputs:Array.from(document.querySelectorAll('input,textarea')).map(e=>({value:e.value})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"]);f=r['result'];assert e['uploaded_filename'] in f['text'];assert all(any(i['value']==v for i in f['inputs']) for v in responses.values());(Q/jid/'draft-after-answers.json').write_text(json.dumps(r,indent=2));e['unanswered_required_questions']=['Exact B2B SaaS/tech company name and Director+ brand leadership within the last ten years.'];(Q/jid/'submission-result.json').write_text(json.dumps(e,indent=2));print('1310 draft saved; only company-name response remains.',flush=True)
