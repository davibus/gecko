import json,subprocess,re,sys
from pathlib import Path
ROOT=Path('/mnt/c/gecko_main');Q=ROOT/'openclaw/application-queue';cli='/home/dcall/.openclaw/bin/openclaw';jid=sys.argv[1];target='retry-'+jid
import sys; sys.path.insert(0,str(ROOT/'job-scout')); from resume_source import read_master_text
assert jid in ['1275','1276','1277'];p=json.loads((Q/jid/'application-package.json').read_text());assert json.loads((Q/jid/'submission-result.json').read_text())['outcome']!='submitted'
answers=(ROOT/'openclaw/application-answers.md').read_text();assert 'AUTH-01' in answers and 'AUTH-02' in answers;master=read_master_text(ROOT/'input/master-resume/master-resume-v4.docx');assert 'American Fork, UT' in master
def call(args):
 r=subprocess.run([cli,'browser']+args+['--json'],capture_output=True,text=True,timeout=90)
 if r.returncode:raise RuntimeError(r.stderr or r.stdout)
 return json.loads(r.stdout)
def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def ref(s,role,name):
 hits=[k for k,v in s['refs'].items() if v['role']==role and v['name'].strip()==name];assert len(hits)==1,(role,name);return hits[0]
def choose(name,value):
 s=snap();k=ref(s,'combobox',name);lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if f'[ref={k}]' in x);k=re.search(r'ref=(e\d+)',next(x for x in lines[i+1:] if 'button "Toggle flyout"' in x)).group(1)
 call(['click',k,'--target-id',target]);s=snap();opts=[(k,v['name']) for k,v in s['refs'].items() if v['role']=='option'];hits=[k for k,n in opts if n.strip()==value]
 if len(hits)!=1:print(json.dumps({'job_id':jid,'field':name,'options':opts}),flush=True);raise SystemExit(2)
 call(['click',hits[0],'--target-id',target]);print(jid+': '+name+' = '+value,flush=True)
call(['press','Escape','--target-id',target])
s=snap();call(['type',ref(s,'textbox','What is your preferred work location (city/state)?'),'American Fork, UT (remote)','--target-id',target])
choose('Country','United States +1');s=snap();call(['type',ref(s,'combobox','Location (City)'),'American Fork','--slowly','--target-id',target]);s=snap();call(['click',ref(s,'option','American Fork, Utah, United States'),'--target-id',target]);print(jid+': City completed',flush=True)
for name,value in [('How did you hear about EFE and/or this role?',"EFE's Careers Page"),('What is your home state?','Utah'),('Do you have the unrestricted right to work in the United States?','Yes'),('Will you now or in the future require sponsorship for employment visa status (i.e. H-1B, EAD, OPT, TN, etc.)?','No')]:choose(name,value)
r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,text:document.querySelector('form').innerText,inputs:Array.from(document.querySelectorAll('input,textarea')).filter(e=>e.type!=='hidden').map(e=>({id:e.id,value:e.value})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"])
(Q/jid/'pending-form.json').write_text(json.dumps(r,indent=2));print(jid+': Known fields complete; awaiting user screening answers',flush=True)
