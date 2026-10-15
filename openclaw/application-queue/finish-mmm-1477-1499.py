from current_batch_ui import UI
from pathlib import Path
import json,time,re
Q=Path('/mnt/c/gecko_main/openclaw/application-queue')
for j in ['1477','1499']:
 u=UI('retry-'+j);p=json.loads((Q/j/'application-package.json').read_text());e=json.loads((Q/j/'submission-result.json').read_text());assert e['outcome']=='pending_assessment';print('Completing MMM '+j,flush=True);u.choose('Country','United States +1');u.choose('What is your current location?','United States of America',search=True);s=u.snap()
 for prefix,value in [('Do you have proven experience','Yes'),('Have you communicated MMM','Yes'),('Are you responsible for MMM','Yes'),('Are you familiar with Incrementality','Yes'),('Are you proficient in Python','Yes'),('Have you run an MMM','Yes'),('Are you authorized to work for any','Yes'),('Will you, at any point','No')]:
  names=[v.get('name','').strip() for v in s['refs'].values() if v['role']=='combobox' and v.get('name','').startswith(prefix)];assert len(names)==1;u.choose(names[0],value)
 s=u.snap();name=next(v.get('name','').strip() for v in s['refs'].values() if v['role']=='combobox' and v.get('name','').startswith('How many years'));opts=u.options(name);fits=[]
 for opt in opts:
  nums=[int(x) for x in re.findall(r'\d+',opt)]
  if not nums:continue
  if len(nums)>=2 and nums[0]<=14<=nums[1]:fits.append(opt)
  elif len(nums)==1 and nums[0]<=14 and any(x in opt.lower() for x in ['+','more','over']):fits.append(opt)
 assert len(fits)==1,{'years_supported':14,'options':opts,'fits':fits};u.choose(name,fits[0]);s=u.snap();fields={}
 for v in s['refs'].values():
  n=v.get('name','').strip()
  if v['role']=='textbox' and n.startswith('Please drop a link'):fields[n]='https://www.linkedin.com/in/mdavidcall'
  if v['role']=='textbox' and n.startswith('What is your desired annual'):fields[n]='70000'
 u.fill(fields);r=u.form();f=r['result'];assert f['url']==p['company_application_url'] and e['uploaded_filename']==Path(p['verified_resume_wsl_path']).name and e['uploaded_filename'] in f['text'];assert not f['invalid'];(Q/j/'pre-submit-form.json').write_text(json.dumps(r,indent=2));s=u.snap();u.call(['click',u.ref(s,'button','Submit application')]);time.sleep(1);r=u.call(['evaluate','--fn','() => ({url:location.href,title:document.title,text:document.body.innerText})']);f=r['result'];(Q/j/'after-submit-review.json').write_text(json.dumps(r,indent=2))
 if 'Security code' in f['text']:e['outcome']='verification_pending'
 elif f['url']==p['company_application_url']+'/confirmation' and f['title']=='Thank you for applying':e.update(outcome='submitted',confirmation_url=f['url'],confirmation_text=f['text']);(Q/j/'confirmation.json').write_text(json.dumps(r,indent=2))
 else:raise RuntimeError(f['text'][-1500:])
 e.pop('blocking_questions',None);(Q/j/'submission-result.json').write_text(json.dumps(e,indent=2));print(json.dumps({'id':j,'outcome':e['outcome']}),flush=True)
