"""Run broad free Gecko coverage and bounded concurrent canonical reviews."""
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from collections import Counter
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import sys
from threading import Lock
from urllib.parse import urlsplit
from datetime import datetime,timezone

from recover_gecko_pending import Recovery,ROOT,OUT,save,scout,History,JobStore,GoogleTracker,Config,run_lock,config
from incremental_discovery import FREE_SOURCES,aliases,complete,free_retrieve
from normalize import normalize,posting_identity
from sources.acquisition import acquire
from sources.base import SearchRequest
from sources.config import load_source_config
from query_provenance import remember


def targeted_muse(requests):
    """Same authorized public API, server-filtered category; missing type is unknown."""
    from sources.themuse import TheMuseProvider
    from sources.http import get_json
    from urllib.parse import urlencode
    from models import RawListing
    provider=TheMuseProvider();pages={};rows={};events=[]
    for request in requests:
        page=0
        while True:
            key=(request.location,page)
            if key not in pages:
                params={'api_key':provider.api_key,'page':page,'descending':'true',
                        'location':request.location,'category':'Marketing'}
                pages[key]=get_json(provider.endpoint+'?'+urlencode(params))
            data=pages[key]
            words={word.casefold() for word in request.query.split() if len(word)>2}
            for item in data.get('results',[]):
                title=str(item.get('name') or '');description=str(item.get('contents') or '')
                if words and not any(word in (title+' '+description).casefold() for word in words):continue
                raw=RawListing('themuse',str(item.get('id') or ''),str(item.get('refs',{}).get('landing_page') or ''),
                    title,str(item.get('company',{}).get('name') or ''),
                    location=', '.join(v.get('name','') for v in item.get('locations',[])),description=description,
                    employment_type=str(item.get('employmentType') or ''),date_posted=str(item.get('publication_date') or ''),
                    metadata={**item,'_query_used_to_find':'The Muse API: category=Marketing; location='+request.location+'; role filter='+request.query})
                rows.setdefault((raw.source_job_id,raw.url),raw)
            events.append({'location':request.location,'category':'Marketing','page':page,'role_filter':request.query,
                           'results':len(data.get('results',[])),'page_count':data.get('page_count')})
            if page+1>=int(data.get('page_count') or 1):break
            page+=1
    remember(rows.values());save('targeted-muse-evidence.json',events)
    return list(rows.values()),[]


class Coverage(Recovery):
    def __init__(self,*args):
        super().__init__(*args)
        audit=json.loads((OUT/'audit.json').read_text())
        self.original_pending_urls={r['url'] for r in audit['pending']+audit['legacy_pending'] if r.get('url')}
        self.original_pending_urls.update(r['original_url'] for r in audit['legacy_pending'] if r.get('original_url'))
        self.original_pending_urls.update(r['url'] for r in audit['cached_postings'] if r.get('url'))
        self.original_pending_identities={posting_identity(u) for u in self.original_pending_urls}
        self.new_feed_rows=0

    def publish(self,job):
        previous=len(self.receipts)
        super().publish(job)
        if len(self.receipts)>previous and posting_identity(job.url) in self.original_pending_identities:
            self.receipts[-1]['kind']='pending recovered'
            save('verified-jobs.json',self.receipts)

    def recover_incomplete(self):
        """Authorized free retry; transport dispatch and all paid bills untouched."""
        self.stage='incomplete pending recovery'
        with self.history.connect() as con:
            rows=[dict(r) for r in con.execute("SELECT * FROM daily_candidates WHERE state='pending' AND content_json IS NULL AND paid_state='' AND raw_json LIKE '%adzuna%'")]
        lock=Lock();host_attempts=Counter();blocked={}
        def fetch(row):
            from models import RawListing
            raw=RawListing(**json.loads(row['raw_json']))
            host=urlsplit(raw.url).hostname or ''
            with lock:
                if host in blocked:return row['key'],None,'Source blocked after free attempts: '+blocked[host],False
                if host_attempts[host]>=3:return row['key'],None,'Free source produced no complete description in three probes; retained for employer API evidence',False
                host_attempts[host]+=1
            try:
                content=free_retrieve(raw)
                return row['key'],content,'Complete exact free description' if content else 'Free paths did not yield a complete exact description',True
            except Exception as exc:
                message=str(exc)
                with lock:
                    if re.search(r'401|402|403|429|robots|blocked|not allowed',message,re.I):blocked[host]=message
                return row['key'],None,message,True
        ready=[]
        with self.history.lock(),ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(fetch,row):row for row in rows}
            remaining=set(futures)
            while remaining:
                done,remaining=wait(remaining,timeout=1,return_when=FIRST_COMPLETED)
                for future in done:
                    key,content,reason,attempted=future.result()
                    if attempted:self.free_attempts.append({'purpose':'recover incomplete pending description','key':key,'reason':reason})
                    if content:
                        self.engine.update(key,content_json=json.dumps(content),retry_at=None)
                        ready.append(key)
                    else:self.engine.pending(key,'Free recovery pending: '+reason)
                self.panel('Recovering incomplete pending sources; '+str(len(ready))+' complete descriptions recovered')
            self.rounds(self.prepare(ready))
        save('pending-free-recovery.json',{'attempts':self.free_attempts,'host_attempts':dict(host_attempts),'blocked_sources':blocked,'ready':ready})

    def recover_ledger(self):
        self.stage='pending recovery'
        from firecrawl_discovery import extract_listing
        from job_extraction import extract,salary_display
        from query_provenance import query_for_job
        from link_validation import EXPIRED,BOT
        raws=[];seen=set();outcomes=Counter()
        with self.history.connect() as con:
            records=con.execute("SELECT response_json,started_at FROM requests WHERE endpoint='scrape' AND status='succeeded' AND response_json IS NOT NULL ORDER BY started_at DESC").fetchall()
        for record in records:
            if (datetime.now(timezone.utc)-datetime.fromisoformat(record['started_at'])).total_seconds()>86400:continue
            data=json.loads(record['response_json']).get('data') or {}
            url=(data.get('metadata') or {}).get('sourceURL') or (data.get('metadata') or {}).get('url')
            if not url or posting_identity(url) in seen:continue
            seen.add(posting_identity(url))
            try:raw,evidence,final=extract_listing(data,url)
            except Exception:outcomes['parse pending']+=1;continue
            if not raw:outcomes['no unique full posting']+=1;continue
            job=normalize(raw)
            if aliases(job)&self.known_names:outcomes['already known']+=1;continue
            doc=extract(data,raw,evidence)
            if doc['status']!='complete' or EXPIRED.search(doc['full_description_markdown']) or BOT.search(doc['full_description_markdown'][:3000]):
                outcomes['incomplete/expired/access challenge']+=1;continue
            query=query_for_job(job)
            if not query:
                outcomes['query provenance not recorded; await free feed evidence']+=1;continue
            raw.description=doc['full_description_markdown']
            raw.salary=salary_display(doc['fields']['salary']) or raw.salary
            raw.employment_type='; '.join(doc['fields']['employment_types']) or raw.employment_type
            raw.remote_type=doc['fields']['work_arrangement'] or raw.remote_type
            raw.metadata.update(_query_used_to_find=query,_recovery_document=doc)
            raws.append(raw)
        save('ledger-cache-audit.json',{'outcomes':dict(outcomes),'recoverable_records':len(raws)})
        with self.history.lock():
            keys=self.engine.ingest(raws,self.known,self.rejections)
            self.rounds(self.prepare(keys))

    def collect_configured(self):
        self.stage='configured free source coverage'
        providers=scout.providers()
        settings=load_source_config()
        self.coverage['jooble']={'status':'disabled by standing source policy','configured':False}
        requests=[SearchRequest(role,location,1,20) for role in self.preferences['target_roles']
                  for location in self.preferences.get('preferred_locations',['Utah','Remote'])]
        checkpoint=OUT/'configured-free-source-coverage-review-queue.json'
        if checkpoint.exists():
            old=json.loads((OUT/'coverage.json').read_text(encoding='utf-8-sig'))
            self.coverage.update(old)
            # Every source response and all candidate identities were already
            # persisted before this queue. Reclassify only its pending review keys.
            self.coverage['themuse']={'status':'success','candidates':1,'targeted_category':'Marketing','reused_saved_source_response':True}
            keys=[r['key'] for r in json.loads(checkpoint.read_text(encoding='utf-8-sig'))]
            with self.history.lock():self.configured_queue=self.prepare(keys)
            self.panel('Configured feed checkpoint recovered; checking additional employer boards next',force=True)
            return
        collected=[]
        previous=json.loads((OUT/'coverage.json').read_text(encoding='utf-8-sig')) if (OUT/'coverage.json').exists() else {}
        for name,provider in providers.items():
            if name not in FREE_SOURCES:
                self.coverage[name]={'status':'requires separate index-only coverage',
                    'configured':provider.configured(),'class':type(provider).__name__,
                    'reason':'Adapter combines discovery and paid page retrieval; not invoked automatically'}
            elif not provider.configured():
                self.coverage[name]={'status':'unconfigured','reason':getattr(provider,'reason','Missing credentials or employer configuration')}
        with ThreadPoolExecutor(max_workers=settings['max_workers']) as pool:
            futures={}
            from models import RawListing
            for name,provider in providers.items():
                if name not in FREE_SOURCES or not provider.configured():continue
                path=OUT/('source-'+name+'.json')
                if path.exists():
                    batch=[RawListing(**r) for r in json.loads(path.read_text(encoding='utf-8'))]
                    collected.extend(batch)
                    self.coverage[name]={**previous.get(name,{}),'status':previous.get(name,{}).get('status','success'),
                                         'candidates':len(batch),'reused_saved_source_response':True}
                else:
                    futures[pool.submit(targeted_muse,requests) if name=='themuse' else pool.submit(acquire,provider,requests)]=name
            remaining=set(futures)
            while remaining:
                done,remaining=wait(remaining,timeout=1,return_when=FIRST_COMPLETED)
                for future in done:
                    name=futures[future]
                    try:
                        rows,errors=future.result()
                        if name=='greenhouse':
                            for raw in rows:raw.date_posted=str(raw.metadata.get('first_published') or '')
                        self.coverage[name]={'status':'partial failure' if errors else 'success' if rows else 'no results',
                            'candidates':len(rows),'errors':errors,'boards':len(getattr(providers[name],'companies',[])),
                            'queries_pages':getattr(providers[name],'acquisition_events',[])}
                        save('source-'+name+'.json',[asdict(r) for r in rows])
                        collected.extend(rows)
                    except Exception as exc:self.coverage[name]={'status':'failed','error':str(exc),'candidates':0}
                    print('SOURCE '+json.dumps({'name':name,**{k:v for k,v in self.coverage[name].items() if k!='queries_pages'}}),flush=True)
                    save('coverage.json',self.coverage)
                self.panel('Collecting configured free feeds: '+str(len(collected))+' candidates received')
        # Stable source IDs collapse repeated query hits before serialization or review.
        unique={}
        for raw in collected:unique.setdefault((raw.source,str(raw.source_job_id),posting_identity(raw.url)),raw)
        self.coverage['collection-summary']={'raw_candidate_encounters':len(collected),'unique_source_candidates':len(unique),
            'query_duplicates_collapsed':len(collected)-len(unique)}
        collected=list(unique.values())
        self.new_feed_rows+=len(collected)
        with self.history.lock():
            keys=self.engine.ingest(collected,self.known,self.rejections)
            queue=self.prepare(keys)
            self.configured_queue=queue

    def extra_employers(self):
        self.stage='additional employer coverage'
        import discover_ats_employers as discovery
        settings=load_source_config()
        existing={(platform,str(c.get(discovery.IDENTIFIER_KEYS[platform],'' )).casefold())
            for platform in discovery.PLATFORMS for c in settings['providers'][platform].get('companies',[])}
        candidates={}
        prior=json.loads((ROOT/'job-scout/data/ats-employer-discovery.json').read_text(encoding='utf-8-sig'))
        for row in prior.get('candidates',[]):
            key=(row.get('platform'),str(row.get('identifier') or '').casefold())
            if key in existing or row.get('validation_status')!='valid' or not row.get('marketing_job_count'):
                continue
            if not row.get('us_remote_job_count') and not row.get('us_job_count'):continue
            candidates[key]={'company':row['company'],'platform':row['platform'],'identifier':row['identifier'],
                             'evidence':row.get('discovered_via',[]),'origin':'existing employer discovery evidence'}
        # The exact shared roles drive fresh index discovery. No detail pages and
        # no Firecrawl web searches are requested here.
        key=os.getenv('BRAVE_SEARCH_API_KEY','')
        index_results=[];index_errors=[]
        if key:
            for role in self.preferences['target_roles']:
                query='(site:job-boards.greenhouse.io OR site:jobs.lever.co OR site:jobs.ashbyhq.com OR site:apply.workable.com) "'+role+'" remote United States'
                try:results=discovery._brave_search(query,key)
                except Exception as exc:
                    index_errors.append({'query':query,'error':str(exc)})
                    # Source-wide quota/access failure cannot be repaired by another query.
                    if re.search(r'401|402|403|429|billing',str(exc),re.I):break
                    continue
                index_results.extend({'query':query,**r} for r in results)
                for result in results:
                    extracted=discovery.extract_identifier(str(result.get('url') or ''))
                    if not extracted:continue
                    platform,identifier=extracted;k=(platform,identifier.casefold())
                    if k in existing:continue
                    candidates.setdefault(k,{'company':identifier,'platform':platform,'identifier':identifier,
                        'evidence':[query],'origin':'fresh authorized index'})
                self.panel('Discovering additional employer boards using '+role)
        else:index_errors=[{'error':'BRAVE_SEARCH_API_KEY is not configured'}]
        save('additional-index.json',{'results':index_results,'errors':index_errors})
        self.coverage['brave-employer-discovery']={'status':'blocked' if index_errors else 'success',
            'results':len(index_results),'errors':index_errors}
        if index_errors and re.search(r'401|402|403|429|billing',str(index_errors),re.I):
            for name in ('web-careers','linkedin','glassdoor','ziprecruiter'):
                self.coverage[name]={'status':'blocked shared authorized index',
                    'reason':index_errors[0]['error'],'paid_fallback_used':False}
        # Resolve all cached/fresh relevant board leads through supported free ATS
        # providers. This is transient coverage; existing source configuration stays.
        providers=scout.providers();rows=[];board_results=[]
        def fetch(item):
            platform=item['platform']
            company={'name':item['company'],discovery.IDENTIFIER_KEYS[platform]:item['identifier']}
            listings=providers[platform].fetch_company(company)
            for raw in listings:
                raw.metadata['_query_used_to_find']='Full feed: '+platform+'/'+item['identifier']+' (no search query)'
                if platform=='greenhouse':raw.date_posted=str(raw.metadata.get('first_published') or '')
            remember(listings)
            return listings
        with ThreadPoolExecutor(max_workers=settings['max_workers']) as pool:
            futures={pool.submit(fetch,item):item for item in candidates.values()}
            remaining=set(futures)
            while remaining:
                done,remaining=wait(remaining,timeout=1,return_when=FIRST_COMPLETED)
                for future in done:
                    item=futures[future]
                    try:
                        batch=future.result();rows.extend(batch)
                        board_results.append({**item,'status':'success' if batch else 'no results','jobs':len(batch)})
                    except Exception as exc:board_results.append({**item,'status':'failed','error':str(exc)})
                self.panel('Checking additional ATS boards: '+str(len(board_results))+'/'+str(len(candidates)))
                save('additional-boards.json',board_results)
        save('additional-source-rows.json',[asdict(r) for r in rows])
        self.coverage['additional-ats-boards']={'status':'complete','boards':len(board_results),
            'successful':sum(r['status']=='success' for r in board_results),'candidates':len(rows)}
        self.new_feed_rows+=len(rows)
        with self.history.lock():
            keys=self.engine.ingest(rows,self.known,self.rejections)
            combined={r['key']:r for r in getattr(self,'configured_queue',[])}
            combined.update({r['key']:r for r in self.prepare(keys)})
            self.rounds(list(combined.values()))

def main():
    scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
    native=sorted((Path(os.environ['LOCALAPPDATA'])/'OpenAI/Codex/bin').glob('*/codex.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
    if native:os.environ['PATH']=str(native[0].parent)+os.pathsep+os.environ['PATH']
    if config().get('usage_unlimited'):raise RuntimeError('Normal provider limits required')
    with run_lock(),JobStore() as store:
        operation=Coverage(GoogleTracker(config=Config.from_environment()),History(),store)
        # Recovery phases above have durable outcomes; resume coverage without
        # reissuing their requests or repeating their reviews.
        operation.collect_configured()
        operation.extra_employers()
        operation.finalize()

if __name__=='__main__':main()
