from current_batch_ui import UI
from pathlib import Path
import json,time
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');a=json.loads((Q/'polished-answers-1408-1603.json').read_text())
for j in ['1441','1447']:
 u=UI('retry-'+j);p=json.loads((Q/j/'application-package.json').read_text());e=json.loads((Q/j/'submission-result.json').read_text());assert e['outcome']=='pending_assessment';print('Completing '+j,flush=True)
 u.choose('Country','United States +1');u.choose('What is your current location?','United States of America',search=True);u.choose('Have you interviewed with Power Digital in the past 3 years?','No');u.choose('Do you have experience in a client-facing position at a digital marketing agency?','Yes');u.choose('Which account type is your primary specialty? Please select one.','Lifestyle (eCommerce)');u.choose('Do you have experience working at a digital marketing agency?','Yes');u.choose('Are you legally authorized to work in the United States?','Yes');u.choose('Which of the following best describes your CPG or eCommerce marketing experience?','I have worked across DTC and at least one of the following: retail media, Amazon, or omnichannel strategy')
 s=u.snap();fields={}
 for k,v in s['refs'].items():
  n=v.get('name','').strip()
  if v['role']=='textbox':
   if n.startswith('Please drop a link'):fields[n]='https://www.linkedin.com/in/mdavidcall'
   if n.startswith('What is your desired annual'):fields[n]='70000'
   if n.startswith('Tell us about a CPG'):fields[n]=a['cross_channel']
   if n.startswith('How do you coordinate'):fields[n]='I would align paid, influencer, creative, and content teams around one audience, value proposition, and measurable goal. '+a['cross_functional']
 u.fill(fields);s=u.snap()
 for name in ['Eastern Time (ET)','Central Time (CT)','Mountain Time (MT)','Pacific Time (PT)','I have supported channel mix conversations and helped clients understand cross-channel impact','Multi-touch attribution or incrementality testing']:
  k=u.ref(s,'checkbox',name);line=next(x for x in s['snapshot'].splitlines() if f'[ref={k}]' in x)
  if '[checked]' not in line:u.call(['click',k])
 s=u.snap();n=next(v.get('name','').strip() for v in s['refs'].values() if v['role']=='combobox' and v.get('name','').startswith('Thank you for taking'));u.choose(n,'Yes')
 r=u.form();f=r['result'];assert f['url']==p['company_application_url'] and e['uploaded_filename']==Path(p['verified_resume_wsl_path']).name and e['uploaded_filename'] in f['text'];assert all(any(i['value']==v for i in f['inputs']) for v in fields.values());(Q/j/'pre-submit-form.json').write_text(json.dumps(r,indent=2));s=u.snap();u.call(['click',u.ref(s,'button','Submit application')]);time.sleep(1);r=u.call(['evaluate','--fn','() => ({url:location.href,title:document.title,text:document.body.innerText})']);f=r['result'];(Q/j/'after-submit-review.json').write_text(json.dumps(r,indent=2))
 if 'Security code' in f['text']:e['outcome']='verification_pending'
 elif f['url']==p['company_application_url']+'/confirmation' and f['title']=='Thank you for applying':e.update(outcome='submitted',confirmation_url=f['url'],confirmation_text=f['text']);(Q/j/'confirmation.json').write_text(json.dumps(r,indent=2))
 else:raise RuntimeError(f['text'][-1800:])
 e.pop('blocking_questions',None);(Q/j/'submission-result.json').write_text(json.dumps(e,indent=2));print(json.dumps({'id':j,'outcome':e['outcome']}),flush=True)
