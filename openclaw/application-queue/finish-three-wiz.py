from current_batch_ui import UI
from pathlib import Path
import json,time
Q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['1594','1598','1603']:
 p=json.loads((Q/j/'application-package.json').read_text());e=json.loads((Q/j/'submission-result.json').read_text());route=json.loads((Q/j/'application-form-route.json').read_text());u=UI(route['targetId']);
 if e['outcome']!='pending_assessment':continue
 print('Completing '+j,flush=True)
 u.choose('Country','United States +1');u.choose('Are you legally authorized to work in the country in which this role is located?','Yes');u.choose('Please select the state where you currently reside','Utah');u.choose('Will you now or in the future require sponsorship for employment visa status (e.g., H-1B visa)?','No');u.choose('Have you ever been an Employee, Intern, Student Ambassador, Fellow, Student Researcher, Bet/M&A Employee, Temp, Vendor, or Contractor of Alphabet?','No');u.fill({'What is your current company?':'ILT Marketing'})
 r=u.form();f=r['result'];assert f['url']==route['form_url'] and p['job_title'] in f['title'] and 'Wiz' in f['title'];assert e['uploaded_filename']==Path(p['verified_resume_wsl_path']).name and e['uploaded_filename'] in f['text'];assert not f['invalid'];assert 'Utah' in f['text'];(Q/j/'pre-submit-form.json').write_text(json.dumps(r,indent=2));s=u.snap();u.call(['click',u.ref(s,'button','Submit application')]);time.sleep(1);r=u.call(['evaluate','--fn','() => ({url:location.href,title:document.title,text:document.body.innerText})']);f=r['result'];(Q/j/'after-submit-review.json').write_text(json.dumps(r,indent=2))
 if 'Security code' in f['text']:e['outcome']='verification_pending'
 elif 'Thank you for applying' in f['title'] or 'Thank you for applying' in f['text']:e.update(outcome='confirmation_review',confirmation_url=f['url'],confirmation_text=f['text']);(Q/j/'confirmation.json').write_text(json.dumps(r,indent=2))
 else:raise RuntimeError(f['text'][-1200:])
 e.pop('blocking_questions',None);(Q/j/'submission-result.json').write_text(json.dumps(e,indent=2));print(json.dumps({'id':j,'outcome':e['outcome'],'response_url':f['url']}),flush=True)
