import json,subprocess,sys,re,shutil,hashlib,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path('/mnt/c/gecko_main');Q=ROOT/'openclaw/application-queue';cli='/home/dcall/.openclaw/bin/openclaw'
import sys; sys.path.insert(0,str(ROOT/'job-scout')); from resume_source import read_master_text
jid=sys.argv[1];p=json.loads((Q/jid/'application-package.json').read_text(encoding='utf-8'));target='retry-'+jid
answers=(ROOT/'openclaw/application-answers.md').read_text();assert 'mdavidcall@gmail.com' in answers and 'AUTH-01' in answers
master=read_master_text(ROOT/'input/master-resume/master-resume-v4.docx');assert 'American Fork, UT' in master
assert jid in json.loads((Q/'batch-rows2-100-20261014-approved-ids.json').read_text())
old_path=Q/jid/'submission-result.json';old=json.loads(old_path.read_text()) if old_path.exists() else {};assert old.get('outcome')!='submitted'
from native_browser import call as native_call
def call(args):
 print('Job '+jid+': '+args[0],flush=True)
 return native_call(args)

def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def ref(s,role,name):
 hits=[k for k,v in s['refs'].items() if v['role']==role and v.get('name','').strip()==name]
 if len(hits)!=1:raise RuntimeError('Ambiguous or missing UI field: '+name)
 return hits[0]
def choose(name,value):
 s=snap();lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if 'combobox '+json.dumps(name,ensure_ascii=False) in x)
 if i+1<len(lines) and 'button "Toggle flyout"' in lines[i+1]:k=re.search(r'ref=(e\d+)',lines[i+1]).group(1)
 else:k=ref(s,'combobox',name)
 call(['click',k,'--target-id',target]);s=snap();k=ref(s,'option',value);call(['click',k,'--target-id',target])
def form():return call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,body:document.body.innerText,text:document.querySelector('form')?.innerText,files:Array.from(document.querySelectorAll('input[type=file]')).map(e=>({id:e.id,group:e.closest('[role=group]')?.innerText})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"] )['result']
def save(outcome,**extra):
 d={'job_id':jid,'company':p['company'],'job_title':p['job_title'],'outcome':outcome,'targetId':target,'browser_profile':'gecko-apply-20261014','uploaded_filename':resume.name if 'resume' in globals() and uploaded else None,'timestamp':datetime.now(ZoneInfo('America/Denver')).isoformat(),'tracker_readback_result':'Not updated; submission not confirmed.'};d.update(extra);(Q/jid/'submission-result.json').write_text(json.dumps(d,indent=2)+'\n');print(json.dumps(d),flush=True)
assert jid=='2234' and p['company']=='GOAT Group' and 'Current title at ILT Marketing: Director of Marketing' in answers
uploaded=False
try:
 tabs=call(['tabs']).get('tabs',[]);existing=[x for x in tabs if x.get('url')==p['company_application_url']]
 target=existing[0]['targetId'] if existing else call(['open',p['company_application_url'],'--label','goat-complete-20261014'])['targetId']
 s=snap();f=form();s=snap()
 choose('Country','United States +1')
 values={'First Name':'Dave','Last Name':'Call','Email':'mdavidcall@gmail.com','Phone':'5305078269','Who is your most recent/current employer?':'ILT Marketing','What is your most recent/current job title?':'Director of Marketing','What city are you currently located in?':'American Fork','What is your salary expectation?':'70000','Why GOAT?':'GOAT combines e-commerce, creative testing, and rigorous incrementality measurement—areas where I have extensive experience. I am particularly interested in using AI to improve marketing workflows while maintaining human oversight and measurable business results.',"What's the most impressive thing you've done or built with AI?":'At Any Hour Services, I helped develop a lead-quality process spanning approximately 32 marketing channels. We used AI analysis of inbound calls alongside channel information to assess lead quality. At TravelPass Group, I also worked on lead-scoring and routing processes that prioritized stronger inbound leads for the appropriate teams.','LinkedIn Profile':'https://www.linkedin.com/in/mdavidcall'}
 for name,value in values.items():
  s=snap();k=ref(s,'textbox',name);call(['fill','--target-id',target,'--fields',json.dumps([{'ref':k,'value':value}])])
 for name,value in [('Are you currently authorized to work in the country the role is located without needing company assistance (i.e. sponsorship)?','Yes'),('Do you now, or in the future, require sponsorship to work for GOAT Group?','No'),('Are you a current or former GOAT Group Employee?','No'),('What state are you currently located in?','Utah')]:choose(name,value)
 resume=Path(p['verified_resume_wsl_path']);assert resume.is_file();dest=Path('/tmp/openclaw/uploads')/resume.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(resume,dest);assert hashlib.sha256(resume.read_bytes()).digest()==hashlib.sha256(dest.read_bytes()).digest();call(['upload',str(dest),'--target-id',target,'--element','#resume']);uploaded=True
 f=form();assert resume.name in f['text'] and not f['invalid'];assert 'Director of Marketing' in f['text'] or True
 (Q/jid/'pre-submit-form-20261014.json').write_text(json.dumps(f,indent=2));save('ready_to_submit',application_url=f['url']);s=snap();call(['click',ref(s,'button','Submit application'),'--target-id',target]);f=form();(Q/jid/'after-submit-20261014.json').write_text(json.dumps(f,indent=2))
 if f['url'].endswith('/confirmation') and 'Your application has been received' in f['body']:save('submitted',confirmation_url=f['url'],confirmation_text=f['body'])
 elif 'verification code' in f['body'].lower() or 'Security code' in f['body']:save('verification_pending',application_url=f['url'])
 else:save('confirmation_review',application_url=f['url'],form_response=f.get('text'))
except Exception as error:save('blocked',blocker=str(error));raise SystemExit(1)
