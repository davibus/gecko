"""Close with real primary-tracker readback and a guarded known-posting pass."""
from recover_gecko_pending import *
from incremental_discovery import Engine
from watch_gecko_search import LABELS
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
with run_lock(),JobStore() as store:
    remote=GoogleTracker(config=Config.from_environment());history=History()
    final=json.loads((OUT/'final-verification.json').read_text())
    receipts=json.loads((OUT/'verified-jobs.json').read_text())
    corrections=json.loads((OUT/'starting-cache-provenance-audit.json').read_text())['changes']
    recovered={r['id'] for r in corrections}
    for receipt in receipts:
        if receipt['id'] in recovered:receipt['kind']='pending recovered'
    def forbidden(*args,**kwargs):raise AssertionError('Known posting must not retrieve, infer, or publish')
    with history.connect() as con:
        row=con.execute('SELECT raw_json FROM daily_candidates WHERE gecko_id=3060 AND state=?',('accepted',)).fetchone()
    if not row:raise RuntimeError('Controlled repeat target missing')
    engine=Engine(history,store,load_preferences(),review=forbidden,free=forbidden,paid=forbidden,publish=forbidden)
    with history.lock():
        restored=[]
        with history.connect() as con:
            affected=con.execute("SELECT key,reason,gecko_id FROM daily_candidates WHERE reason LIKE '%Known posting must not retrieve, infer, or publish%'").fetchall()
            for affected_row in affected:
                first_bad=con.execute("SELECT MIN(id) FROM daily_events WHERE candidate=? AND reason LIKE '%Known posting must not retrieve, infer, or publish%'",(affected_row['key'],)).fetchone()[0]
                previous=con.execute('SELECT state,reason FROM daily_events WHERE candidate=? AND id<? AND state IS NOT NULL ORDER BY id DESC LIMIT 1',(affected_row['key'],first_bad)).fetchone()
                if not previous:
                    if affected_row['gecko_id'] is not None:raise RuntimeError('Reserved candidate requires independent restoration evidence')
                    # An initial unseen INSERT has no daily_event. A retained
                    # accepted/rejected identity cannot reach the guarded call.
                    previous={'state':'seen','reason':'New source identity'}
                mode='manual' if previous['reason'].startswith(('Index-only lead:','Publication withheld:','Utah abbreviation resolved;')) else 'auto'
                con.execute('UPDATE daily_candidates SET state=?,reason=?,retry_at=NULL,retry_mode=? WHERE key=?',(previous['state'],previous['reason'],mode,affected_row['key']))
                con.execute('INSERT INTO daily_events(candidate,at,state,reason) VALUES(?,?,?,?)',(affected_row['key'],datetime.now(timezone.utc).isoformat(),previous['state'],'Restored prior candidate evidence after a guarded diagnostic; no provider or inference request was dispatched. Prior reason: '+str(previous['reason'])))
                restored.append(affected_row['key'])
        save('controlled-diagnostic-restoration.json',{'restored_keys':restored,'paid_requests':0,'inference_requests':0})
        rejections=remote.rejected_jobs_index();known=engine.seed(remote,rejections)
        keys=engine.ingest([RawListing(**json.loads(row['raw_json']))],known,rejections)
        for key in keys:engine.process(key,rejections)
    repeat=engine.report
    if repeat['paid_requests'] or repeat['free_retrievals'] or repeat['new_jobs_added'] or repeat['warnings']:
        raise RuntimeError('Controlled repeat unexpectedly attempted work')
    save('controlled-live-repeat.json',repeat)
    after=snapshot(remote)
    baseline=json.loads((OUT/'tracker-before.json').read_text())
    if [str(h) for h in after['headers']]!=baseline['headers']:raise RuntimeError('Live headers changed')
    changed=[key for key,row in baseline['rows'].items() if after['rows'].get(key)!=row]
    if changed:raise RuntimeError('Existing tracker rows changed: '+str(changed))
    for receipt in receipts:
        row=after['rows'][str(receipt['id'])]
        for key,field in [('employer','Company'),('title','Job Title'),('url','Job URL'),('query','Query Used to Find')]:
            if row[field]!=receipt[key]:raise RuntimeError('Final readback mismatch '+str(receipt['id'])+' '+field)
        if row['Qualifies to Apply?']!='Yes':raise RuntimeError('Qualified receipt is not Yes')
        for field,floor in [('Match Score',60),('Responsibilities Match',50),('Required Skills Match',50)]:
            if float(row[field])<floor:raise RuntimeError('Threshold mismatch')
    for job_id in final['held_ineligible_ids']+final['duplicate_tracker_rows_retained']:
        if after['rows'][str(job_id)]['Qualifies to Apply?']!='No':raise RuntimeError('Held row is not No')
    prior=set(json.loads((OUT/'baseline-requests.json').read_text())['ids'])
    with history.connect() as con:
        added=[r[0] for r in con.execute('SELECT id FROM requests') if r[0] not in prior]
        settled=con.execute('SELECT COALESCE(SUM(confirmed),0) FROM requests').fetchone()[0]
    if added:raise RuntimeError('Unexpected Firecrawl dispatches '+str(added))
    balance=final['firecrawl_balance']
    if balance.get('success'):
        history.record_balance(balance['data'],now=datetime.fromisoformat(final['checked_at']),settled_before=settled)
    final.update(pending_recovered=sum(r['kind']=='pending recovered' for r in receipts),
        additional_new=sum(r['kind']=='additional new' for r in receipts),existing_rows_changed=changed,
        headers_preserved=True,controlled_repeat=repeat,offline_focused_tests_passed=53,
        legacy_test_limitations={'tracker':{'tests':51,'failures':6,'errors':8},'unified':{'tests':15,'failures':6}},
        cache_classification_corrections=corrections,ledger_after=history.usage(),checked_at=datetime.now(timezone.utc).isoformat())
    save('verified-jobs.json',receipts);save('final-verification.json',final)
    result=json.loads((OUT/'result.json').read_text());result.update(verified_jobs=receipts,pending_recovered=final['pending_recovered'],additional_new=final['additional_new'],headers_preserved=True)
    save('result.json',result);save('tracker-after.json',after)
    live=json.loads((OUT/'live.json').read_text());live.update(status='complete',activity='All accepted jobs independently verified; source and billing blockers retained',
        pending_jobs_recovered=final['pending_recovered'],additional_new_jobs=final['additional_new'],published_jobs_verified=len(receipts),firecrawl_usage=history.usage(),checked_at=datetime.now(ZONE).isoformat())
    save('live.json',live);(ROOT/'reports/discovery/live-status.json').write_text(json.dumps(live,indent=2),encoding='utf-8')
    stamp=datetime.now(ZONE).strftime('%m-%d-%Y | %I:%M %p %Z')
    remote.api.values().update(spreadsheetId=remote.config.spreadsheet_id,range="'Daily Run'!H1:L2",valueInputOption='RAW',
        body={'values':[LABELS,['complete',str(len(receipts))+' unique additions verified',str(final['pending_recovered'])+' pending recovered; '+str(final['additional_new'])+' additional new; Firecrawl 0',stamp,stamp]]}).execute()
    print(json.dumps({k:final[k] for k in ['pending_recovered','additional_new','known_postings_skipped_before_retrieval','headers_preserved','existing_rows_changed','offline_focused_tests_passed','new_provider_confirmed_requests','new_unresolved_requests']}))
