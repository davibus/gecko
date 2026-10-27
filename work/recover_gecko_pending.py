"""Supervised recovery/coverage run using canonical Gecko identity and writers."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import re
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
import scout
from firecrawl_state import History, config
from google_tracker import GoogleTracker,Config
from storage import JobStore
from preferences import load_preferences
from incremental_discovery import Engine,aliases,complete,publish_verified
from normalize import normalize,posting_identity
from models import RawListing
from run_gecko import run_lock
import time

OUT=ROOT/'reports/discovery/recovery-20261025'
ZONE=ZoneInfo('America/Denver')

def source_location_blocker(raw):
    """Structured source countries outrank a generic remote flag."""
    metadata=raw.metadata
    workplace=str(metadata.get('workplaceType') or '').casefold()
    if workplace in ('hybrid','onsite','on-site') and not re.search(r'\bUtah\b|,\s*UT\b',raw.location,re.I):
        return 'Structured employer workplace is '+workplace+' outside verified Utah location; generic remote flag does not establish eligibility: '+raw.location
    countries=[]
    def walk(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ('addressCountry','country','country_code') and isinstance(item,str) and item:
                    countries.append(item)
                elif key in ('address','postalAddress','secondaryLocations','locations'):walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    walk(metadata)
    if not countries:return ''
    allowed={'us','usa','united states','united states of america','worldwide','global'}
    if any(c.casefold() in allowed for c in countries):return ''
    return 'Structured employer/ATS country excludes verified U.S./Utah eligibility: '+', '.join(sorted(set(countries)))

def location_blocker(job):
    """Honor explicit applicant restrictions, including ISO country codes."""
    restriction=str(job.details.get('fields',{}).get('remote_eligibility_restrictions') or '').strip()
    if re.search(r'(?:except|exclud(?:e|es|ing)|not (?:hiring|accepting|considering)[^.;\n]{0,80})[^.;\n]{0,80}\bUtah\b',restriction,re.I):
        return 'Explicit applicant restriction excludes Utah: '+restriction
    # Hiring-region restrictions override a generic country/global marker.
    for line in restriction.splitlines():
        if (re.search(r'only (?:hiring|accepting|considering)',line,re.I)
                and re.search(r'Eastern|Central|Pacific|Atlantic',line,re.I)
                and not re.search(r'Mountain|all (?:US|U.S.|United States) time',line,re.I)):
            return 'Utah/Mountain time excluded by explicit hiring-zone restriction: '+line
    text=restriction or str(job.location or '').strip()
    countries=json.loads((OUT/'country-regions.json').read_text(encoding='utf-8-sig'))
    us=lambda value:bool(re.search(r'\b(?:USA|United States|Worldwide|Anywhere|Global)\b',value,re.I) or re.search(r'\bUS\b',value))
    # A country-tagged requisition is distinct from a global job at the same
    # company. A generic country eligibility marker cannot resolve that conflict.
    for country in countries:
        if country['code'] in ('US','001'):continue
        name=re.escape(country['name'])
        if (not us(job.title) and re.search(r'(?:\||[-\u2013\u2014]|\()\s*'+name+r'\s*(?:\||\)|[-\u2013\u2014]|Remote|$)',job.title,re.I)):
            return 'Country-specific requisition: '+country['name']+'; Utah eligibility unverified'
    if us(text):return ''
    for country in countries:
        if country['code']=='US':continue
        if text.casefold() in {country['code'].casefold(),country['iso3'].casefold(),country['name'].casefold()}:
            return 'Explicit foreign-only applicant country: '+country['name']+' ('+country['code']+')'
        if len(country['name'])>3 and re.search(r'\b'+re.escape(country['name'])+r'\b',text,re.I):
            return 'Foreign-only job location/restriction: '+country['name']+'; U.S./Utah eligibility unverified'
    if re.fullmatch(r'[A-Z]{2}(?:\s*[,;/]\s*[A-Z]{2})*',text):
        # With no explicit US/global evidence, a country-code restriction is not
        # proof of Utah eligibility. Keep ambiguous state codes pending too.
        if text not in ('UT',):return 'Country/region restriction '+text+' does not establish U.S./Utah eligibility'
    if re.search(r'\b(?:Egypt|Bulgaria|Romania|Philippines|South Africa|Serbia|Poland|Argentina|Brazil|LATAM|EMEA|Canada|United Kingdom|Australia|New Zealand|India)\b',text,re.I):
        return 'Explicit foreign-only applicant restriction: '+text
    return ''

def save(name,value):
    from uuid import uuid4
    OUT.mkdir(parents=True,exist_ok=True)
    path=OUT/name
    temp=path.with_suffix('.'+uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,indent=2,default=str),encoding='utf-8')
    temp.replace(path)

def snapshot(remote):
    tab=remote.scout(value_render_option='FORMULA')
    rows={str(v.get('Scout ID',v.get('ID'))):dict(zip(tab.header_values,tab.raw_rows[n]))
          for n,v in tab.rows if str(v.get('Scout ID',v.get('ID')) or '').isdigit()}
    return {'headers':[str(name) for name in tab.header_values],'rows':rows,'properties':remote._sheet_properties()}

def audit(remote,history,store):
    prefs=load_preferences()
    providers=scout.providers()
    from sources.config import load_source_config
    settings=load_source_config()
    result={'target_roles':prefs['target_roles'],'policy':json.loads((ROOT/'job-scout/preferences/resume-match.json').read_text()),
            'providers':{},'history':{},'cached_postings':[]}
    for name,provider in providers.items():
        result['providers'][name]={'class':type(provider).__name__,'configured':provider.configured(),
            'enabled':settings['providers'].get(name,{}).get('enabled'),
            'boards':len(getattr(provider,'companies',[])),
            'status':getattr(provider,'status',''), 'reason':getattr(provider,'reason','')}
    with history.connect() as con:
        for table,col in [('daily_candidates','state'),('candidates','verification_status'),('requests','status'),('report_outbox','status')]:
            result['history'][table]=[dict(r) for r in con.execute(f'SELECT {col},COUNT(*) AS count FROM {table} GROUP BY {col}')]
        pending=[dict(r) for r in con.execute("SELECT * FROM daily_candidates WHERE state='pending' OR (job_json IS NOT NULL AND published=0)")]
        result['pending_reasons']=dict(Counter(r['reason'] for r in pending))
        result['pending']=[{'key':r['key'],'reason':r['reason'],'retry_at':r['retry_at'],'paid_state':r['paid_state'],
            'content_cached':bool(r['content_json']),'review_cached':bool(r['review_json']),
            'qualified':bool(r['job_json']),'gecko_id':r['gecko_id'],
            **{k:json.loads(r['raw_json']).get(k) for k in ['source','source_job_id','company','title','location','url']}}
            for r in pending]
        result['legacy_pending']=[dict(r) for r in con.execute("SELECT key,verification_status,gecko_id,original_url,title,crawl_result FROM candidates WHERE verification_status NOT IN ('synced','duplicate','old','irrelevant')")]
    save('pending-audit.json',result)
    rejections=remote.rejected_jobs_index()
    engine=Engine(history,store,prefs)
    known=engine.seed(remote,rejections)
    from firecrawl_discovery import extract_listing
    from job_extraction import extract
    for path in (ROOT/'work/codex-focused-search').glob('*-source.json'):
        try:
            saved=json.loads(path.read_text(encoding='utf-8'))
            data=saved.get('data') or saved
            entry=saved.get('entry') or {}
            target=entry.get('url') or (data.get('metadata') or {}).get('url') or (data.get('metadata') or {}).get('sourceURL')
            if not target:continue
            raw,evidence,final=extract_listing(data,target)
            if not raw:continue
            doc=extract(data,raw,evidence)
            job=normalize(raw)
            duplicate=bool(aliases(job)&set(known))
            result['cached_postings'].append({'path':str(path),'url':target,'company':raw.company,'title':raw.title,
                'status':doc['status'],'issues':doc['issues'],'known':duplicate,'chars':len(doc['full_description_markdown']),
                'query':entry.get('actual_query') or entry.get('query') or '',
                'modified':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat()})
        except Exception as exc:
            result['cached_postings'].append({'path':str(path),'error':str(exc)})
    result['unified_outbox']=json.loads((ROOT/'reports/discovery/unified-pending.json').read_text())
    result['usage']=history.usage()
    save('audit.json',result)
    if not (OUT/'tracker-before.json').exists():
        save('tracker-before.json',snapshot(remote))
        save('ledger-before.json',history.usage())
        save('baseline-requests.json',{'ids':[r[0] for r in history_read(history,'SELECT id FROM requests') ]})
    print(json.dumps({'pending_reasons':result['pending_reasons'],'history':result['history'],
        'providers':result['providers'],'cached_postings':len(result['cached_postings']),
        'unknown_cached':[r for r in result['cached_postings'] if not r.get('known')],
        'legacy_pending':result['legacy_pending'],'usage':result['usage']},indent=2),flush=True)

def history_read(history,sql):
    with history.connect() as con:return con.execute(sql).fetchall()

class Recovery:
    def __init__(self,remote,history,store):
        self.remote,self.history,self.store=remote,history,store
        self.preferences=load_preferences()
        self.rejections=remote.rejected_jobs_index()
        self.baseline=json.loads((OUT/'tracker-before.json').read_text())
        self.baseline_ids=set(self.baseline['rows'])
        self.stage='pending recovery'
        self.receipts=json.loads((OUT/'verified-jobs.json').read_text()) if (OUT/'verified-jobs.json').exists() else []
        self.coverage={}
        self.excluded=Counter()
        self.free_attempts=[]
        self.checkpoints=[]
        self.last_panel=0
        self.engine=Engine(history,store,self.preferences,publish=self.publish)
        self.known=self.engine.seed(remote,self.rejections)
        self.known_names=set(self.known)
        self.engine.progress=lambda report:self.panel()
        from watch_gecko_search import prepare_panel
        prepare_panel(remote)

    def panel(self,activity=None,force=False,status='running'):
        if not force and time.monotonic()-self.last_panel<30:return
        self.last_panel=time.monotonic()
        from watch_gecko_search import LABELS
        stamp=datetime.now(ZONE)
        with self.history.connect() as con:
            counts=dict(con.execute('SELECT state,COUNT(*) FROM daily_candidates GROUP BY state').fetchall())
        value={'run_id':'recovery-20261025','status':status,'stage':self.stage,
            'activity':activity or self.stage,'verified_job_ids':[r['id'] for r in self.receipts],
            'pending_jobs_recovered':sum(r['kind']=='pending recovered' for r in self.receipts),
            'additional_new_jobs':sum(r['kind']=='additional new' for r in self.receipts),
            'published_jobs_verified':len(self.receipts),'source_health':self.coverage,
            'candidates_excluded':dict(self.excluded),'candidate_states':counts,
            'free_retrievals':len(self.free_attempts),'firecrawl_usage':self.history.usage(),
            'resumes_generated':0,'applications_submitted':0,'checked_at':stamp.isoformat()}
        save('live.json',value)
        (ROOT/'reports/discovery/live-status.json').write_text(json.dumps(value,indent=2),encoding='utf-8')
        rows=[LABELS,[status,str(len(self.receipts))+' verified new this run',value['activity'],
                     stamp.strftime('%m-%d-%Y | %I:%M %p %Z'),stamp.strftime('%m-%d-%Y | %I:%M %p %Z')]]
        try:
            self.remote.api.values().update(spreadsheetId=self.remote.config.spreadsheet_id,
                range="'Daily Run'!H1:L2",valueInputOption='RAW',body={'values':rows}).execute()
        except Exception as exc:
            save('panel-error.json',{'error':str(exc)})

    def publish(self,job):
        # Cached/current accepted evidence is revalidated by the canonical writer.
        from resume_match import check,spreadsheet_scores
        review=check(job)
        if not review['accepted']:raise RuntimeError('Current match gate no longer accepts job')
        blocker=location_blocker(job)
        if blocker:raise RuntimeError(blocker)
        # Current public feed evidence or a valid recent cache must establish
        # availability; for a cache-only candidate use a free availability check.
        if self.stage=='pending recovery':
            from link_validation import validate_job
            availability=validate_job(job)
            self.free_attempts.append({'purpose':'availability of accepted cached posting','url':job.url,
                                       'status':availability.status,'reason':availability.reason})
            if availability.status!='valid':raise RuntimeError('Availability unverified: '+availability.reason)
        publish_verified(self.remote,job)
        from query_provenance import query_for_job
        expected={'Company':job.company,'Job Title':job.title,'Query Used to Find':query_for_job(job),**spreadsheet_scores(review)}
        matches=[v for _,v in self.remote.scout().rows if str(v.get('Scout ID',v.get('ID')))==str(job.id)]
        if len(matches)!=1:raise RuntimeError('Independent ID readback failed')
        row=matches[0]
        for name,value in expected.items():
            actual=row.get(name)
            if isinstance(value,(int,float)):
                if abs(float(actual)-value)>0.001:raise RuntimeError('Score readback differs: '+name)
            elif str(actual or '')!=str(value or ''):
                raise RuntimeError('Independent readback differs: '+name)
        if str(job.id) in self.baseline_ids:raise RuntimeError('Existing job cannot count as a new addition')
        receipt={'id':job.id,'kind':'pending recovered' if self.stage=='pending recovery' else 'additional new',
                 'employer':job.company,'title':job.title,'url':row['Job URL'],
                 'score':row.get('Match Score'),'responsibilities':row.get('Responsibilities Match'),
                 'required_skills':row.get('Required Skills Match'),'query':row.get('Query Used to Find'),
                 'verified_at':datetime.now(timezone.utc).isoformat()}
        if not any(r['id']==job.id for r in self.receipts):self.receipts.append(receipt)
        self.known_names.update(aliases(job))
        save('verified-jobs.json',self.receipts)
        print('VERIFIED '+json.dumps(receipt),flush=True)
        self.panel('Published '+job.company+' / '+job.title,force=True)

    def cached_candidates(self):
        from firecrawl_discovery import extract_listing
        from job_extraction import extract,salary_display
        from query_provenance import remember
        from link_validation import BOT,EXPIRED
        result=[]
        for path in (ROOT/'work/codex-focused-search').glob('*-source.json'):
            try:
                value=json.loads(path.read_text(encoding='utf-8'));data=value.get('data') or {}
                entry=value.get('entry') or {}
                target=entry.get('url') or (data.get('metadata') or {}).get('url') or (data.get('metadata') or {}).get('sourceURL')
                if not target:continue
                raw,evidence,final=extract_listing(data,target)
                if not raw:continue
                doc=extract(data,raw,evidence)
                if (datetime.now(timezone.utc).timestamp()-path.stat().st_mtime)>86400:
                    self.excluded['cache older than valid 24-hour retrieval window']+=1;continue
                text=doc['full_description_markdown']
                if BOT.search(text[:3000]) or EXPIRED.search(text):
                    self.excluded['cached access challenge or expired posting']+=1;continue
                query=entry.get('actual_query') or ''
                raw.metadata['_query_used_to_find']=query
                raw.description=text
                raw.employment_type='; '.join(doc['fields']['employment_types']) or raw.employment_type
                raw.salary=salary_display(doc['fields']['salary']) or raw.salary
                raw.remote_type=doc['fields']['work_arrangement'] or raw.remote_type
                raw.metadata['_recovery_document']=doc
                if doc['status']!='complete':raw.metadata['_incomplete']=True
                remember([raw])
                result.append(raw)
            except Exception as exc:self.excluded['cached parse needs review: '+str(exc)[:100]]+=1
        return result

    def prepare(self,keys):
        """Batch local classification checkpoints; no external effects in this stage."""
        changes=[]
        original_update=self.engine.update
        self.engine.update=lambda key,**values:changes.append((key,values))
        try:
            result=self._prepare(keys)
            with self.history.connect() as con:
                for key,values in changes:
                    con.execute('UPDATE daily_candidates SET '+','.join(name+'=?' for name in values)+' WHERE key=?',
                                [*values.values(),key])
                    if 'state' in values or 'reason' in values:
                        con.execute('INSERT INTO daily_events(candidate,at,state,reason) VALUES(?,?,?,?)',
                            (key,datetime.now(timezone.utc).isoformat(),values.get('state'),values.get('reason')))
            return result
        finally:self.engine.update=original_update

    def _prepare(self,keys):
        from hard_filters import deterministic_filter
        from google_tracker import resume_approval_value
        from job_extraction import extract,markdown
        from dataclasses import replace
        from firecrawl_postings import reject_result
        result=[]
        snapshots={};key_list=list(keys)
        with self.history.connect() as con:
            for start in range(0,len(key_list),250):
                chunk=key_list[start:start+250]
                snapshots.update((r['key'],r) for r in con.execute('SELECT * FROM daily_candidates WHERE key IN ('+','.join('?' for _ in chunk)+')',chunk))
        for index,key in enumerate(key_list):
            row=snapshots[key]
            if index%1000==0:self.panel('Filtering cached candidates: '+str(index)+'/'+str(len(key_list)))
            raw=RawListing(**json.loads(row['raw_json']))
            job=normalize(raw)
            if row['state']=='duplicate':
                self.excluded['verified requisition alias skipped before review']+=1;continue
            if aliases(job)&self.known_names:
                self.excluded['known before retrieval']+=1;continue
            source_blocker=source_location_blocker(raw)
            if source_blocker:
                self.engine.pending(key,source_blocker,retry=False)
                self.excluded['structured source country ineligible/unknown']+=1;continue
            declared_area=' '.join([job.title,job.location,str(raw.metadata.get('applicantLocationRequirements') or '')])
            if (re.search(r'\b(?:Bulgaria|Romania|Philippines|South Africa|Serbia|Poland|Argentina|Brazil|LATAM|EMEA)\b| - PH\b',declared_area,re.I)
                    and not re.search(r'\b(?:United States|USA|Worldwide|Global)\b',declared_area,re.I)):
                self.engine.pending(key,'Explicit foreign-only location; U.S./Utah eligibility not established',retry=False)
                self.excluded['explicit foreign-only location']+=1;continue
            allowed,reason=deterministic_filter(job,self.preferences)
            if not allowed or self.rejections.matches_job(job):
                reason=reason if not allowed else 'permanent rejection'
                self.engine.update(key,state='rejected',reason=reason,policy=self.engine.policy)
                self.excluded[reason]+=1;continue
            if row['state']=='rejected' and row['policy']==self.engine.policy:
                self.excluded['unchanged reviewed/filtered rejection']+=1;continue
            if reject_result(raw.url,raw.title,datetime.now(timezone.utc)):
                self.engine.pending(key,'Non-posting/talent pool/old URL needs source review',retry=False)
                self.excluded['not an exact current posting']+=1;continue
            doc=raw.metadata.get('_recovery_document')
            content=json.loads(row['content_json']) if row['content_json'] else None
            if doc and doc['status']=='complete':content={'description':doc['full_description_markdown'],'url':raw.url,'document':doc}
            elif not content and complete(raw):
                source=replace(raw,metadata={**raw.metadata,'description':raw.description})
                doc=extract({'markdown':markdown(raw.description)},source,'')
                if doc['status']=='complete':content={'description':doc['full_description_markdown'],'url':raw.url,'document':doc}
            if not content:
                self.engine.pending(key,'Incomplete source description; free recovery required',retry=False)
                continue
            job.description=content['description'];job.details=content.get('document') or {}
            job.authoritative_url=content.get('url') or job.url
            job.url_verification_status='verified'
            fields=job.details.get('fields',{})
            blocker=location_blocker(job)
            if blocker:
                self.engine.pending(key,blocker,retry=False)
                self.excluded['country/region eligibility unverified']+=1;continue
            if fields.get('application_fee_required') is True:
                self.engine.update(key,state='rejected',reason='Mandatory application fee',policy=self.engine.policy)
                self.excluded['mandatory fee']+=1;continue
            allowed,reason=deterministic_filter(job,self.preferences)
            if not allowed or resume_approval_value(job.location,job.work_arrangement,'')!='Yes':
                self.engine.pending(key,reason if not allowed else 'Location/remote eligibility unverified',retry=False)
                self.excluded['location or salary ineligible/unknown']+=1;continue
            self.engine.update(key,content_json=json.dumps(content),retry_mode='auto',retry_at=None)
            result.append({'id':key,'key':key,'job':job})
        # Relevant paid-media/analytics evidence gets reviewed first, without a quota.
        result.sort(key=lambda r:(not any(t in r['job'].title.casefold() for t in ['paid','ppc','sem','performance','analytics']),r['job'].company))
        save(self.stage.replace(' ','-')+'-review-queue.json',[{'key':r['key'],'job':r['job'].to_dict()} for r in result])
        print('REVIEW QUEUE '+json.dumps({'stage':self.stage,'eligible_complete':len(result),'excluded':dict(self.excluded)}),flush=True)
        return result

    def rounds(self,candidates):
        from focused_discovery import run_round
        from resume_match import check
        confirmed=[]
        def review(candidate):
            job=candidate['job']
            decision=check(job)
            if decision.get('accepted'):
                from description_readiness import assess
                assess([{'id':candidate['key'],'company':job.company,'title':job.title,'description':job.description}])
            return decision
        finished=set();publication_attempts=set()
        def checkpoint(candidate,status,detail):
            key=candidate['key']
            if status in ('pending','published','duplicate') or (status=='reviewed' and not detail.get('accepted')):
                finished.add(key)
            if status=='reviewed':
                self.engine.update(key,review_json=json.dumps(detail),policy=self.engine.policy)
                if not detail['accepted']:
                    if detail['status']=='pending':self.engine.pending(key,detail.get('reason','Match review pending'))
                    else:self.engine.update(key,state='rejected',reason=detail.get('reason','Below 60/50/50'),policy=self.engine.policy)
            record={'key':key,'status':status,'detail':detail,'at':datetime.now(timezone.utc).isoformat()}
            with (OUT/'events.jsonl').open('a',encoding='utf-8') as stream:stream.write(json.dumps(record,default=str)+'\n')
            if status in ('reviewed','pending','published'):print('CANDIDATE '+json.dumps({'key':key,'company':candidate['job'].company,'title':candidate['job'].title,'status':status,'accepted':detail.get('accepted') if isinstance(detail,dict) else None,'score':detail.get('score') if isinstance(detail,dict) else None}),flush=True)
        def publish(candidate,decision):
            publication_attempts.add(candidate['key'])
            self.engine.review=lambda job:decision
            previous=len(self.receipts)
            self.engine.process(candidate['key'],self.rejections)
            receipt=next((r for r in self.receipts[previous:] if r['id']==candidate['job'].id),None)
            # Engine constructs the reserved JobListing separately; use readback receipts.
            if len(self.receipts)>previous:
                receipt=self.receipts[-1];confirmed.append(candidate['key'])
                return {'verified':True,**receipt}
            return {'verified':False,'reason':'Canonical publication pending; evidence retained'}
        try:
            run_round(candidates,target=len(candidates),confirmed=lambda:confirmed,
                identity=lambda c:c['key'],known=lambda c:bool(aliases(c['job'])&self.known_names),
                review=review,publish=publish,checkpoint=checkpoint,
                status=lambda s,d:self.panel(self.stage+': '+s),max_workers=3)
        except RuntimeError as exc:
            print('ROUND BLOCKER '+str(exc),flush=True)
            save('round-blocker-'+self.stage.replace(' ','-')+'.json',{'error':str(exc)})
            for key in publication_attempts-finished:
                self.engine.pending(key,'Publication remains pending: '+str(exc),retry=False)
            remaining=[c for c in candidates if c['key'] not in finished|publication_attempts]
            if remaining:self.rounds(remaining)
        finally:self.engine.review=check

    def recover(self):
        self.panel('Auditing qualified outboxes and cached employer descriptions',force=True)
        with self.history.connect() as con:
            qualified=con.execute('SELECT COUNT(*) FROM daily_candidates WHERE job_json IS NOT NULL AND published=0').fetchone()[0]
        if qualified:self.engine.run([],tracker=self.remote,rejections=self.rejections,publish_only=True)
        from firecrawl_discovery import flush_pending
        with self.history.connect() as con:
            legacy=con.execute("SELECT COUNT(*) FROM candidates WHERE verification_status='validated'").fetchone()[0]
        if legacy:flush_pending(history=self.history,remote=self.remote,store=self.store)
        raws=self.cached_candidates()
        with self.history.lock():
            keys=self.engine.ingest(raws,self.known,self.rejections)
            self.rounds(self.prepare(keys))
        self.panel('Cached pending recovery phase complete',force=True)

    def finalize(self):
        from sheet_sync import ensure_frozen_headers
        ensure_frozen_headers(self.remote)
        after=snapshot(self.remote);save('tracker-after.json',after)
        changed=[key for key,value in self.baseline['rows'].items() if after['rows'].get(key)!=value]
        new={key:row for key,row in after['rows'].items() if key not in self.baseline_ids}
        result={'verified_jobs':self.receipts,'pending_recovered':sum(r['kind']=='pending recovered' for r in self.receipts),
            'additional_new':sum(r['kind']=='additional new' for r in self.receipts),'new_tracker_ids':list(new),
            'existing_rows_changed':changed,'headers_preserved':after['headers']==self.baseline['headers'],
            'coverage':self.coverage,'excluded':dict(self.excluded),'free_attempts':self.free_attempts,'ledger_after':self.history.usage()}
        save('result.json',result)
        self.panel('Recovery/coverage complete; all additions independently verified',force=True,status='complete')
        print('FINAL '+json.dumps(result,default=str),flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=['audit','recover'])
    args=parser.parse_args()
    scout.load_local_environment()
    scout.load_local_environment(ROOT/'.env.google-sheets.local')
    native_root=Path(os.environ['LOCALAPPDATA'])/'OpenAI/Codex/bin'
    native=sorted(native_root.glob('*/codex.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
    if native:os.environ['PATH']=str(native[0].parent)+os.pathsep+os.environ['PATH']
    if config().get('usage_unlimited'):
        raise RuntimeError('Unlimited override active; normal provider limits required')
    with run_lock(),JobStore() as store:
        remote=GoogleTracker(config=Config.from_environment())
        history=History()
        if args.stage=='audit':audit(remote,history,store)
        elif args.stage=='recover':
            operation=Recovery(remote,history,store)
            operation.recover()
            operation.finalize()

if __name__=='__main__':main()
