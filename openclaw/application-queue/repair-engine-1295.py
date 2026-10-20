import json,subprocess,sys,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path('/mnt/c/gecko_main');Q=ROOT/'openclaw/application-queue';cli='/home/dcall/.openclaw/bin/openclaw';jid=sys.argv[1];target='retry-'+jid
import sys; sys.path.insert(0,str(ROOT/'job-scout')); from resume_source import read_master_text
assert jid in ['1295','1296','1297','1298','1299'];p=json.loads((Q/jid/'application-package.json').read_text());e=json.loads((Q/jid/'submission-result.json').read_text());assert p['company']=='Engine' and e['outcome']=='blocked';assert e['uploaded_filename']==Path(p['verified_resume_wsl_path']).name
answers=(ROOT/'openclaw/application-answers.md').read_text();assert '$70,000' in answers and 'AUTH-01' in answers;master=read_master_text(ROOT/'input/master-resume/master-resume-v4.docx');assert 'American Fork, UT' in master
known=['What are your salary expectations?','Would you, now or in the future, require immigration sponsorship for work authorization?','Are you legally authorized to work in the country where this position is based?'];assert set(e['blocking_questions'])==set(known) or (jid=='1297' and set(e['blocking_questions'])==set(known+['How many years of experience do you have?']))
def call(args):
 r=subprocess.run([cli,'browser']+args+['--json'],capture_output=True,text=True,timeout=90)
 if r.returncode:raise RuntimeError(r.stderr or r.stdout)
 return json.loads(r.stdout)
def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def ref(s,role,name):
 hits=[k for k,v in s['refs'].items() if v['role']==role and v['name'].strip()==name];assert len(hits)==1,(role,name);return hits[0]

def choose_prefix(name,prefix):
 s=snap();k=ref(s,'combobox',name);lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if f'[ref={k}]' in x);k=re.search(r'ref=(e\d+)',next(x for x in lines[i+1:] if 'button "Toggle flyout"' in x)).group(1);call(['click',k,'--target-id',target]);s=snap();hits=[k for k,v in s['refs'].items() if v['role']=='option' and v['name'].startswith(prefix)];assert len(hits)==1;call(['click',hits[0],'--target-id',target])
call(['click','e40','--target-id',target])
r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,text:document.querySelector('form').innerText,inputs:Array.from(document.querySelectorAll('input,textarea')).filter(e=>e.type!=='hidden').map(e=>({id:e.id,value:e.value})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"]);f=r['result'];(Q/jid/'pre-submit-form.json').write_text(json.dumps(r,indent=2));assert not f['invalid'] and e['uploaded_filename'] in f['text'] and 'American Fork, Utah, United States' in f['text'];assert any(x['value']=='70000' for x in f['inputs']);assert f['text'].split(known[1]+'*',1)[1].strip().startswith(('No','option No'));assert f['text'].split(known[2]+'*',1)[1].strip().startswith(('Yes','option Yes'))
s=snap();call(['click',ref(s,'button','Submit application'),'--target-id',target]);r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,text:document.body.innerText})"]);c=r['result'];e['timestamp']=datetime.now(ZoneInfo('America/Denver')).isoformat()
if c['url']==p['company_application_url']+'/confirmation' and 'Your application has been received' in c['text']:e.update(outcome='submitted',confirmation_url=c['url'],confirmation_text=c['text']);(Q/jid/'confirmation.json').write_text(json.dumps(r,indent=2))
elif 'Security code' in c['text'] and 'verification code was sent to mdavidcall@gmail.com' in c['text']:e.update(outcome='verification_pending',verification_email='mdavidcall@gmail.com')
else:e.update(outcome='unconfirmed',blocker=c['text'][-1500:])
e.pop('blocking_questions',None);(Q/jid/'submission-result.json').write_text(json.dumps(e,indent=2));print(json.dumps({'job_id':jid,'outcome':e['outcome'],'url':c['url']}),flush=True)
