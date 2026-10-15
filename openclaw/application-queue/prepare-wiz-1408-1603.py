import json,subprocess,sys,re,shutil,hashlib,time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path('/mnt/c/gecko_main');Q=ROOT/'openclaw/application-queue';cli='/home/dcall/.openclaw/bin/openclaw'
jid=sys.argv[1];p=json.loads((Q/jid/'application-package.json').read_text(encoding='utf-8'));target='retry-'+jid
answers=(ROOT/'openclaw/application-answers.md').read_text();assert 'mdavidcall@gmail.com' in answers and 'AUTH-01' in answers
master=(ROOT/'input/master-resume/master-resume-v2.txt').read_text();assert 'American Fork, UT' in master
assert jid in json.loads((Q/'batch-1408-1603-approved-ids.json').read_text())
old_path=Q/jid/'submission-result.json';old=json.loads(old_path.read_text()) if old_path.exists() else {};assert old.get('outcome')!='submitted'
from native_browser import call as native_call
def call(args):
 print('Job '+jid+': '+args[0],flush=True)
 return native_call(args)

def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def ref(s,role,name):
 hits=[k for k,v in s['refs'].items() if v['role']==role and v['name'].strip()==name]
 if len(hits)!=1:raise RuntimeError('Ambiguous or missing UI field: '+name)
 return hits[0]
def choose(name,value):
 s=snap();lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if 'combobox '+json.dumps(name,ensure_ascii=False) in x)
 if i+1<len(lines) and 'button "Toggle flyout"' in lines[i+1]:k=re.search(r'ref=(e\d+)',lines[i+1]).group(1)
 else:k=ref(s,'combobox',name)
 call(['click',k,'--target-id',target]);s=snap();k=ref(s,'option',value);call(['click',k,'--target-id',target])
def form():return call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,body:document.body.innerText,text:document.querySelector('form')?.innerText,files:Array.from(document.querySelectorAll('input[type=file]')).map(e=>({id:e.id,group:e.closest('[role=group]')?.innerText})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"] )['result']
def save(outcome,**extra):
 d={'job_id':jid,'company':p['company'],'job_title':p['job_title'],'outcome':outcome,'uploaded_filename':resume.name if 'resume' in globals() and uploaded else None,'timestamp':datetime.now(ZoneInfo('America/Denver')).isoformat(),'tracker_readback_result':'Not updated; submission not confirmed.'};d.update(extra);(Q/jid/'submission-result.json').write_text(json.dumps(d,indent=2)+'\n');print(json.dumps(d),flush=True)
uploaded=False
try:
 review=json.loads((Q/jid/'live-page-review.json').read_text());parent=review['result'];assert parent['url']==p['company_application_url'] and p['job_title'] in parent['text'];frames=[x for x in parent['frames'] if x['id']=='grnhse_iframe'];assert len(frames)==1;url=frames[0]['src'];from urllib.parse import urlparse,parse_qs;assert urlparse(url).hostname=='job-boards.greenhouse.io' and parse_qs(urlparse(url).query)['for']==['wizinc'];assert parse_qs(urlparse(url).query)['token']==parse_qs(urlparse(p['company_application_url']).query)['gh_jid'];opened=call(['open',url,'--label',target]);target=opened['targetId'];time.sleep(1);s=snap();f=form();assert p['job_title'] in f['title'] and 'Wiz' in f['title'];(Q/jid/'application-form-route.json').write_text(json.dumps({'parent_url':parent['url'],'form_url':url,'targetId':target,'company':'Wiz','job_id':jid},indent=2))
 (Q/jid/'form-before.json').write_text(json.dumps(f,indent=2))
 if not f.get('text'):raise RuntimeError('Application form not visible')
 supported=['First Name','Last Name','Email','Country','Phone','Location (City)','Resume/CV','LinkedIn Profile','Are you legally authorized to work in the country where this role is based without restriction?','Will you now or in the future require visa sponsorship?','Do you currently reside in a Central or Eastern Time Zone (U.S.)?','If selected for this role, will you require sponsorship in order to be employed?','Are you located within the United States of America?']
 unknown=[line.rstrip('*').strip() for line in f['text'].splitlines() if line.endswith('*') and line.rstrip('*').strip() not in supported]
 fields=[]
 for name,value in [('First Name','Dave'),('Last Name','Call'),('Email','mdavidcall@gmail.com'),('Phone','5305078269'),('LinkedIn Profile','https://www.linkedin.com/in/mdavidcall')]:
  hits=[k for k,v in s['refs'].items() if v['role']=='textbox' and v['name'].strip()==name]
  if len(hits)==1:fields.append({'ref':hits[0],'value':value})
 call(['fill','--target-id',target,'--fields',json.dumps(fields)])
 resume=Path(p['verified_resume_wsl_path']);assert resume.is_file();dest=Path('/tmp/openclaw/uploads')/resume.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(resume,dest);assert hashlib.sha256(resume.read_bytes()).digest()==hashlib.sha256(dest.read_bytes()).digest()
 files=[x for x in f['files'] if (x.get('group') or '').startswith('Resume/CV')];assert len(files)==1 and files[0]['id']=='resume'
 call(['upload',str(dest),'--target-id',target,'--element','#resume']);uploaded=True
 save('pending_assessment',blocking_questions=unknown);raise SystemExit(0)
 choose('Country','United States +1')
 s=snap();call(['type',ref(s,'combobox','Location (City)'),'American Fork','--slowly','--target-id',target]);s=snap();call(['click',ref(s,'option','American Fork, Utah, United States'),'--target-id',target])
 s=snap()
 for name,value in [('Are you legally authorized to work in the country where this role is based without restriction?','Yes'),('Will you now or in the future require visa sponsorship?','No'),('Do you currently reside in a Central or Eastern Time Zone (U.S.)?','No'),('If selected for this role, will you require sponsorship in order to be employed?','No'),('Are you located within the United States of America?','Yes')]:
  if any(v['role']=='combobox' and v['name'].strip()==name for v in s['refs'].values()):choose(name,value)
 f=form();assert resume.name in f['text'];assert 'American Fork, Utah, United States' in f['text'];assert not f['invalid']
 (Q/jid/'pre-submit-form.json').write_text(json.dumps(f,indent=2));s=snap();call(['click',ref(s,'button','Submit application'),'--target-id',target]);f=form()
 if str(f['url']).endswith('/confirmation'):
  result=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,text:document.body.innerText})"] )['result'];assert 'Your application has been received' in result['text'];save('submitted',confirmation_text=result['text'],confirmation_url=result['url'])
 elif 'verification code' in str(f.get('text','')).lower() or 'Security code' in str(f.get('text','')):save('verification_pending',verification_email='mdavidcall@gmail.com',application_url=f['url'])
 else:save('unconfirmed',application_url=f['url'],form_response=f.get('text'))
except SystemExit:raise
except Exception as e:save('blocked',blocker=str(e));raise SystemExit(1)
