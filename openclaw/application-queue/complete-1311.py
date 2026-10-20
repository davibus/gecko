import json,subprocess,sys,re,time
from pathlib import Path
ROOT=Path('/mnt/c/gecko_main');Q=ROOT/'openclaw/application-queue';cli='/home/dcall/.openclaw/bin/openclaw';jid='1311';target='retry-'+jid
import sys; sys.path.insert(0,str(ROOT/'job-scout')); from resume_source import read_master_text
p=json.loads((Q/jid/'application-package.json').read_text());e=json.loads((Q/jid/'submission-result.json').read_text());assert e['outcome']=='pending_assessment'
assert 'Confirmed standing screening answers - 2026-10-13' in (ROOT/'openclaw/application-answers.md').read_text()
assert 'American Fork, UT' in read_master_text(ROOT/'input/master-resume/master-resume-v4.docx')
from native_browser import call

def snap():return call(['snapshot','--target-id',target,'--format','ai','--interactive','--compact'])
def ref(s,role,name):
 hits=[k for k,v in s['refs'].items() if v['role']==role and v['name'].strip()==name];assert len(hits)==1,(role,name);return hits[0]

def choose_prefix(name,prefix):
 s=snap();k=ref(s,'combobox',name);lines=s['snapshot'].splitlines();i=next(i for i,x in enumerate(lines) if f'[ref={k}]' in x);k=re.search(r'ref=(e\d+)',next(x for x in lines[i+1:] if 'button "Toggle flyout"' in x)).group(1);call(['click',k,'--target-id',target]);s=snap();hits=[k for k,v in s['refs'].items() if v['role']=='option' and v['name'].startswith(prefix)];assert len(hits)==1, json.dumps({'field':name,'wanted_prefix':prefix,'options':[v['name'] for v in s['refs'].values() if v['role']=='option']});call(['click',hits[0],'--target-id',target])

call(['press','Escape','--target-id',target]);choose_prefix('Country','United States +1')
s=snap();call(['type',ref(s,'combobox','Location (City)'),'American Fork','--slowly','--target-id',target]);time.sleep(1);s=snap();call(['click',ref(s,'option','American Fork, Utah, United States'),'--target-id',target])
s=snap();names=[v['name'].strip() for v in s['refs'].values() if v['role']=='combobox'];acts=[];answers={}
for prefix,value in [('Do you reside','Yes'),('Will you now','No'),('Are you willing and able','Yes')]:
 n=next(n for n in names if n.startswith(prefix));answers[n]=value;acts.append({'kind':'type','ref':ref(s,'combobox',n),'text':value,'slowly':True,'submit':True})
texts=[v['name'].strip() for v in s['refs'].values() if v['role']=='textbox'];values={
'List the *SaaS':'I have not run field events for SaaS companies.',
'Walk us through':'I used Salesforce at a Google Ads and web agency serving a diverse client base. The metrics we tracked varied according to each client’s business objectives rather than a fixed set of measures. I would prioritize qualified leads and conversion rates for lead-generation campaigns, revenue and acquisition efficiency for commerce, and opportunities and pipeline impact when evaluating marketing’s contribution to sales.'}
fields=[]
for prefix,value in values.items():
 n=next(n for n in texts if n.startswith(prefix));fields.append({'ref':ref(s,'textbox',n),'value':value})
acts.append({'kind':'fill','fields':fields});call(['batch','--target-id',target,'--actions',json.dumps(acts)])
r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,text:document.querySelector('form').innerText,inputs:Array.from(document.querySelectorAll('input,textarea')).map(e=>({value:e.value})),invalid:Array.from(document.querySelectorAll('input,textarea,select')).filter(e=>!e.checkValidity()).map(e=>({id:e.id,message:e.validationMessage}))})"]);f=r['result'];assert not f['invalid'] and e['uploaded_filename'] in f['text'] and 'American Fork, Utah, United States' in f['text'];assert all(any(i['value']==v for i in f['inputs']) for v in values.values())
for name,value in answers.items():assert f['text'].split(name,1)[1].lstrip(' *\n').startswith(value)
(Q/jid/'pre-submit-form.json').write_text(json.dumps(r,indent=2));s=snap();call(['click',ref(s,'button','Submit application'),'--target-id',target]);r=call(['evaluate','--target-id',target,'--fn',"() => ({url:location.href,text:document.body.innerText})"]);f=r['result'];assert 'Security code' in f['text'] and 'verification code was sent to mdavidcall@gmail.com' in f['text'];e['outcome']='verification_pending';e.pop('blocking_questions',None);(Q/jid/'submission-result.json').write_text(json.dumps(e,indent=2));print('1311 ready for fresh email verification',flush=True)
