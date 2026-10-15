import json,subprocess,sys,time,re
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
R=Path('/mnt/c/gecko_main');Q=R/'openclaw/application-queue';j=sys.argv[1];target='retry-'+j
assert j in ['1297','1298','1299','1301','1302','1303','1308']
p=json.loads((Q/j/'application-package.json').read_text());e=json.loads((Q/j/'submission-result.json').read_text())
assert e['outcome']=='blocked' and e['uploaded_filename']==Path(p['verified_resume_wsl_path']).name
bank=(R/'openclaw/application-answers.md').read_text();master=(R/'input/master-resume/master-resume-v2.txt').read_text()
assert 'AUTH-01' in bank and '$70,000' in bank and 'American Fork, UT' in master
cli='/home/dcall/.openclaw/bin/openclaw'
def call(args):
 for attempt in range(4):
  r=subprocess.run([cli,'browser']+args+['--json'],capture_output=True,text=True,timeout=90)
  if r.returncode==0:return json.loads(r.stdout)
  if 'getaddrinfo' not in r.stderr+r.stdout:raise RuntimeError(r.stderr or r.stdout)
  print(j+': Temporary DNS failure; retry '+str(attempt+1),flush=True);time.sleep(2*(attempt+1))
 raise RuntimeError(r.stderr or r.stdout)
def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def ref(s,role,name):
 hits=[k for k,v in s['refs'].items() if v['role']==role and v['name'].strip()==name]
 assert len(hits)==1,(role,name);return hits[0]
select_fn=r'''async () => {
const plan=PLAN;const norm=s=>s.replace(/\s+/g,' ').replace(/\*+$/,'').trim();const out=[];
for(const a of plan){
 const hits=Array.from(document.querySelectorAll('input[role=combobox]')).filter(el=>norm(el.labels?.[0]?.innerText||'')===a.name);
 if(hits.length!==1)throw Error('Field missing/ambiguous: '+a.name);
 const el=hits[0],ctrl=el.closest('.select__control'),button=ctrl?.querySelector('button[aria-label="Toggle flyout"]');
 if(!button)throw Error('No visible dropdown control: '+a.name);
 el.focus();await new Promise(r=>setTimeout(r,100));if(el.getAttribute('aria-expanded')!=='true')button.click();
 let opts=[];for(let i=0;i<40;i++){await new Promise(r=>setTimeout(r,50));opts=Array.from(document.querySelectorAll('[role=option]'));if(opts.length)break;}
 const match=opts.filter(o=>a.exact?norm(o.innerText)===a.value: (norm(o.innerText)===a.value||norm(o.innerText).startsWith(a.value+' ')||norm(o.innerText).startsWith(a.value+',')||norm(o.innerText).startsWith(a.value+'-')));
 if(match.length!==1)throw Error('No unique choice: '+a.name+'; options='+JSON.stringify(opts.map(o=>norm(o.innerText))));
 const selected=norm(match[0].innerText);match[0].dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true,view:window}));match[0].dispatchEvent(new MouseEvent('mouseup',{bubbles:true,cancelable:true,view:window}));match[0].click();await new Promise(r=>setTimeout(r,100));el.blur();await new Promise(r=>setTimeout(r,100));out.push({name:a.name,selected,display:norm(ctrl.innerText)});
}
return out;
}'''
def select(plan):return call(['evaluate','--target-id',target,'--fn',select_fn.replace('PLAN',json.dumps(plan))])['result']
if p['company']=='Engine':
 salary='What are your salary expectations?';sponsor='Would you, now or in the future, require immigration sponsorship for work authorization?';auth='Are you legally authorized to work in the country where this position is based?'
elif p['company']=='Eve':
 salary='What is your desired salary?';sponsor='Will you now or in the future require employer sponsorship for employment visa status (e.g., H-1B, O-1, TN)?';auth='Are you legally authorized to work in the United States?'
else:
 assert j=='1308' and p['company']=='ezCater, Inc'
 salary=None;sponsor=next(x for x in e['blocking_questions'] if x.startswith('Will you, now or in the future, require sponsorship'));auth='Do you have the unrestricted right to work for any employer in the United States?'
plan=[{'name':'Country','value':'United States+1','exact':True},{'name':sponsor,'value':'No'},{'name':auth,'value':'Yes'}]
cert='I certify that the information provided in this application is true and complete to the best of my knowledge.'
if p['company']=='Eve':plan.append({'name':cert,'value':'Yes'})
if j=='1297':plan.append({'name':'How many years of experience do you have?','value':'10-15','exact':True})
if j=='1308':
 assert 'Led an eight-person e-commerce team' in master and 'annual projections and KPI reporting' in master
 plan.extend([{'name':'Which state do you currently reside in?','value':'Utah','exact':True},{'name':'Do you have experience leading Marketing Analytics?','value':'Yes'}])
s=snap();selected=select(plan);print(j+': Confirmed dropdown answers selected',flush=True)
fields=[]
if salary:fields.append({'ref':ref(s,'textbox',salary),'value':'70000'})
if j=='1308':
 name='Please briefly describe the team sizes and scopes you have led as a Marketing leader.'
 value='At LifeSpan Fitness, I managed an eight-person e-commerce department covering paid search, outreach, lead generation, customer acquisition, website performance, and growth across the U.S., Canada, and U.K. I also directed digital marketing and e-commerce for a large B2B distributor, coordinating execution and reporting across marketing, sales, operations, finance, IT, and product teams. My responsibilities included annual projections, KPI reporting, attribution, budget allocation, and campaign performance analysis.'
 fields.append({'ref':ref(s,'textbox',name),'value':value})
call(['batch','--target-id',target,'--actions',json.dumps([{'kind':'fill','fields':fields},{'kind':'type','ref':ref(s,'combobox','Location (City)'),'text':'American Fork','slowly':True}])])
city_fn=r'''async () => {for(let i=0;i<200;i++){const opts=Array.from(document.querySelectorAll('[role=option]')).filter(o=>o.innerText.replace(/\s+/g,' ').trim()==='American Fork, Utah, United States');if(opts.length===1){opts[0].dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true,view:window}));opts[0].click();document.querySelector('input#candidate-location')?.blur();return 'American Fork, Utah, United States';}await new Promise(r=>setTimeout(r,50));}throw Error('Exact city option unavailable');}'''
assert call(['evaluate','--target-id',target,'--fn',city_fn])['result']=='American Fork, Utah, United States'
r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,text:document.querySelector('form').innerText,inputs:Array.from(document.querySelectorAll('input,textarea')).filter(e=>e.type!=='hidden').map(e=>({id:e.id,value:e.value})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"])
f=r['result'];assert f['url']==p['company_application_url'] and not f['invalid'] and e['uploaded_filename'] in f['text'] and 'American Fork, Utah, United States' in f['text']
if salary:assert any(x['value']=='70000' for x in f['inputs'])
for a in plan:
 if a['name']=='Country':continue
 assert a['value'] in next(x['display'] for x in selected if x['name']==a['name'])
(Q/j/'pre-submit-form.json').write_text(json.dumps({'form':r,'verified_selections':selected},indent=2))
s=snap();call(['click',ref(s,'button','Submit application'),'--target-id',target])
r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,title:document.title,text:document.body.innerText})"]);c=r['result']
e['timestamp']=datetime.now(ZoneInfo('America/Denver')).isoformat()
if c['url']==p['company_application_url']+'/confirmation' and ('Your application has been received' in c['text'] or 'We have received your application' in c['text']):
 e.update(outcome='submitted',confirmation_url=c['url'],confirmation_text=c['text']);(Q/j/'confirmation.json').write_text(json.dumps(r,indent=2))
elif 'Security code' in c['text'] and 'verification code was sent to mdavidcall@gmail.com' in c['text']:e.update(outcome='verification_pending',verification_email='mdavidcall@gmail.com')
else:e.update(outcome='unconfirmed',blocker=c['text'][-1500:])
e.pop('blocking_questions',None);(Q/j/'submission-result.json').write_text(json.dumps(e,indent=2));print(json.dumps({'job_id':j,'outcome':e['outcome']}),flush=True)
