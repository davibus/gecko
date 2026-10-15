"""Reconcile saved canonical discovery evidence; no network or tracker writes."""
import csv,json,sys
from pathlib import Path
from collections import Counter
from urllib.parse import urlsplit

def main(folder):
    aggregate=json.loads((folder/'discovery-reconciliation.json').read_text())
    requests=json.loads((folder/'http-requests.json').read_text())
    readback=json.loads((folder/'independent-readback.json').read_text())
    tracker=json.loads((folder/'tracker-result.json').read_text())
    config=json.loads((folder/'effective-config-after.json').read_text())
    host_source={'api.adzuna.com':'adzuna','remotive.com':'remotive','jobicy.com':'jobicy',
        'remoteok.com':'remoteok','data.usajobs.gov':'usajobs','boards-api.greenhouse.io':'greenhouse',
        'api.lever.co':'lever','api.ashbyhq.com':'ashby','apply.workable.com':'workable','www.workable.com':'workable',
        'weworkremotely.com':'weworkremotely','www.workingnomads.com':'workingnomads',
        'workingnomads.com':'workingnomads'}
    source_requests={}
    for event in requests:
        source=host_source.get(urlsplit(event['endpoint']).hostname)
        if source:source_requests.setdefault(source,[]).append(event)
    source_for_id={}
    for source,pipeline in aggregate['source_pipeline'].items():
        for job_id in pipeline['new_job_ids']+pipeline['existing_job_ids']:source_for_id.setdefault(job_id,source)
    rows=[];all_decisions=[];checks=[]
    for source,settings in config['providers'].items():
        path=folder/f'{source}.json'
        evidence=json.loads(path.read_text()) if path.exists() else {}
        pipeline=evidence.get('pipeline',{})
        decisions=evidence.get('record_decisions',[])
        all_decisions.extend(decisions)
        reasons=Counter(v['reason'] for v in decisions)
        parsed=pipeline.get('fetched',0)
        checks.append({'source':source,'parsed':parsed,'decisions':len(decisions),'exclusive_reasons':dict(reasons),
                       'reconciled':parsed==len(decisions)==sum(reasons.values())})
        events=evidence.get('queries_pages',[])
        reqs=source_requests.get(source,[])
        success=[r for r in reqs if r.get('status')==200]
        raw_observed=sum(r.get('raw_records',0) for r in success)
        fields_observed=any('raw_records' in r for r in success)
        identity_counts=Counter((v['source'],v['source_job_id'] or v['url']) for v in decisions)
        first_attempts=[r for r in reqs if r.get('attempt')==1]
        query_count=len({(v.get('query'),v.get('location')) for v in events if 'query' in v})
        if not query_count:query_count=len(first_attempts)
        written=[j for j in readback['affected_jobs'] if source_for_id.get(j['job_id'])==source]
        status=aggregate.get('source_health',{}).get(source,{}).get('status','disabled' if not settings.get('enabled') else 'not attempted')
        if aggregate.get('source_errors',{}).get(source) and not parsed:status='blocked'
        source_error=aggregate.get('source_errors',{}).get(source,'')
        try:error_count=len(json.loads(source_error)) if source_error else 0
        except (ValueError,TypeError):error_count=int(bool(source_error))
        row={'source':source,'enabled':settings.get('enabled'), 'status':status,
             'queries_or_feed_board_requests':query_count,
             'pages_attempted':len(events) if events and 'query' in events[0] else len(first_attempts),
             'pages_completed':0 if status=='blocked' else sum(v.get('status')=='completed' for v in events) if events and 'query' in events[0] else len(success),
             'zero_result_queries_pages':0 if status=='blocked' else sum(v.get('status')=='completed' and v.get('parsed')==0 for v in events),
             'raw_http_records':raw_observed if fields_observed else 'unknown' if status in ('blocked','missing key','api error') else '',
             'successfully_parsed_listings':parsed,
             'source_errors':error_count,
             'pre_normalization_exclusions':max(raw_observed-parsed,0) if fields_observed else '',
             'pre_normalization_exclusion_reason':'Remote OK API metadata record without position' if source=='remoteok' and raw_observed>parsed else '',
             'repeated_source_id_occurrences_raw':sum(v-1 for v in identity_counts.values()),
             'previously_known_records':reasons['previously known'],
             'duplicates_within_current_run_records':reasons['duplicate within run'],
             'cross_source_duplicates_subset':sum(bool(v.get('cross_source')) for v in decisions),
             'rejection_history_excluded':reasons['rejection history'],
             'eligibility_filter_excluded':pipeline.get('deterministic_rejects',0),
             'missing_content_excluded':reasons['missing content'],
             'disabled_jooble_excluded':reasons['disabled Jooble provenance'],
             'confirmed_dead_url_excluded':reasons['confirmed dead URL'],
             'url_review_excluded':reasons['URL requires review'],
             'url_verified_records':pipeline.get('url_validated',0),
             'new_unique_local_jobs':reasons['new unique'],
             'unique_verified_candidates':len(pipeline.get('new_job_ids',[]))+len(pipeline.get('existing_job_ids',[])),
             'new_job_list_rows':sum(bool(v['new']) for v in written),
             'eligible_new_job_list_rows':sum(v['new'] and v['values'].get('Apply?')=='Yes' for v in written),
             'existing_job_list_rows_updated':sum(not v['new'] for v in written),
             'errors':aggregate.get('source_errors',{}).get(source,'')}
        for reason,count in pipeline.get('deterministic_reject_reasons',{}).items():row['excluded: '+reason]=count
        rows.append(row)
    columns=list(dict.fromkeys(k for row in rows for k in row))
    with (folder/'source-reconciliation.csv').open('w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=columns);writer.writeheader();writer.writerows(rows)
    (folder/'source-reconciliation.json').write_text(json.dumps(rows,indent=2))
    (folder/'record-decisions.json').write_text(json.dumps(all_decisions,indent=2))
    (folder/'count-reconciliation-checks.json').write_text(json.dumps(checks,indent=2))
    summary={'parsed':sum(v['successfully_parsed_listings'] for v in rows),
             'raw_http_records_observed':sum(v.get('raw_records',0) for v in requests if v.get('status')==200),
             'exclusive_reasons':dict(Counter(v['reason'] for v in all_decisions)),
             'local_new':aggregate['newly_discovered'],'unique_existing_matches':aggregate['already_existed'],
             'sheet':tracker,'readback_verified':readback['verified'],
             'all_source_counts_reconciled':all(v['reconciled'] for v in checks),
             'source_rows':rows}
    (folder/'final-reconciliation.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_rows','sheet')},indent=2))

if __name__=='__main__':main(Path(sys.argv[1]))
