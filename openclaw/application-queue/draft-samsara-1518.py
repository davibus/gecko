from current_batch_ui import UI
from pathlib import Path
import json,time
Q=Path('/mnt/c/gecko_main/openclaw/application-queue');j='1518';route=json.loads((Q/j/'application-form-route.json').read_text());u=UI(route['targetId']);e=json.loads((Q/j/'submission-result.json').read_text());assert e['outcome']=='pending_assessment';u.choose('Country','United States +1');s=u.snap();u.call(['type',u.ref(s,'combobox','Location (City)'),'American Fork','--slowly']);time.sleep(1);s=u.snap();u.call(['click',u.ref(s,'option','American Fork, Utah, United States')]);s=u.snap();fields={}
for v in s['refs'].values():
 n=v.get('name','').strip()
 if v['role']=='textbox':
  if n=='Preferred First Name':fields[n]='Dave'
  if n=='Preferred Last Name':fields[n]='Call'
  if n.startswith('What is the zip code'):fields[n]='84003'
  if n=='Most Recent Employer':fields[n]='ILT Marketing'
  if n.startswith('At Samsara, we encourage'):fields[n]='Dave Call (he/him)'
u.fill(fields);s=u.snap()
for prefix,value in [('Will you now or in the future require Samsara','No'),('Are you currently legally authorized','Yes'),('Have you previously worked at Samsara?','No')]:
 n=next(v.get('name','').strip() for v in s['refs'].values() if v['role']=='combobox' and v.get('name','').startswith(prefix));u.choose(n,value)
for name in ['Processing of Personal Data','How did you hear about this opportunity?','Where have you learned about Samsara? Select all that apply.','How do you identify? (gender identity)','How do you identify? (race/ethnicity)','If you are based in the US, what is your veteran status?','Do you have a physical or mental disability, impairment, or condition that substantially limits major life activity?']:
 print(name,json.dumps(u.options(name)),flush=True)
(Q/j/'form-draft.json').write_text(json.dumps(u.form(),indent=2));print('Samsara known contact and authorization fields completed; policy answer pending.')
