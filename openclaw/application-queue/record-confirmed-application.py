import sys,json
from pathlib import Path
from urllib.parse import urlsplit,unquote
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'job-scout'))
from google_tracker import GoogleTracker,_col,_a1
jid=sys.argv[1];q=ROOT/'openclaw/application-queue'/jid
p=json.loads((q/'application-package.json').read_text(encoding='utf-8'));e=json.loads((q/'submission-result.json').read_text(encoding='utf-8'))
assert e.get('outcome')=='submitted' and e.get('job_id',e.get('id'))==jid
assert ((p['company']=='Samsara' and jid=='1518' and 'Thank you for submitting your application and choosing Samsara for your job search!' in e.get('confirmation_text','') and 'Samsara’s Recruiting Team' in e.get('confirmation_text','')) or 'Your application has been received' in e.get('confirmation_text','') or (p['company']=='Keeper Security' and 'We’ve received your application and will review it soon.' in e.get('confirmation_text','')) or (p['company']=='Later' and 'one of our Talent Acquisition team members will review your application!' in e.get('confirmation_text','') and 'The Later Team' in e.get('confirmation_text','')) or (p['company']=='Gametime United' and 'We appreciate you taking the time to submit your application. Our team will review it and be in touch with next steps soon.' in e.get('confirmation_text','')) or (p['company']=='Wiz' and 'We have received your application' in e.get('confirmation_text','') and 'The Wiz Recruiting Team' in e.get('confirmation_text','')) or (p['company']=='Power Digital' and 'We have received your application' in e.get('confirmation_text','')) or (p['company']=='Engine' and 'We have received your application' in e.get('confirmation_text','')) or (p['company']=='Eve' and 'Thanks for applying to Eve!' in e.get('confirmation_text','') and 'Our team is reviewing applications closely' in e.get('confirmation_text','')) or (p['company']=='DataGrail' and 'Thank you for applying to DataGrail. Our team will review your application' in e.get('confirmation_text','')))
if p['company']=='Wiz' or (p['company']=='Samsara' and jid=='1518'):
 route=json.loads((q/'application-form-route.json').read_text(encoding='utf-8'));from urllib.parse import parse_qs;query=parse_qs(urlsplit(route['form_url']).query);token=query['token'][0];board='wizinc' if p['company']=='Wiz' else 'samsara';assert query['for']==[board];assert e.get('confirmation_url')=='https://job-boards.greenhouse.io/embed/job_app/confirmation?for='+board+'&token='+token;assert route['parent_url']==p['company_application_url']
else:assert e.get('confirmation_url','').rstrip('/')==p['company_application_url'].rstrip('/')+'/confirmation'
assert e['uploaded_filename']==Path(p['verified_resume_file_path']).name
t=GoogleTracker();t.discover_workbook(required=(t.config.scout_tab,));tab=t.tab(t.config.scout_tab)
hits=[(n,r) for n,r in tab.rows if str(r.get('Scout ID'))==jid];assert len(hits)==1
n,r=hits[0]
for field,pfield in [('Company','company'),('Job Title','job_title'),('Job URL','company_application_url')]:assert str(r.get(field))==p[pfield],field+' changed'
assert Path(unquote(urlsplit(r['Resume Link']).path).lstrip('/')).resolve()==Path(p['verified_resume_file_path']).resolve()
formula=t.tab(tab.title,value_render_option='FORMULA');assert formula.sheet_id==tab.sheet_id and formula.headers==tab.headers
fhits=[(nn,rr) for nn,rr in formula.rows if str(rr.get('Scout ID'))==jid];assert len(fhits)==1 and fhits[0][0]==n
col=tab.headers['Applied'];fr=fhits[0][1]
assert fr.get('Applied','') in ('','X'), 'Applied contains manual state or formula'
for rn,raw in (formula.raw_rows or {}).items():
 for cn,value in enumerate(raw,1):
  assert not(isinstance(value,str) and 'ARRAYFORMULA' in value.upper() and n>=rn and col>=cn),'Possible ARRAYFORMULA spill'
assert r.get('Applied','') in ('','X')
cell=_a1(tab.title,f'{_col(col)}{n}')
if r.get('Applied','')!='X':t.api.values().batchUpdate(spreadsheetId=t.config.spreadsheet_id,body={'valueInputOption':'RAW','data':[{'range':cell,'values':[['X']]}]}).execute()
after=t.tab(tab.title);assert after.headers==tab.headers and after.sheet_id==tab.sheet_id
ahits=[(nn,rr) for nn,rr in after.rows if str(rr.get('Scout ID'))==jid];assert len(ahits)==1 and ahits[0][0]==n and ahits[0][1].get('Applied')=='X'
for k,v in r.items():
 if k!='Applied':assert ahits[0][1].get(k)==v,'Unrelated target-row field changed: '+k
e['tracker_readback_result']={'tab':tab.title,'row':n,'cell':cell,'Applied':'X'}
(q/'submission-result.json').write_text(json.dumps(e,indent=2)+'\n')
(q/'tracker-write-audit.json').write_text(json.dumps({'job_id':jid,'cell':cell,'before':r.get('Applied',''),'after':'X','verified':True},indent=2)+'\n')
print(json.dumps(e['tracker_readback_result']))
