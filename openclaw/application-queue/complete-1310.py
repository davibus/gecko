import json,subprocess,sys,re,time
from pathlib import Path
ROOT=Path('/mnt/c/gecko_main');Q=ROOT/'openclaw/application-queue';cli='/home/dcall/.openclaw/bin/openclaw';jid='1310';target='retry-'+jid
p=json.loads((Q/jid/'application-package.json').read_text());e=json.loads((Q/jid/'submission-result.json').read_text());assert e['outcome']=='pending_user'
assert 'Confirmed standing screening answers - 2026-10-13' in (ROOT/'openclaw/application-answers.md').read_text()
assert 'American Fork, UT' in (ROOT/'input/master-resume/master-resume-v2.txt').read_text()
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

s=snap();n=next(v['name'] for v in s['refs'].values() if v['role']=='textbox' and v['name'].startswith('In the last ~10 years'))
answer='Result Reach, approximately two years ago. I led brand at director level for a B2B SaaS business using a white-label GoHighLevel platform customized to each individual client company.'
call(['fill','--target-id',target,'--fields',json.dumps([{'ref':ref(s,'textbox',n),'value':answer}])])
r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,text:document.querySelector('form').innerText,inputs:Array.from(document.querySelectorAll('input,textarea')).map(e=>({value:e.value})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"]);f=r['result'];assert not f['invalid'];assert e['uploaded_filename'] in f['text'] and 'American Fork, Utah, United States' in f['text'];assert any(i['value']==answer for i in f['inputs'])
responses=json.loads((Q/jid/'confirmed-written-answers.json').read_text());assert all(any(i['value']==v for i in f['inputs']) for v in responses.values())
for prefix,value in [('Do you reside','Yes'),('Do you require visa','No')]:
 question=next(v['name'].strip() for v in s['refs'].values() if v['role']=='combobox' and v['name'].startswith(prefix));assert f['text'].split(question,1)[1].lstrip(' *\n').startswith(value)
(Q/jid/'pre-submit-form.json').write_text(json.dumps(r,indent=2));s=snap();call(['click',ref(s,'button','Submit application'),'--target-id',target]);r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,text:document.body.innerText})"]);f=r['result'];assert 'Security code' in f['text'] and 'verification code was sent to mdavidcall@gmail.com' in f['text'];e['outcome']='verification_pending';e.pop('blocking_questions',None);e.pop('unanswered_required_questions',None);(Q/jid/'submission-result.json').write_text(json.dumps(e,indent=2));print('1310 ready for fresh email verification',flush=True)
