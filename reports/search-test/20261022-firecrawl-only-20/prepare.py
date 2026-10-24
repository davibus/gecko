"""Assess saved Firecrawl-only evidence; no web discovery or tracker writes."""
import sys,json,re,html
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
from urllib.parse import urlsplit
ROOT=Path('C:/gecko_main');P=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8')
from models import RawListing
from normalize import normalize,posting_identity,clean_text
from firecrawl_discovery import posting_date
from sources.web import SCRIPT_RE,_job_nodes
from job_extraction import extract,markdown
from hard_filters import deterministic_filter
from preferences import load_preferences

now=datetime.now(timezone.utc);cutoff=now-timedelta(hours=96)
details=json.loads((P/'all-indeed-details.json').read_text(encoding='utf-8'))
details += [x['data'] for x in json.loads((P/'replacements.json').read_text(encoding='utf-8'))['data']['alexandria'] if x.get('data')]
gh={}
for f in [P/'batch-0.json',P/'batch-1.json',P/'full-batch-2.json',P/'full-batch-3.json',P/'employer-original-dates.json']:
    for x in json.loads(f.read_text(encoding='utf-8')).get('data',{}).get('alexandria',[]):
        if x.get('data',{}).get('id'):gh[str(x['data']['id'])]=x['data']
manual_hold={
 'c4666f015b36af1b':'Employer link resolves to general openings; exact current vacancy not verified',
 '2be5e7c74316d516':'Employer application is CAN-BC-Remote and pay is CAD; outside US geography',
 '05a39abd0dfb5437':'Employer permitted states explicitly exclude Utah',
 '3e3baf61a0b959cc':'Employer permitted states explicitly exclude Utah',
 'fdf27fc25ce4bd47':'Employer JobPosting restricts applicant country to South Africa',
 '45ecc5c9ab366609':'Posting conflicts: remote metadata but Hercules hybrid requirement in description',
 'a1c1d2e15f5fc79d':'Requires bilingual sales/business-development leadership; outside requested marketing role focus',
}
chosen=['fc2c0758c591cd65','d21fa1f70f214488','3af54cce23d872d9','6fd5dae7c26f6604',
 'd43b4425c2410435','cef0302b96e7130e','bf579883c6d565e8','704036dc656dad48',
 'da6d662422e5110d','6e6a7041208d6cbd','547234419d1fdbb6','8408cd9a0b482a9c',
 '96fc46852ef3281a','67f9bf7ba4640aaf','0a74a099f7a2bf8e','6cb76570e2dce43f',
 'd4d47ac21de7584f','9806a1e32c9ac8de','5701142e55bfbafc']
assessment=[];prepared=[]
for d in details:
    key=d['job_key'];f=P/('employer-'+key+'.json');page=json.loads(f.read_text(encoding='utf-8')) if f.exists() else {}
    meta=page.get('metadata') or {};body=d.get('description_html') or d.get('description_text') or ''
    nodes=[]
    for block in SCRIPT_RE.findall(page.get('rawHtml') or ''):
        try:nodes.extend(_job_nodes(json.loads(html.unescape(block))))
        except ValueError:pass
    nodes=[n for n in nodes if clean_text(n.get('title') or '').casefold()==clean_text(d['title']).casefold()]
    item=nodes[0] if len(nodes)==1 else {}
    employer_url=meta.get('url') or d.get('apply_url') or d['source_url']
    original=item.get('datePosted') or d.get('posted_at') or ''
    date_evidence='Employer JobPosting.datePosted' if item.get('datePosted') else 'Indeed employer posting date; reposted=false'
    ghid=re.search(r'(?:/jobs/|gh_jid=)(\d+)',employer_url)
    if ghid and ghid[1] in gh and gh[ghid[1]].get('first_published'):
        original=gh[ghid[1]]['first_published'];date_evidence='Employer ATS first_published retrieved through Firecrawl'
    elif re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(original)) and str(d.get('posted_at') or '').startswith(original):
        # Preserve the provider's actual UTC instant when it corroborates the
        # employer's original calendar date; do not invent a midnight/timezone.
        original=d['posted_at'];date_evidence='Employer original date corroborated by Indeed employer posting timestamp; reposted=false'
    if key=='fc2c0758c591cd65':
        # The employer explicitly shows Open Date 10/19/2026; syndicated JSON-LD
        # reports 10/22, which cannot replace that earlier original opening date.
        assert re.search(r'10/19/2026',page.get('markdown') or '')
        original=d['posted_at'];date_evidence='Employer visible Open Date 10/19/2026, corroborated by Indeed posting timestamp'
    # Read the source's published server-side job object; no browser execution.
    phenom={}
    match=re.search(r'phApp\.ddo\s*=\s*',page.get('rawHtml') or '')
    if match:
        try:phenom=json.JSONDecoder().raw_decode(page['rawHtml'][match.end():])[0].get('jobDetail',{}).get('data',{}).get('job',{})
        except (ValueError,AttributeError):pass
    if phenom.get('jobStatus','').casefold() in {'closed','expired','inactive'}:
        manual_hold[key]='Employer marks vacancy closed'
    if item.get('description') and len(markdown(item['description']))>=600:body=item['description']
    elif phenom.get('description') and len(markdown(phenom['description']))>=600:body=phenom['description']
    labels=[x['label'] for x in d.get('attributes',[])]
    arrangement='hybrid' if 'Hybrid work' in labels else 'remote' if 'Remote' in labels else 'on-site' if 'In-person' in labels else ''
    if item.get('jobLocationType')=='TELECOMMUTE':arrangement='remote'
    employer_markdown=page.get('markdown') or ''
    if key=='5701142e55bfbafc':arrangement='hybrid'
    if key=='d43b4425c2410435':arrangement='remote' # exact employer path US---Remote and full description North - Remote (US)
    location=d.get('location',{}).get('formatted') or ''
    if arrangement=='remote':location='Remote, United States'
    employment='contract' if 'Contract' in labels else 'full-time' if 'Full-time' in labels else 'part-time' if 'Part-time' in labels else ''
    sal=d.get('salary') or {}
    salary=sal.get('formatted') or ''
    if sal.get('kind')=='estimated':salary='Estimated '+salary
    company=d.get('employer',{}).get('name') or (item.get('hiringOrganization') or {}).get('name') or ''
    raw=RawListing('indeed',key,d['source_url'],d['title'],company,location=location,
        description=markdown(body),employment_type=employment,salary=salary,date_posted=original,remote_type=arrangement,
        metadata={**item,'description':body,'employmentType':employment,'datePosted':original,
            '_discovered_via':'firecrawl','_retrieved_via':'firecrawl-alexandria',
            'jobLocationType':'TELECOMMUTE' if arrangement=='remote' else item.get('jobLocationType','')})
    if sal.get('kind')=='posted' and sal.get('min') is not None:
        raw.metadata['baseSalary']={'currency':sal.get('currency'),'value':{'minValue':sal['min'],'maxValue':sal.get('max'),'unitText':sal.get('period','').upper()}}
    job=normalize(raw,discovered=now.astimezone(__import__('zoneinfo').ZoneInfo('America/Denver')).date().isoformat())
    job.work_arrangement=arrangement or job.work_arrangement
    job.found_using='Firecrawl'
    accepted,reason=deterministic_filter(job,load_preferences())
    freshness,_=posting_date(original,now,cutoff)
    if freshness!='recent':accepted=False;reason='Original employer posting date outside four-day window or unverified'
    if d.get('expired') or d.get('reposted'):
        accepted=False;reason='Expired or marked repost'
    if f.exists() and meta.get('statusCode')!=200:
        accepted=False;reason='Employer page HTTP '+str(meta.get('statusCode'))
    if key in manual_hold:accepted=False;reason=manual_hold[key]
    doc=extract({'markdown':markdown(body),'rawHtml':'','metadata':{'statusCode':200}},raw,date_evidence+': '+original)
    if doc['status']!='complete':accepted=False;reason='Full-description extraction needs review: '+'; '.join(doc['issues'])
    doc['fields']['work_arrangement']=job.work_arrangement
    doc['fields']['application_url']=employer_url
    doc['fields']['original_posting_date']=original
    doc['firecrawl_evidence']={'indeed_detail':d,'employer_file':str(f) if f.exists() else None,
        'checked_at':now.isoformat(),'original_date_evidence':date_evidence,'employer_page_status':meta.get('statusCode'),
        'phenom_job_status':phenom.get('jobStatus'),'employer_jobposting':item}
    # Company homepages only from links actually published in the saved posting.
    org=item.get('hiringOrganization') or {}
    website=org.get('sameAs') or org.get('url') or ''
    urls=re.findall(r'https?://[^\s<>"\)]+',html.unescape((page.get('rawHtml') or '')+' '+body))
    name=re.sub('[^a-z0-9]','',company.casefold())
    if not website:
        for u in urls:
            try:parts=urlsplit(u);host=(parts.hostname or '').removeprefix('www.')
            except ValueError:continue
            stem=host.split('.')[0].replace('-','')
            if len(stem)>=4 and stem in name and parts.path in ('','/') and not parts.query:
                website=parts._replace(fragment='',query='').geturl();break
    if website:doc['fields']['company_website']=website
    if accepted:
        prepared.append({'candidate_key':key,'raw':asdict(raw),'job':asdict(job),'document':doc,
            'application_url':employer_url,'selected':key in chosen,'date_evidence':date_evidence})
    assessment.append({'key':key,'company':company,'title':d['title'],'accepted':accepted,'reason':reason,
        'selected':key in chosen,'date':original,'arrangement':job.work_arrangement,'salary':salary,
        'company_website':website,'description_characters':len(job.description)})
# The current Real Chemistry paid-search vacancy was independently returned by
# Firecrawl and its full exact employer ATS record has already been retrieved.
g=gh['5454003008']
raw=RawListing('greenhouse',str(g['id']),g['absolute_url'],g['title'],g['company_name'],
    location=g['location'],description=markdown(g['content_html']),date_posted=g['first_published'],remote_type='remote',
    metadata={'description':g['content_html'],'datePosted':g['first_published'],'jobLocationType':'TELECOMMUTE',
        '_discovered_via':'firecrawl','_retrieved_via':'firecrawl-alexandria','hiringOrganization':{'name':g['company_name']}})
job=normalize(raw);job.found_using='Firecrawl'
doc=extract({'markdown':markdown(g['content_html']),'metadata':{'statusCode':200}},raw,'Employer ATS first_published: '+raw.date_posted)
job.salary=__import__('job_extraction').salary_display(doc['fields']['salary'])
ok,why=deterministic_filter(job,load_preferences());fresh,_=posting_date(raw.date_posted,now,cutoff)
assert ok and fresh=='recent' and doc['status']=='complete',(why,fresh,doc['issues'])
doc['fields']['application_url']=g['apply_url'];doc['firecrawl_evidence']={'employer_ats':g,'checked_at':now.isoformat()}
prepared.append({'candidate_key':'gh:'+str(g['id']),'raw':asdict(raw),'job':asdict(job),'document':doc,
    'application_url':g['apply_url'],'selected':True,'date_evidence':'Employer ATS first_published'})
assessment.append({'key':'gh:'+str(g['id']),'company':g['company_name'],'title':g['title'],'accepted':True,'selected':True,
    'date':g['first_published'],'salary':job.salary,'description_characters':len(job.description)})
(P/'assessment.json').write_text(json.dumps(assessment,indent=2),encoding='utf-8')
(P/'prepared.json').write_text(json.dumps(prepared,indent=2),encoding='utf-8')
selected=[x for x in prepared if x['selected']]
print(json.dumps({'selected_count':len(selected),'selected':[{'key':x['candidate_key'],'company':x['job']['company'],'title':x['job']['title'],'salary':x['job']['salary'],'date':x['job']['date_posted'],'work':x['job']['work_arrangement']} for x in selected],
    'selected_failures':[x for x in assessment if x.get('selected') and not x['accepted']]},indent=2))
