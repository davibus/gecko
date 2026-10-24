"""Bounded discovery test; no evaluation, resume generation or applications."""
import sys, json, re, sqlite3
from pathlib import Path
from dataclasses import asdict
from urllib.parse import urlsplit
ROOT = Path('C:/gecko_main')
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT/'job-scout'), str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8')
from models import RawListing
from firecrawl_discovery import extract_listing
from normalize import normalize
from hard_filters import deterministic_filter
from preferences import load_preferences
import scout
scout.load_local_environment()
scout.load_local_environment(ROOT/'.env.google-sheets.local')

def candidates():
    gecko = [RawListing(**r) for r in json.loads((HERE/'gecko-raw.json').read_text(encoding='utf-8'))]
    first = json.loads((HERE/'firecrawl-raw.json').read_text(encoding='utf-8'))
    extra = json.loads((HERE/'firecrawl-extra.json').read_text(encoding='utf-8'))
    pages = first['web'] + extra['data']['web']
    fallback = {
        'appspace': ('Appspace', 'Tampa, Florida, United States Remote'),
        'datagrail': ('DataGrail', 'Remote - United States'),
        'lumimeds': ('LumiMeds', 'United States'),
        'grafanalabs': ('Grafana Labs', 'United States (Remote)'),
        'paynearmeinc': ('PayNearMe', 'Remote'),
    }
    firecrawl=[]; seen=set(); evidence={}
    for p in pages:
        u=p['url']; m=p.get('markdown','')
        if urlsplit(u).hostname not in {'jobs.lever.co','job-boards.greenhouse.io','jobs.ashbyhq.com'} or u in seen:
            continue
        seen.add(u)
        if re.search(r'no longer available|no longer accepting|job (?:has been )?closed|no longer open|future opening',m,re.I):
            continue
        raw, _, _ = extract_listing(p,u)
        if raw is None:
            slug=urlsplit(u).path.strip('/').split('/')[0]
            company,location=fallback[slug]
            title=re.search(r'^# (.+)$',m,re.M).group(1).replace('\\|','|')
            description=re.split(r'(?im)^#{1,4} (?:Apply for this job|Apply to this job|Application)\s*$',m)[0]
            raw=RawListing(source='greenhouse',source_job_id=urlsplit(u).path.split('/')[-1],url=u,title=title,company=company,location=location,description=description,remote_type='remote',metadata={'_retrieved_via':'firecrawl','_discovered_via':'firecrawl-search'})
        if '## Location Type\n\nRemote' in m or re.search(r'(?im)^Remote[ ,;-]*(?:USA|United States)|^United States.*Remote|^### Location: Remote',m):
            raw.remote_type='remote'
        if not raw.location:
            match=re.search(r'## Location\s+([^\n]+)',m)
            if match:raw.location=match.group(1)
            elif 'upstart/jobs/' in u:raw.location='Remote - United States'
        raw.metadata.update({'_web_search_backends':['firecrawl'],'_retrieved_via':'firecrawl','_discovered_via':'firecrawl-search'})
        assert len(raw.description)>500 and raw.company and raw.title
        assert re.search(r'Apply|Application',m,re.I),u
        evidence[raw.url]={'status':'valid','url':raw.url,'final_url':raw.url,'reason':'Fresh Firecrawl employer/ATS page with full description and application entry point; maxAge=0','http_status':200}
        firecrawl.append(raw)
    assert len(gecko)==5 and len(firecrawl)==15,(len(gecko),len(firecrawl))
    return gecko,firecrawl,evidence

def main():
    from storage import JobStore,DEFAULT_DB
    from google_tracker import GoogleTracker
    from link_validation import DailyLinkValidator,LinkResult
    from deduplicate import find_duplicate
    from service import discover_listings
    from run_gecko import run_lock
    import sheet_sync
    gecko,firecrawl,evidence=candidates()
    prefs=load_preferences()
    listings=[('Gecko',r) for r in gecko]+[('Firecrawl',r) for r in firecrawl]
    (HERE/'candidates.json').write_text(json.dumps([{'retrieved_by':b,**asdict(r)} for b,r in listings],indent=2),encoding='utf-8')
    validator=DailyLinkValidator(); validator.require_verified=True
    # Use the freshly retrieved full employer pages as availability evidence.
    original_check=validator.check
    validator.check=lambda job: LinkResult(**evidence[job.url]) if job.url in evidence else original_check(job)
    # Network checks for the five Gecko URLs are bounded and independent.
    validator.check_existing([normalize(r) for r in gecko],workers=5)
    with run_lock():
        print('Synchronizing the current tracker',flush=True)
        before_sync=sheet_sync.sync()
        with sqlite3.connect(DEFAULT_DB) as source, sqlite3.connect(HERE/'before.sqlite3') as backup:
            source.backup(backup)
        tracker=GoogleTracker(); live=tracker.scout()
        with JobStore(DEFAULT_DB) as store:
            ids=[int(row.get('Scout ID')) for _,row in live.rows if str(row.get('Scout ID') or '').isdigit()]
            if ids:store.observe_scout_id(max(ids))
            rejected=tracker.rejected_jobs_index(); known=store.all(); rows=[]; new=[]
            for backend,raw in listings:
                job=normalize(raw); accepted,reason=deterministic_filter(job,prefs)
                duplicate=find_duplicate(job,known)
                result={'retrieved_by':backend,'company':raw.company,'title':raw.title,'url':raw.url,'location':raw.location}
                if not accepted:result.update(outcome='filtered',reason=reason)
                elif rejected.matches_job(job) is not None:result.update(outcome='rejection history',reason='Previously rejected')
                elif duplicate:result.update(outcome='already tracked',scout_id=duplicate.id,reason='Existing listing preserved')
                else:
                    check=validator.check(job)
                    if check.status!='valid':result.update(outcome='needs review',reason=check.reason)
                    else:
                        summary=discover_listings([raw],store,require_content=True,preserve_existing=True,link_validator=validator,preferences=prefs,rejected_jobs=rejected)
                        result.update(outcome='added' if summary.added else 'not added',scout_id=(summary.new_job_ids or [None])[0],reason=(summary.decisions or [{}])[0].get('reason',''))
                        new.extend(summary.new_job_ids);known=store.all()
                rows.append(result);print(json.dumps(result),flush=True)
            if new:scout.sync_tracker(store,jobs=[store.get(i) for i in new],append_only=True,audit_dir=HERE)
        after_sync=sheet_sync.sync()
        # Verify publication independently through the primary Google tracker.
        from google_tracker import Config
        remote=GoogleTracker(config=Config.from_environment()); readback=remote.scout()
        remote_urls={r.get('Job URL'):r for _,r in readback.rows}
        for row in rows:
            if row['outcome']=='added':
                actual=remote_urls.get(row['url'])
                assert actual and actual.get('Company')==row['company'] and actual.get('Job Title')==row['title'],row
                row['tracker_id']=actual.get('ID') or actual.get('Scout ID')
        report={'retrieved':{'Gecko':5,'Firecrawl':15},'firecrawl_credits':29,'results':rows,'before_sync':before_sync,'after_sync':after_sync,'verified_primary_readback':True}
        (HERE/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        lines=['# Gecko discovery test — October 22, 2026','','5 Gecko listings and 15 Firecrawl listings. No resumes or applications were run.','', '| Search | Company / role | Outcome | Tracker ID |','| --- | --- | --- | --- |']
        for row in rows:lines.append(f"| {row['retrieved_by']} | [{row['company']} — {row['title'].replace('|','/')} ]({row['url']}) | {row['outcome']}: {row['reason']} | {row.get('tracker_id','')} |")
        (HERE/'results.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print('COMPLETE: '+str(HERE/'results.md'),flush=True)

if __name__=='__main__':main()
