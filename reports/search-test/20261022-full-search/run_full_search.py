"""Authorized full manual search, with per-run settings and shared credit ledger.

Uses canonical Scout/unified discovery/publication; never changes scheduled settings.
Cheap date, identity and preference checks precede URL verification/enrichment.
"""
import sys,json,threading
from pathlib import Path
from datetime import datetime,timezone,timedelta
from dataclasses import replace
from collections import Counter
ROOT=Path('C:/gecko_main');HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8');sys.stderr.reconfigure(encoding='utf-8')
import scout,unified_search,firecrawl_discovery
from firecrawl_state import config,History
from sources.firecrawl import FirecrawlClient
from storage import JobStore,DEFAULT_DB
from google_tracker import GoogleTracker
from preferences import load_preferences
from normalize import normalize,posting_identity
from hard_filters import deterministic_filter
from run_gecko import run_lock
from sqlite_daily_report import backup_workspace
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
HERE.mkdir(parents=True,exist_ok=True)
settings=config();settings.update(enabled=True,daily_enabled=True,daily_soft_credits=200,daily_hard_credits=200)
assert settings['posting_window_hours']==96
history=History(settings=settings);client=FirecrawlClient(history=history,settings=settings)
usage_before=history.usage();(HERE/'usage-before.json').write_text(json.dumps(usage_before,indent=2),encoding='utf-8')
print(json.dumps({'mode':'full manual discovery','daily_credit_cap':200,'remaining_accounted_today':max(0,200-usage_before['total_credits_accounted']),'window_hours':96,'contracts':True,'maximum_starting_base':120000}),flush=True)
prefs=load_preferences();cutoff=datetime.now(timezone.utc)-timedelta(hours=96)
stats={};stats_lock=threading.Lock()
with run_lock():
    print(json.dumps({'backup_before':backup_workspace()}),flush=True)
with JobStore(DEFAULT_DB) as store:
    existing=store.all()
    known_urls={posting_identity(u) for j in existing for u in [j.url,j.canonical_url,j.authoritative_url,j.original_url,*[s.get('url','') for s in j.source_links]] if u}
    known_ids={(j.source.casefold(),j.source_job_id) for j in existing if j.source_job_id}
    for _,r in GoogleTracker().scout().rows:
        if r.get('Job URL'):known_urls.add(posting_identity(r['Job URL']))
    original_acquire=scout.acquire_source
    original_providers=scout.providers
    def providers_without_repeated_failures(*args,**kwargs):
        from sources.unavailable import UnavailableProvider
        available=original_providers(*args,**kwargs)
        for name in ('web-careers','linkedin','glassdoor','ziprecruiter','remote-careers'):
            available[name]=UnavailableProvider(name,'Attempted in this full search; slow or inaccessible page retrieval. Retrying unchanged sources would waste time. Employer APIs and Firecrawl discovery continue.',status='needs attention')
        return available
    scout.providers=providers_without_repeated_failures
    pending=unified_search._pending()
    staged=store.get(2885)
    if staged and staged.company=='Maximus' and staged.title=='Digital Marketing Specialist':
        pending['job_ids']=list(dict.fromkeys(pending['job_ids']+[2885]))
        unified_search._save(unified_search.PENDING,pending)
        print('Recovered staged job 2885 from the interrupted attempt',flush=True)
    def acquire_recent(provider,requests):
        requests=[replace(r,days=4) for r in requests]
        rows,errors=original_acquire(provider,requests)
        kept=[];counts=Counter(fetched=len(rows));seen=set()
        for raw in rows:
            identity=(raw.source.casefold(),raw.source_job_id)
            url_identity=posting_identity(raw.url)
            if identity in known_ids or url_identity in known_urls:
                counts['already_known']+=1;continue
            if identity in seen:
                counts['same_source_duplicate']+=1;continue
            seen.add(identity)
            if raw.source=='greenhouse':
                raw.date_posted=str(raw.metadata.get('first_published') or raw.metadata.get('datePosted') or '')
            elif raw.source=='lever' and raw.metadata.get('createdAt'):
                raw.date_posted=datetime.fromtimestamp(raw.metadata['createdAt']/1000,timezone.utc).isoformat()
            try:
                posted=datetime.fromisoformat(raw.date_posted.replace('Z','+00:00'))
                if posted.tzinfo is None:posted=posted.replace(tzinfo=timezone.utc)
            except (ValueError,TypeError):
                counts['original_date_unverified']+=1;continue
            if posted < cutoff:counts['outside_four_days']+=1;continue
            if posted > datetime.now(timezone.utc):counts['future_date']+=1;continue
            accepted,reason=deterministic_filter(normalize(raw),prefs)
            if not accepted:
                counts['filter: '+reason]+=1;continue
            kept.append(raw)
        counts['passed_cheap_checks']=len(kept)
        (HERE/('accepted-'+provider.name+'.json')).write_text(json.dumps([__import__('dataclasses').asdict(r) for r in kept],indent=2),encoding='utf-8')
        with stats_lock:
            stats[provider.name]={'counts':dict(counts),'errors':errors}
            (HERE/'source-progress.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
        print('EARLY FILTERS '+json.dumps({'source':provider.name,**dict(counts)}),flush=True)
        return kept,errors
    scout.acquire_source=acquire_recent
    unified_search.config=lambda:dict(settings)
    original_smart=firecrawl_discovery.run_discovery
    def smart(store,preferences,**kwargs):
        return original_smart(store,preferences,history=history,client=client,**kwargs)
    unified_search.run_discovery=smart
    args=scout.build_parser().parse_args(['search','--source','all','--unified','--results','50','--location','Remote','--location','Utah','--audit-dir',str(HERE/'canonical-audit')])
    # Canonical search covers all configured providers and all saved target roles.
    code=scout.search(args,store,prefs)
    print(json.dumps({'canonical_exit_code':code,'usage_after':history.usage(),'raw_acquisition':stats}),flush=True)
    assert history.usage()['total_credits_accounted']<=200
with run_lock():
    print(json.dumps({'backup_after':backup_workspace()}),flush=True)
raise SystemExit(code)
