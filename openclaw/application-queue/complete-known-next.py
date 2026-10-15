import json,subprocess,sys,re,time
from pathlib import Path
ROOT=Path('/mnt/c/gecko_main');Q=ROOT/'openclaw/application-queue';cli='/home/dcall/.openclaw/bin/openclaw';jid=sys.argv[1];target='retry-'+jid
p=json.loads((Q/jid/'application-package.json').read_text());e=json.loads((Q/jid/'submission-result.json').read_text());assert e['outcome']=='pending_assessment'
assert 'Confirmed standing screening answers - 2026-10-13' in (ROOT/'openclaw/application-answers.md').read_text()
assert 'American Fork, UT' in (ROOT/'input/master-resume/master-resume-v2.txt').read_text()
from native_browser import call

def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def ref(s,role,name):
 hits=[k for k,v in s['refs'].items() if v['role']==role and v['name'].strip()==name];assert len(hits)==1,(role,name);return hits[0]

def choose_prefix(name,prefix):
 s=snap();k=ref(s,'combobox',name);lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if f'[ref={k}]' in x);k=re.search(r'ref=(e\d+)',next(x for x in lines[i+1:] if 'button "Toggle flyout"' in x)).group(1);call(['click',k,'--target-id',target]);s=snap();hits=[k for k,v in s['refs'].items() if v['role']=='option' and v['name'].startswith(prefix)];assert len(hits)==1, json.dumps({'field':name,'wanted_prefix':prefix,'options':[v['name'] for v in s['refs'].values() if v['role']=='option']});call(['click',hits[0],'--target-id',target])

plans=json.loads((Q/'known-next-plans.json').read_text());assert jid in plans;plan=plans[jid];assert e['uploaded_filename']==Path(p['verified_resume_wsl_path']).name
call(['press','Escape','--target-id',target]);s=snap()
if any(v['role']=='combobox' and v['name'].strip()=='Country' for v in s['refs'].values()):choose_prefix('Country','United States +1')
s=snap();city=any(v['role']=='combobox' and v['name'].strip()=='Location (City)' for v in s['refs'].values())
if city:
 call(['type',ref(s,'combobox','Location (City)'),'American Fork','--slowly','--target-id',target]);time.sleep(1);s=snap();call(['click',ref(s,'option','American Fork, Utah, United States'),'--target-id',target])
s=snap();acts=[];fields=[];combo_answers={};texts=[]
for prefix,value in plan.items():
 hits=[(k,v) for k,v in s['refs'].items() if v['role'] in ['textbox','combobox'] and v.get('name','').strip().startswith(prefix)];assert hits,prefix
 if len(hits)>1:assert all(v['role']=='textbox' for k,v in hits)
 for k,v in hits:
  if v['role']=='textbox':fields.append({'ref':k,'value':value});texts.append(value)
  else:acts.append({'kind':'type','ref':k,'text':value,'slowly':True,'submit':True});combo_answers[v['name'].strip()]=value
if fields:acts.append({'kind':'fill','fields':fields})
call(['batch','--target-id',target,'--actions',json.dumps(acts)])
if '--draft' in sys.argv:
 (Q/jid/'snapshot-draft.json').write_text(json.dumps(snap(),indent=2));print(json.dumps({'id':jid,'outcome':'draft_updated'}));sys.exit(0)
r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,text:document.querySelector('form').innerText,inputs:Array.from(document.querySelectorAll('input,textarea')).map(e=>({value:e.value})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"]);f=r['result'];assert not f['invalid'] and e['uploaded_filename'] in f['text'];assert all(any(i['value']==v for i in f['inputs']) for v in texts)
if city:assert 'American Fork, Utah, United States' in f['text']
for name,value in combo_answers.items():assert f['text'].split(name,1)[1].lstrip(' *\n').startswith((value,'option '+value)),(name,value)
(Q/jid/'pre-submit-form.json').write_text(json.dumps(r,indent=2));s=snap();call(['click',ref(s,'button','Submit application'),'--target-id',target]);time.sleep(1);r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,text:document.body.innerText})"]);f=r['result']
if 'Security code' in f['text'] and 'verification code was sent to mdavidcall@gmail.com' in f['text']:e['outcome']='verification_pending'
elif f['url']==p['company_application_url']+'/confirmation' and ('Your application has been received' in f['text'] or 'We have received your application' in f['text']):e.update(outcome='submitted',confirmation_url=f['url'],confirmation_text=f['text']);(Q/jid/'confirmation.json').write_text(json.dumps(r,indent=2))
else:raise RuntimeError('Submission not confirmed: '+f['text'][-700:])
e.pop('blocking_questions',None);e.pop('unanswered_required_questions',None);(Q/jid/'submission-result.json').write_text(json.dumps(e,indent=2));print(json.dumps({'id':jid,'outcome':e['outcome']}),flush=True)
