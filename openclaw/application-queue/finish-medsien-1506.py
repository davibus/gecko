from current_batch_ui import UI
from pathlib import Path
import json,time
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');j='1506';u=UI('retry-'+j);p=json.loads((Q/j/'application-package.json').read_text());e=json.loads((Q/j/'submission-result.json').read_text());assert e['outcome']=='pending_assessment'
u.choose('Country','United States +1');u.choose('School','Brigham Young University - Provo',search=True);u.choose('Degree',"Bachelor's Degree");u.choose('Discipline','Business');u.choose('Which US state do you live?','UT');u.fill({'What is your LinkedIn profile?':'https://www.linkedin.com/in/mdavidcall'})
s=u.snap()
for n,v in [('Start date year','2004'),('End date year','2008')]:u.call(['type',u.ref(s,'spinbutton',n),v]);u.call(['press','Tab'])
r=u.form();f=r['result'];assert f['url']==p['company_application_url'];assert e['uploaded_filename']==Path(p['verified_resume_wsl_path']).name and e['uploaded_filename'] in f['text'];assert not f['invalid'];assert all(x in f['text'] for x in ['Brigham Young University - Provo',"Bachelor's Degree",'Business','UT']);assert all(any(i['value']==v for i in f['inputs']) for v in ['2004','2008','https://www.linkedin.com/in/mdavidcall']);(Q/j/'pre-submit-form.json').write_text(json.dumps(r,indent=2));s=u.snap();u.call(['click',u.ref(s,'button','Submit application')]);time.sleep(1);r=u.call(['evaluate','--fn','() => ({url:location.href,title:document.title,text:document.body.innerText})']);f=r['result'];(Q/j/'after-submit-review.json').write_text(json.dumps(r,indent=2))
if 'Security code' in f['text']:e['outcome']='verification_pending'
elif f['url']==p['company_application_url']+'/confirmation' and f['title']=='Thank you for applying':e.update(outcome='submitted',confirmation_url=f['url'],confirmation_text=f['text']);(Q/j/'confirmation.json').write_text(json.dumps(r,indent=2))
else:raise RuntimeError(f['text'][-1200:])
e.pop('blocking_questions',None);(Q/j/'submission-result.json').write_text(json.dumps(e,indent=2));print(json.dumps({'id':j,'outcome':e['outcome']}))
