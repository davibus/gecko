"""Collect Indeed result pages and append verified new jobs to local SQLite."""
import argparse
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'job-scout'))
from google_tracker import load_environment
from sqlite_tracker import SQLiteTracker
from storage import JobStore
from normalize import normalize, posting_identity
from deduplicate import find_duplicate
from hard_filters import deterministic_filter
from preferences import load_preferences
from sources.indeed_search import IndeedSearchProvider
from description_retrieval import description_is_sufficient
from run_gecko import run_lock


def import_new(listings, tracker, report_dir):
    """Append only; existing job rows and their manual decisions remain untouched."""
    preferences=load_preferences()
    before=tracker.scout()
    before_rows=dict(before.rows)
    identities={posting_identity(str(d.get('Job URL') or '')) for _,d in before.rows if d.get('Job URL')}
    rejected=tracker.rejected_jobs_index()
    with tracker.connection() as con:
        archived_ids={str(row[0]) for row in con.execute("SELECT id FROM workspace_jobs WHERE archived=1")}
    result={'added_ids':[],'existing':[],'excluded':[]}
    if not (report_dir/'before.sqlite3').exists():
        with tracker.connection() as live, closing(sqlite3.connect(report_dir/'before.sqlite3')) as backup:
            live.backup(backup)
    with JobStore(tracker.path) as store:
        store.observe_scout_id(max((int(d['Scout ID']) for _,d in before.rows if str(d.get('Scout ID','')).isdigit()),default=0))
        known=store.all()
        ready=[]
        for raw in listings:
            job=normalize(raw,discovered=datetime.now(ZoneInfo('America/Denver')).date().isoformat())
            allowed,reason=deterministic_filter(job,preferences)
            if not allowed or not description_is_sufficient(job.description):
                result['excluded'].append({'key':raw.source_job_id,'reason':reason if not allowed else 'insufficient description'})
                continue
            if rejected.matches_job(job):
                result['excluded'].append({'key':raw.source_job_id,'reason':'rejection history'})
                continue
            if posting_identity(job.url) in identities:
                result['existing'].append({'key':raw.source_job_id,'reason':'already in tracker'})
                continue
            duplicate=find_duplicate(job,known)
            if duplicate:
                if str(duplicate.id) in archived_ids:
                    result['excluded'].append({'key':raw.source_job_id,'reason':'previously archived job'})
                    continue
                # Recover a prior interrupted import only for this exact Indeed identity.
                if duplicate.source=='indeed' and duplicate.source_job_id==job.source_job_id and str(duplicate.id) not in {str(d.get('Scout ID')) for _,d in before.rows}:
                    job=duplicate
                else:
                    result['existing'].append({'key':raw.source_job_id,'id':duplicate.id,'reason':'duplicate posting'})
                    continue
            else:
                job.id=store.save(job)
                known.append(job)
            ready.append(job);identities.add(posting_identity(job.url))
        notes={job.id:'Indeed direct search verified '+datetime.now(ZoneInfo('America/Denver')).isoformat(timespec='seconds')+' | Firecrawl | Full posting retrieved; no application submitted.' for job in ready}
        written=tracker.upsert_scout(ready,append_only=True,discovery_notes=notes,audit_dir=report_dir)
        result['added_ids']=written.get('added_ids',[])
    after=tracker.scout()
    for row,old in before_rows.items():
        if dict(after.rows).get(row)!=old:
            raise RuntimeError('An existing tracker row changed during import; inspect audit')
    for job in ready:
        matches=[d for _,d in after.rows if str(d.get('Scout ID'))==str(job.id)]
        if len(matches)!=1 or matches[0].get('Job URL')!=job.url:
            raise RuntimeError('New Indeed job failed independent identity readback')
    result['readback_verified']=True
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query',action='append',help='Repeat for multiple role searches')
    parser.add_argument('--location',action='append',help='Repeat for locations; default Utah and Remote')
    parser.add_argument('--max-pages',type=int,default=5)
    parser.add_argument('--max-jobs',type=int,default=150)
    parser.add_argument('--collect-only',action='store_true',help='Save evidence without importing jobs')
    args=parser.parse_args()
    if not 1<=args.max_pages<=20 or not 1<=args.max_jobs<=500:parser.error('Use 1–20 pages and 1–500 postings')
    load_environment()
    folder=ROOT/'reports/indeed-search'/datetime.now().strftime('%Y%m%dT%H%M%S%f')
    folder.mkdir(parents=True)
    provider=IndeedSearchProvider(queries=args.query,locations=args.location,max_pages=args.max_pages,max_jobs=args.max_jobs)
    listings=[]
    try:
        for listing in provider.full_feed():
            listings.append(listing)
            print(json.dumps({'retrieved':len(listings),'key':listing.source_job_id}),flush=True)
            (folder/'listings.json').write_text(json.dumps([asdict(j) for j in listings],ensure_ascii=False),encoding='utf-8')
    finally:
        report={'mode':provider.discovery_mode,'queried':provider.queries,'locations':provider.locations,
                'unique_postings_attempted':len(provider.seen_jobs),'retrieved':len(listings),
                'pages':provider.acquisition_events,'errors':provider.errors,'exclusions':provider.exclusions,
                'limits':provider.limits,'coverage':'partial' if provider.errors or provider.limits else 'observed result pages exhausted'}
        (folder/'collection.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if not args.collect_only and listings:
        with run_lock():report['import']=import_new(listings,SQLiteTracker(),folder)
    report['report_directory']=str(folder)
    (folder/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)
    return 2 if provider.errors else 0


if __name__=='__main__':raise SystemExit(main())
