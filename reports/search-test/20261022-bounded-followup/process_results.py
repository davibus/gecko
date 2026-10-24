"""Process exactly five Gecko and fifteen Firecrawl candidates; no paid calls."""
import sys,json,re,html
from pathlib import Path
from datetime import datetime,timezone,timedelta
from dataclasses import asdict
from types import SimpleNamespace
from urllib.parse import urlsplit
ROOT=Path('C:/gecko_main');HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8')
import scout,sheet_sync
from models import RawListing
from normalize import normalize,clean_text,posting_identity
from firecrawl_discovery import extract_listing
from job_extraction import markdown,extract,salary_display
from hard_filters import deterministic_filter
from preferences import load_preferences
from google_tracker import GoogleTracker,Config
from storage import JobStore,DEFAULT_DB
from service import discover_listings,_same_source_identity_conflicts
from deduplicate import find_duplicate
from link_validation import LinkResult
from run_gecko import run_lock
from sqlite_daily_report import backup_workspace
from firecrawl_state import History,config
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
now=datetime.now(timezone.utc);cutoff=now-timedelta(hours=96)
gecko=json.loads((HERE/'gecko-raw.json').read_text(encoding='utf-8'))
web=json.loads((HERE/'firecrawl-search.json').read_text(encoding='utf-8'))['web']
web=[x for x in web if urlsplit(x['url']).hostname in {'jobs.lever.co','job-boards.greenhouse.io','jobs.ashbyhq.com'}]
replacement=next(x for x in json.loads((HERE/'firecrawl-replacements.json').read_text(encoding='utf-8'))['web'] if '/appspace/jobs/' in x['url'])
web.append(replacement)
assert len(gecko)==5 and len(web)==15
planned=[];proofs={};raws={}
local_rows=GoogleTracker().scout().rows
known_urls={posting_identity(r['Job URL']):r for _,r in local_rows if r.get('Job URL')}

def date_value(value):
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):return None

def assess(backend,key,raw,verification):
    row={'retrieved_by':backend,'candidate_key':key,'company':raw.company,'title':raw.title,'url':raw.url,'date_posted':raw.date_posted,'salary':raw.salary}
    posted=date_value(raw.date_posted)
    if posted is None:row.update(outcome='needs review',reason='Original posting date unverified; four-day window retained')
    elif posted < cutoff:row.update(outcome='filtered',reason='Outside four-day posting window')
    elif posted > now:row.update(outcome='needs review',reason='Future posting timestamp needs verification')
    else:
        job=normalize(raw);accepted,reason=deterministic_filter(job,load_preferences())
        if not accepted:row.update(outcome='filtered',reason=reason)
        elif not raw.description or len(clean_text(raw.description))<600:row.update(outcome='needs review',reason='Full description unavailable')
        else:
            row.update(outcome='qualified',reason='Within four days; full posting and filters verified')
            raws[key]=raw;proofs[raw.url]=verification
    planned.append(row)

for data in gecko:
    raw=RawListing(**data);key=raw.source_job_id;page=json.loads((HERE/('page-'+key+'.json')).read_text(encoding='utf-8'))
    extracted,evidence,_=extract_listing(page,'https://www.adzuna.com/details/'+key)
    assert extracted and clean_text(extracted.title)==clean_text(raw.title) and extracted.company.casefold()==raw.company.casefold()
    assert page.get('metadata',{}).get('statusCode')==200 and '[Apply for this job]' in page['markdown']
    doc=extract(page,extracted,evidence)
    raw.description=markdown(extracted.description);raw.date_posted=extracted.date_posted
    raw.employment_type=extracted.employment_type or raw.employment_type
    salary=salary_display(doc['fields']['salary'])
    if salary:raw.salary=salary
    assess('Gecko',key,raw,LinkResult('valid',raw.url,raw.url,'Fresh matching Adzuna detail page with full JobPosting and application link',200))

for item in web:
    url=item['url'];key=url.rstrip('/').split('/')[-1]
    row={'retrieved_by':'Firecrawl','candidate_key':key,'title':item['title'],'url':url}
    if re.search(r'future opening|talent pool',item['title'],re.I):
        planned.append({**row,'outcome':'filtered','reason':'Future opening/talent pool; no current vacancy'});continue
    known=known_urls.get(posting_identity(url))
    if known:
        planned.append({**row,'company':known['Company'],'outcome':'already tracked','tracker_id':known.get('Scout ID'),'reason':'Skipped before paid page retrieval'});continue
    if '/appspace/jobs/' in url:
        planned.append({**row,'company':'Appspace','outcome':'filtered','reason':'Posting explicitly located in Toronto, Canada; outside US/Utah scope'});continue
    api_file=HERE/('ats-'+key+'.json')
    if api_file.exists():
        saved=json.loads(api_file.read_text(encoding='utf-8'));d=saved['data']
        if 'lever.co' in url:
            parts=[d.get('descriptionPlain','')]+[x['text']+'\n'+markdown(x['content']) for x in d.get('lists',[])]+[d.get('additionalPlain','')]
            desc='\n\n'.join(filter(None,parts));sr=d.get('salaryRange') or {}
            salary=f"{sr.get('currency','')} {sr.get('min','')}-{sr.get('max','')} per year" if sr.get('min') is not None else ''
            raw=RawListing('lever',key,url,d['text'],'Silverback Strategies',location=d['categories'].get('location',''),description=desc,employment_type=d['categories'].get('commitment',''),salary=salary,date_posted=datetime.fromtimestamp(d['createdAt']/1000,timezone.utc).isoformat(),remote_type=d.get('workplaceType',''))
        else:
            desc=markdown(html.unescape(d['content']))
            raw=RawListing('greenhouse',key,url,d['title'],d['company_name'],location=d['location']['name'],description=desc,date_posted=d.get('first_published') or '',remote_type='remote' if 'remote' in d['location']['name'].casefold() else '')
        raw.metadata={'_discovered_via':'firecrawl-search','_retrieved_via':'public-ats-api','_web_search_backends':['firecrawl']}
        assess('Firecrawl',key,raw,LinkResult('valid',url,url,'Current exact public employer ATS endpoint; full posting available',200));continue
    page_file=HERE/('page-'+key+'.json')
    if page_file.exists():
        page=json.loads(page_file.read_text(encoding='utf-8'));raw,evidence,_=extract_listing(page,url)
        assert raw and page.get('metadata',{}).get('statusCode')==200
        raw.url=url;raw.description=markdown(raw.description)
        if '## Location Type\n\nOn-site' in page.get('markdown',''):raw.remote_type='on-site'
        assess('Firecrawl',key,raw,LinkResult('valid',url,url,'Fresh matching employer page',200));continue
    planned.append({**row,'outcome':'closed','reason':'Official job-specific employer API returned HTTP 404; not retried'})

assert len(planned)==20
(HERE/'analysis.json').write_text(json.dumps(planned,indent=2),encoding='utf-8')
for row in planned:print(json.dumps(row),flush=True)
with run_lock():
    initial=sheet_sync.sync();before_backup=backup_workspace();tracker=GoogleTracker();tab=tracker.scout()
    with JobStore(DEFAULT_DB) as store:
        ids=[int(r['Scout ID']) for _,r in tab.rows if str(r.get('Scout ID') or '').isdigit()]
        if ids:store.observe_scout_id(max(ids))
        rejected=tracker.rejected_jobs_index();added=[]
        validator=SimpleNamespace(require_verified=True,check=lambda job:proofs[job.url])
        for row in planned:
            if row['outcome']!='qualified':continue
            raw=raws[row['candidate_key']];job=normalize(raw)
            duplicate=find_duplicate(job,[j for j in store.all() if not _same_source_identity_conflicts(job,j)])
            if duplicate:row.update(outcome='already tracked',scout_id=duplicate.id,reason='Existing stable/source identity preserved');continue
            result=discover_listings([raw],store,require_content=True,preserve_existing=True,link_validator=validator,preferences=load_preferences(),rejected_jobs=rejected)
            if result.added:
                row.update(outcome='added',scout_id=result.new_job_ids[0]);added.extend(result.new_job_ids)
            else:row.update(outcome='filtered',reason=str(result.decisions))
        if added:
            notes={i:'Bounded 20-listing Gecko test; four-day posting window. Contract jobs included; posted starting annual base above $120,000 excluded. Full description saved; unknown/estimated pay is not a confirmed salary. No resume or application started.' for i in added}
            scout.sync_tracker(store,jobs=[store.get(i) for i in added],append_only=True,discovery_notes=notes,audit_dir=HERE/'publication-audit')
    publication=sheet_sync.sync();remote=GoogleTracker(config=Config.from_environment()).scout()
    readback={str(r.get('Scout ID')):r for _,r in remote.rows}
    for row in planned:
        if row['outcome']=='added':
            r=readback[str(row['scout_id'])];raw=raws[row['candidate_key']]
            assert r['Company']==raw.company and r['Job Title']==clean_text(raw.title) and len(r['Job Description'])>=600 and r['Work Arrangement']=='remote'
            assert posting_identity(r['Job URL'])==posting_identity(raw.url)
            row['tracker_id']=row['scout_id'];row['description_characters']=len(r['Job Description'])
    settings=config();settings.update(enabled=True,daily_soft_credits=30,daily_hard_credits=30)
    usage=History(settings=settings).usage();assert usage['total_credits_accounted']<=30
    result={'verified':True,'checked':20,'source_counts':{'Gecko':5,'Firecrawl':15},'four_day_cutoff':cutoff.isoformat(),'results':planned,'credit_usage':usage,'publication':publication,'backup':backup_workspace()}
    (HERE/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    lines=['# Bounded Gecko job search — October 22, 2026','','20 listings checked: 5 Gecko and 15 Firecrawl. Four-day posting window retained. Contracts eligible; posted starting annual base over $120,000 excluded. No resumes or applications.','','| Search | Employer / role | Result | ID |','| --- | --- | --- | --- |']
    for r in planned:lines.append(f"| {r['retrieved_by']} | [{r.get('company','')} — {r['title'].replace('|','/')} ]({r['url']}) | {r['outcome']}: {r['reason']} | {r.get('tracker_id','')} |")
    lines+=['',f"Firecrawl: {usage['provider_confirmed_credits']} credits confirmed; {usage['estimated_or_reserved_credits']} reserved/estimated; {usage['total_credits_accounted']} total accounted against a 30-credit cap."]
    (HERE/'results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'added':added,'publication':publication,'credit_usage':usage}),flush=True)
