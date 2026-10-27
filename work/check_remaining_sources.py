"""Read-only/index-only coverage for paid-first adapters; no tracker writes."""
from recover_gecko_pending import ROOT,OUT,save,scout
import html
import json
import os
import re
import sqlite3
import time
from urllib.parse import urlsplit,parse_qs

scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
from discover_ats_employers import _brave_search
from preferences import load_preferences
from normalize import posting_identity
from firecrawl_postings import reject_result
from datetime import datetime,timezone
from sources.http import get_document

known=set()
with sqlite3.connect('file:'+str(ROOT/'job-scout/data/firecrawl_discovery.sqlite').replace('\\','/')+'?mode=ro',uri=True) as con:
    known.update(r[0] for r in con.execute('SELECT alias FROM daily_aliases'))
queries=[];candidates={};coverage={}
sites={'indeed':'site:indeed.com/viewjob','linkedin':'site:linkedin.com/jobs/view',
       'glassdoor':'site:glassdoor.com/job-listing','ziprecruiter':'site:ziprecruiter.com/jobs'}
stopped=''
for source,site in sites.items():
    found=skipped=0;errors=[]
    if stopped:
        coverage[source]={'status':'blocked shared index','reason':stopped};continue
    for role in load_preferences()['target_roles']:
        query=site+' "'+role+'" remote United States'
        try:results=_brave_search(query,os.environ['BRAVE_SEARCH_API_KEY'])
        except Exception as exc:
            errors.append({'query':query,'error':str(exc)})
            if re.search(r'401|402|403|429|billing',str(exc),re.I):stopped=str(exc);break
            continue
        queries.append({'source':source,'query':query,'results':results})
        for result in results:
            url=str(result.get('url') or '')
            if not url or reject_result(url,str(result.get('title') or ''),datetime.now(timezone.utc)):continue
            parts=urlsplit(url)
            if source=='indeed':key=parse_qs(parts.query).get('jk',[''])[0]
            elif source=='linkedin':
                match=re.search(r'(\d{8,})/?$',parts.path);key=match[1] if match else ''
            else:key=''
            aliases={'url:'+repr(posting_identity(url))}
            if key:aliases.add('source:'+source+':'+key)
            if aliases&known:skipped+=1;continue
            identity=source+':'+key if key else repr(posting_identity(url))
            candidates.setdefault(identity,{'source':source,'source_job_id':key,'url':url,
                'title_from_index':result.get('title'),'description_snippet':result.get('description'),
                'actual_query':query,'state':'pending','reason':'Index result only; exact complete posting and employer metadata required'})
            found+=1
        save('remaining-index-queries.json',queries)
        save('remaining-index-candidates.json',list(candidates.values()))
        time.sleep(1)
    coverage[source]={'status':'partial failure' if errors else 'index checked; full posting retrieval pending',
                      'new_candidate_encounters':found,'known_skipped':skipped,'errors':errors,'paid_requests':0}
    save('remaining-source-coverage.json',coverage)
    print(json.dumps({'source':source,**coverage[source]}),flush=True)
try:
    document=get_document('https://remote.com/openings')
    page=document.body.decode('utf-8',errors='replace')
    urls=sorted(set(re.findall(r'https://apply\.remote\.com/jobs/[a-f0-9-]{36}',html.unescape(page))))
    coverage['remote-careers']={'status':'free index checked' if urls else 'free index returned no extractable job IDs',
        'candidate_ids':len(urls),'known_skipped':sum('url:'+repr(posting_identity(u)) in known for u in urls),
        'paid_requests':0,'reason':'Detail requests require candidate-level admission; paid full_feed adapter was not invoked'}
    save('remote-index-candidates.json',[{'url':u,'state':'pending exact role metadata','source':'remote-careers',
        'actual_query':'Full employer index: remote.com/openings (no search query)'} for u in urls
        if 'url:'+repr(posting_identity(u)) not in known])
except Exception as exc:coverage['remote-careers']={'status':'free index failed','error':str(exc),'paid_requests':0}
ats=json.loads((OUT/'additional-index.json').read_text(encoding='utf-8-sig'))
coverage['web-careers']={'status':'authorized index checked through targeted ATS queries',
    'queries':len({r['query'] for r in ats['results']}),'results':len(ats['results']),
    'paid_requests':0,'reason':'Used index-only discovery; legacy paid-first document helper was not invoked'}
save('remaining-source-coverage.json',coverage)
print(json.dumps({'coverage':coverage,'pending_unique_index_candidates':len(candidates),'paid_requests':0}),flush=True)
