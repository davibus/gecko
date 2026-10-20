import json,subprocess,re,sys
from pathlib import Path
ROOT=Path('/mnt/c/gecko_main');Q=ROOT/'openclaw/application-queue';cli='/home/dcall/.openclaw/bin/openclaw';jid=sys.argv[1];target='retry-'+jid
import sys; sys.path.insert(0,str(ROOT/'job-scout')); from resume_source import read_master_text
assert jid in ['1276','1277'];p=json.loads((Q/jid/'application-package.json').read_text());assert json.loads((Q/jid/'submission-result.json').read_text())['outcome']!='submitted'
answers=(ROOT/'openclaw/application-answers.md').read_text();assert 'User agrees to the linked EFE' in answers and 'No applications to Edelman Financial Engines before' in answers;master=read_master_text(ROOT/'input/master-resume/master-resume-v4.docx');assert 'American Fork, UT' in master
prior=[]
for j in ['1275','1276']:
 if j==jid:continue
 e=json.loads((Q/j/'submission-result.json').read_text());pp=json.loads((Q/j/'application-package.json').read_text())
 if e['outcome']=='submitted':assert e['confirmation_url']==pp['company_application_url']+'/confirmation';prior.append(pp['job_title'])
assert prior
history='October 12, 2026: '+ '; '.join(prior)+'. Remote roles; applying from American Fork, UT.'
def call(args):
 r=subprocess.run([cli,'browser']+args+['--json'],capture_output=True,text=True,timeout=90)
 if r.returncode:raise RuntimeError(r.stderr or r.stdout)
 return json.loads(r.stdout)
def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def ref(s,role,name):
 hits=[k for k,v in s['refs'].items() if v['role']==role and v['name'].strip()==name];assert len(hits)==1,(role,name);return hits[0]
s=snap();call(['type',ref(s,'combobox','Location (City)'),'American Fork','--slowly','--target-id',target]);s=snap();call(['click',ref(s,'option','American Fork, Utah, United States'),'--target-id',target]);
values=[('How did you hear about EFE and/or this role?',"EFE's Careers Page"),('What is your home state?','Utah'),('Do you have the unrestricted right to work in the United States?','Yes'),('Will you now or in the future require sponsorship for employment visa status (i.e. H-1B, EAD, OPT, TN, etc.)?','No'),('Are you related to anyone presently employed by Edelman Financial Engines?','No'),('Have you ever been employed by Edelman Financial Engines, Edelman Financial Services, Financial Engines, or The Mutual Fund Store?','No'),('Have you previously applied for employment with Edelman Financial Engines?','Yes'),('Are you subject to any non-compete or non-solicitation agreements?','No'),('Do you need any accommodations to perform the job for which you are applying?','No'),('Are you involved in any Outside Business Activities (i.e. selling nonregistered insurance products or real estate, acting as a consultant, CPA, tax preparer, second jobs, or online social networking websites used with/for such activities)?','No'),('Have you ever been involuntarily terminated or asked to resign from an employer?','Yes')]
r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,text:document.querySelector('form').innerText,inputs:Array.from(document.querySelectorAll('input,textarea')).filter(e=>e.type!=='hidden').map(e=>({id:e.id,value:e.value})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"])
(Q/jid/'pre-submit-form.json').write_text(json.dumps(r,indent=2));f=r['result'];assert not f['invalid'];assert Path(p['verified_resume_wsl_path']).name in f['text'];assert 'American Fork, Utah, United States' in f['text'];assert 'I Agree' in f['text'];assert any(x['value']=='70000' for x in f['inputs']);assert any(x['value']==history for x in f['inputs'])
for name,value in values[1:]:
 block=f['text'].split(name+'*',1);assert len(block)==2,name;after=block[1].strip();assert after.startswith(value),name+' selection mismatch'
s=snap();call(['click',ref(s,'button','Submit application'),'--target-id',target]);r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,text:document.body.innerText})"]);(Q/jid/'post-submit-response.json').write_text(json.dumps(r,indent=2));print(json.dumps({'job_id':jid,'url':r['result']['url'],'response_tail':r['result']['text'][-850:]}),flush=True)
