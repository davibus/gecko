import json,time
from pathlib import Path
from native_browser import call
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');j='1391';T='retry-'+j
p=json.loads((Q/j/'application-package.json').read_text());e=json.loads((Q/j/'submission-result.json').read_text());assert e['outcome']=='pending_user';assert time.time()-(Q/j/'resume-submit-preflight.json').stat().st_mtime<180
s=call(['snapshot','--target-id',T,'--format','ai','--interactive','--compact'])
def ref(s,role,name):
 hits=[k for k,v in s['refs'].items() if v['role']==role and v['name'].strip()==name];assert len(hits)==1,(role,name);return hits[0]
k=ref(s,'checkbox','-Fewer than 100 employees');call(['click',k,'--target-id',T]);s=call(['snapshot','--target-id',T,'--format','ai','--interactive','--compact']);assert all('[checked]' in next(x for x in s['snapshot'].splitlines() if f'[ref={ref(s,"checkbox",name)}]' in x) for name in ['Career Growth','Culture','Company Outlook','-Fewer than 100 employees','Balanced mix of B2B and B2C','10 to 19 years'])
r=call(['evaluate','--target-id',T,'--fn',"() => ({url:location.href,text:document.querySelector('form').innerText,inputs:Array.from(document.querySelectorAll('input,textarea')).map(e=>({id:e.id,value:e.value,checked:e.checked}))})"]);f=r['result'];assert f['url']==p['company_application_url'];assert e['uploaded_filename']==Path(p['verified_resume_wsl_path']).name and e['uploaded_filename'] in f['text'];assert all(x in f['text'] for x in ['American Fork, Utah, United States',"Bachelor's Degree",'Brigham Young University - Provo','Business','Motive Careers Page']);assert any(i['value']=='mdavidcall@gmail.com' for i in f['inputs']);(Q/j/'pre-submit-form.json').write_text(json.dumps(r,indent=2))
call(['click',ref(s,'button','Submit application'),'--target-id',T]);time.sleep(1);r=call(['evaluate','--target-id',T,'--fn','() => ({url:location.href,title:document.title,text:document.body.innerText})']);f=r['result'];(Q/j/'after-submit-review.json').write_text(json.dumps(r,indent=2))
if 'Security code' in f['text'] and 'verification code was sent to mdavidcall@gmail.com' in f['text']:e['outcome']='verification_pending'
elif f['url']==p['company_application_url']+'/confirmation' and f['title']=='Thank you for applying':e.update(outcome='submitted',confirmation_url=f['url'],confirmation_text=f['text']);(Q/j/'confirmation.json').write_text(json.dumps(r,indent=2))
else:raise RuntimeError('Submission needs review: '+f['text'][-1500:])
e.pop('blocking_questions',None);(Q/j/'submission-result.json').write_text(json.dumps(e,indent=2));print(json.dumps({'job_id':j,'outcome':e['outcome']}))
