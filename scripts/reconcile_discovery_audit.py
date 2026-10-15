"""Offline record-by-record reconciliation of saved discovery evidence."""
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit
import csv
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'job-scout'))
from models import RawListing, JobListing
from normalize import normalize, canonicalize_url
from hard_filters import deterministic_filter
from source_policy import is_jooble_candidate
from service import _same_source_identity_conflicts
from deduplicate import find_duplicate
from google_tracker import resume_approval_value
from rejected_jobs import RejectedJob, RejectedJobsIndex

def main():
    out=ROOT/'reports/discovery-audit/20261013'
    live=json.loads((out/'live-before.json').read_text())
    config=json.loads((out/'configuration.json').read_text())
    db=json.loads((out/'database.json').read_text())
    links=defaultdict(list)
    for r in db['source_links']: links[r['job_id']].append(r)
    known=[]
    for r in db['jobs']:
        r['source_links']=links[r['id']];r['tags']=json.loads(r.get('tags_json','[]'))
        known.append(JobListing.from_dict(r))
    rejected_range=next(v for v in live['values']['valueRanges'] if v['range'].startswith("'Rejected Jobs'"))
    values=rejected_range['values'];headers=values[0]
    rejected=RejectedJobsIndex(RejectedJob.from_mapping(dict(zip(headers,r))) for r in values[1:])
    live_urls={canonicalize_url(str(r.get('Job URL'))) for _,r in live['ledger_rows'] if r.get('Job URL')}
    live_by_url={canonicalize_url(str(r.get('Job URL'))):r for _,r in live['ledger_rows'] if r.get('Job URL')}
    def posting_key(url):
        parts=urlsplit(str(url or ''))
        if parts.hostname in {'apply.workable.com','www.apply.workable.com'}:
            pieces=parts.path.strip('/').split('/')
            if 'j' in pieces and pieces.index('j')+1<len(pieces):
                return ('workable',pieces[pieces.index('j')+1].casefold())
        canonical=urlsplit(canonicalize_url(str(url or '')))
        return ('url',canonical.netloc+canonical.path+'?'+canonical.query)
    live_keys={posting_key(r.get('Job URL')) for _,r in live['ledger_rows'] if r.get('Job URL')}
    new=[];table=[];records=[];recovery=[]
    for name, settings in config['sources']['providers'].items():
        path=out/(name+'.json');retry=out/'retry'/(name+'.json')
        if retry.exists():path=retry
        if not path.exists():
            table.append({'source':name,'enabled':settings.get('enabled',True),'queries':0,'raw_parsed':0,
                          'status':'intentionally disabled, not executed','tracker_written':0})
            continue
        result=json.loads(path.read_text());counts=Counter();seen=set();source_records=[]
        for r in result['raw']:
            raw=RawListing(**r);job=normalize(raw)
            identity=(raw.source.casefold(), raw.source_job_id or canonicalize_url(raw.url))
            reason='';match=None
            if identity in seen:reason='duplicates within source'
            seen.add(identity)
            if not reason and is_jooble_candidate(source=raw.source,urls=(raw.url,),metadata=raw.metadata):reason='disabled Jooble provenance'
            if not reason and (not raw.title or (not raw.description and not callable_feed(name))):reason='missing title or content'
            if not reason and rejected.matches_job(job):reason='previously rejected'
            if not reason:
                accepted, gate=deterministic_filter(job,config['preferences'])
                if not accepted:reason=gate
            if not reason:
                match=find_duplicate(job,[k for k in known if not _same_source_identity_conflicts(job,k)])
                if match:
                    sources={match.source.casefold(),*(str(link.get('source','')).casefold()
                              for link in match.source_links)}
                    if raw.source.casefold() not in sources:
                        counts['subset: cross-source previously known'] += 1
                    urls=[match.url,match.canonical_url,*[l.get('url','') for l in match.source_links]]
                    present=any(posting_key(u) in live_keys for u in urls)
                    reason='previously known in live tracker' if present else 'previously known only in database'
                    if not present:
                        recovery.append({'source':name,'source_job_id':job.source_job_id,'url':job.url,
                                         'title':job.title,'blocked_by_database_id':match.id})
            if not reason:
                match=find_duplicate(job,[k for k in new if not _same_source_identity_conflicts(job,k)])
                if match:reason='cross-source duplicates' if match.source.casefold()!=job.source.casefold() else 'duplicates within source'
            if not reason:
                reason='new unique';new.append(job)
                counts['eligible new unique']+=int(resume_approval_value(job.location,job.work_arrangement,'')=='Yes')
            counts[reason]+=1
            source_records.append({'source':name,'source_job_id':job.source_job_id,'url':job.url,
                'title':job.title,'company':job.company,'reason':reason,'matched_database_id':getattr(match,'id',None)})
        assert sum(v for k,v in counts.items() if k!='eligible new unique' and not k.startswith('subset:'))==len(result['raw'])
        error_count=len(result['errors'])+len(result['board_errors'])+len(result['detail_errors'])
        row={'source':name,'enabled':settings.get('enabled',True),'queries':len(result['queries']),
             'raw_parsed':len(result['raw']),'source_errors':error_count,
             'status':'partial failure' if error_count and result['raw'] else 'failure' if error_count else result['status'],
             'tracker_written':0,'reconciled':True,'evidence':str(path.relative_to(ROOT)),
             'windows':result['observed_date_windows'],**dict(counts)}
        table.append(row);records.extend(source_records)
    (out/'reconciliation.json').write_text(json.dumps({'sources':table,'record_count':len(records),
        'new_unique':len(new),'eligible_new_unique':sum(r.get('eligible new unique',0) for r in table),
        'database_only_blocks':len(recovery),'caveat':'Parsed adapter records; not unobserved historical HTTP search hits. No tracker writes.',
        'new_jobs':[j.to_dict() for j in new],'database_only_candidates':recovery},indent=2))
    (out/'record-decisions.json').write_text(json.dumps(records,indent=2))
    columns=sorted(set().union(*(r.keys() for r in table))-{'windows'})
    with (out/'source-reconciliation.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(table)
    print('Reconciled',len(records),'records; new unique',len(new),'database-only blocks',len(recovery))

def callable_feed(name):
    return name in {'remotive','jobicy','remoteok','greenhouse','lever','ashby','workable','weworkremotely','workingnomads'}

if __name__=='__main__':main()
