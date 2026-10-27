"""Resume durable complete queues without repeating source discovery."""
from extend_gecko_coverage import Coverage
from recover_gecko_pending import *
from recover_gecko_pending import source_location_blocker
from models import JobListing
from resume_match import check,spreadsheet_scores
from query_provenance import query_for_job

scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
native=sorted((Path(os.environ['LOCALAPPDATA'])/'OpenAI/Codex/bin').glob('*/codex.exe'),key=lambda p:p.stat().st_mtime,reverse=True)
if native:os.environ['PATH']=str(native[0].parent)+os.pathsep+os.environ['PATH']
with run_lock(),JobStore() as store:
    remote=GoogleTracker(config=Config.from_environment());history=History()
    receipts=json.loads((OUT/'verified-jobs.json').read_text())
    blocked=json.loads((OUT/'blocked-location-jobs.json').read_text())
    baseline=json.loads((OUT/'tracker-before.json').read_text())['rows']
    tab=remote.scout()
    with history.connect() as con:
        raw_rows={r['gecko_id']:r for r in con.execute('SELECT * FROM daily_candidates WHERE gecko_id IS NOT NULL')}
    for number,row in tab.rows:
        job_id=str(row.get('Scout ID',row.get('ID')) or '')
        if not job_id.isdigit() or job_id in baseline:continue
        job=store.get(int(job_id))
        if not job:raise RuntimeError('New tracker row has no durable local evidence '+job_id)
        rows=[raw_rows[int(job_id)]] if int(job_id) in raw_rows else []
        raw=RawListing(**json.loads(rows[0]['raw_json'])) if rows else None
        reason=(source_location_blocker(raw) if raw else '') or location_blocker(job)
        if reason:
            if row.get('Apply?')!='No':
                remote._write(tab,number,{'Apply?':'No','Notes':str(row.get('Notes') or '')+'\nLocation review: '+reason})
                saved=next(v for _,v in remote.scout().rows if str(v.get('Scout ID',v.get('ID')))==job_id)
                if saved['Apply?']!='No':raise RuntimeError('Hold readback failed')
            with history.connect() as con:con.execute("UPDATE daily_candidates SET state='pending',published=0,reason=? WHERE gecko_id=?",(reason,int(job_id)))
            blocked.extend(r for r in receipts if r['id']==int(job_id) and not any(b['id']==int(job_id) for b in blocked))
            receipts=[r for r in receipts if r['id']!=int(job_id)]
            continue
        if row.get('Apply?')!='Yes':continue
        if any(r['id']==int(job_id) for r in receipts):continue
        review=check(job)
        if not review.get('cached') or not review.get('accepted'):raise RuntimeError('Interrupted row lacks valid cached acceptance '+job_id)
        expected={'Company':job.company,'Job Title':job.title,'Query Used to Find':query_for_job(job),**spreadsheet_scores(review)}
        for field,value in expected.items():
            if isinstance(value,(int,float)):
                if abs(float(row[field])-value)>0.001:raise RuntimeError('Score mismatch '+job_id)
            elif str(row.get(field) or '')!=str(value or ''):raise RuntimeError('Field mismatch '+field)
        if posting_identity(row['Job URL'])!=posting_identity(job.url):raise RuntimeError('URL mismatch')
        original=json.loads((OUT/'pending-audit.json').read_text())['pending']
        old_urls={posting_identity(x['url']) for x in original}
        receipts.append({'id':int(job_id),'kind':'pending recovered' if posting_identity(job.url) in old_urls else 'additional new',
            'employer':job.company,'title':job.title,'url':row['Job URL'],'score':row['Match Score'],
            'responsibilities':row['Responsibilities Match'],'required_skills':row['Required Skills Match'],
            'query':row['Query Used to Find'],'verified_at':datetime.now(timezone.utc).isoformat(),'reconciled_interrupted_write':True})
        with history.connect() as con:con.execute("UPDATE daily_candidates SET state='accepted',published=1,reason='Publication independently reconciled' WHERE gecko_id=?",(int(job_id),))
    save('verified-jobs.json',receipts);save('blocked-location-jobs.json',blocked)
    operation=Coverage(remote,history,store)
    operation.coverage=json.loads((OUT/'live.json').read_text()).get('source_health',{})
    operation.coverage.update(json.loads((OUT/'remaining-source-coverage.json').read_text()))
    operation.stage='complete source queue recovery'
    keys=set()
    for name in ('configured-free-source-coverage-review-queue.json','additional-employer-coverage-review-queue.json'):
        keys.update(r['key'] for r in json.loads((OUT/name).read_text()))
    with history.lock():operation.rounds(operation.prepare(keys))
    operation.finalize()
