"""Independent reconciliation after the supervised location-guard stop."""
from recover_gecko_pending import *
from resume_match import check,spreadsheet_scores
from query_provenance import query_for_job
from sheet_sync import ensure_frozen_headers

scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
with run_lock(),JobStore() as store:
    remote=GoogleTracker(config=Config.from_environment());history=History()
    receipts=json.loads((OUT/'verified-jobs.json').read_text())
    blocked=json.loads((OUT/'blocked-location-jobs.json').read_text())
    tab=remote.scout()
    for job_id in (2982,2984):
        job=store.get(job_id);reason=location_blocker(job)
        if not reason:raise RuntimeError('Expected source restriction missing')
        matches=[(n,v) for n,v in tab.rows if str(v.get('Scout ID',v.get('ID')))==str(job_id)]
        if len(matches)!=1:raise RuntimeError('Exact row is not unique')
        number,row=matches[0]
        if posting_identity(row['Job URL']) not in {posting_identity(job.url),posting_identity(job.authoritative_url)}:
            raise RuntimeError('Source identity differs')
        remote._write(tab,number,{'Apply?':'No','Notes':str(row.get('Notes') or '')+'\nLocation review: '+reason})
        after=next(v for _,v in remote.scout().rows if str(v.get('Scout ID',v.get('ID')))==str(job_id))
        if after['Apply?']!='No':raise RuntimeError('Ineligible decision readback failed')
        with history.connect() as con:con.execute("UPDATE daily_candidates SET state='pending',published=0,reason=? WHERE gecko_id=?",(reason,job_id))
        blocked.extend(r for r in receipts if r['id']==job_id)
        receipts=[r for r in receipts if r['id']!=job_id]
        tab=remote.scout()
    # Recover the in-flight writer's result only through full independent readback.
    job=store.get(2994)
    review=check(job)
    if location_blocker(job) or not review['accepted'] or not review.get('cached'):
        raise RuntimeError('Interrupted posting requires review; no inferred receipt')
    matches=[v for _,v in remote.scout().rows if str(v.get('Scout ID',v.get('ID')))=='2994']
    if len(matches)!=1:raise RuntimeError('Interrupted publication not found uniquely')
    row=matches[0]
    expected={'Company':job.company,'Job Title':job.title,'Query Used to Find':query_for_job(job),**spreadsheet_scores(review)}
    for field,value in expected.items():
        if isinstance(value,(int,float)):
            if abs(float(row[field])-value)>0.001:raise RuntimeError('Score mismatch')
        elif row[field]!=value:raise RuntimeError('Field mismatch: '+field)
    if posting_identity(row['Job URL']) not in {posting_identity(job.url),posting_identity(job.authoritative_url)}:raise RuntimeError('URL mismatch')
    receipt={'id':job.id,'kind':'pending recovered','employer':job.company,'title':job.title,'url':row['Job URL'],
        'score':row['Match Score'],'responsibilities':row['Responsibilities Match'],'required_skills':row['Required Skills Match'],
        'query':row['Query Used to Find'],'verified_at':datetime.now(timezone.utc).isoformat(),'reconciled_interrupted_write':True}
    if not any(r['id']==job.id for r in receipts):receipts.append(receipt)
    with history.connect() as con:con.execute("UPDATE daily_candidates SET state='accepted',published=1,reason='Interrupted publication independently reconciled' WHERE gecko_id=2994")
    save('verified-jobs.json',receipts);save('blocked-location-jobs.json',blocked)
    ensure_frozen_headers(remote)
    save('reconciliation.json',{'verified_matches':len(receipts),'blocked_ids':[r['id'] for r in blocked],'reconciled':receipt})
    print(json.dumps({'verified_matches':len(receipts),'blocked_ids':[r['id'] for r in blocked],'reconciled_id':job.id}))
