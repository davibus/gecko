"""Reconcile only first-party, tenant-qualified Greenhouse internal IDs."""
from recover_gecko_pending import *
from collections import defaultdict
from hard_filters import deterministic_filter
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
with run_lock(),JobStore() as store:
    history=History();remote=GoogleTracker(config=Config.from_environment())
    receipts=json.loads((OUT/'verified-jobs.json').read_text());baseline=json.loads((OUT/'tracker-before.json').read_text())['rows']
    tab=remote.scout();sheet={str(v.get('Scout ID',v.get('ID'))):(n,v) for n,v in tab.rows}
    groups=defaultdict(list)
    with history.connect() as con:
        records=con.execute("SELECT * FROM daily_candidates WHERE json_extract(raw_json,'$.source')='greenhouse'").fetchall()
    for row in records:
        raw=RawListing(**json.loads(row['raw_json']));reqs={a for a in aliases(normalize(raw)) if a.startswith('requisition:')}
        if len(reqs)==1:groups[next(iter(reqs))].append((row,raw))
    changes=[];duplicates=[]
    prefs=load_preferences()
    for req,members in groups.items():
        if len(members)<2:continue
        def rank(pair):
            row,raw=pair;job_id=str(row['gecko_id']);saved=sheet.get(job_id,(None,{}))[1]
            return (job_id in baseline,bool(saved.get('Apply?')=='Yes'),
                bool(not source_location_blocker(raw) and deterministic_filter(normalize(raw),prefs)[0]),
                -int(row['gecko_id'] or 999999999))
        from recover_gecko_pending import source_location_blocker
        canonical,raw_canonical=max(members,key=rank)
        target=canonical['key'];canonical_id=canonical['gecko_id']
        with history.connect() as con:
            for row,raw in members:
                job=normalize(raw)
                if row['key']==target:
                    for alias in aliases(job):con.execute('INSERT OR IGNORE INTO daily_aliases VALUES(?,?)',(alias,target))
                    continue
                reason='Verified duplicate of Greenhouse internal requisition '+req+'; canonical Gecko ID '+str(canonical_id or 'pending')
                job_id=str(row['gecko_id'])
                if job_id in sheet and job_id not in baseline:
                    number,saved=sheet[job_id]
                    if saved.get('Apply?')!='No':
                        remote._write(tab,number,{'Apply?':'No','Notes':str(saved.get('Notes') or '')+'\n'+reason})
                        readback=next(v for _,v in remote.scout().rows if str(v.get('Scout ID',v.get('ID')))==job_id)
                        if readback['Apply?']!='No':raise RuntimeError('Duplicate hold readback failed')
                    duplicates.extend(r for r in receipts if r['id']==row['gecko_id'])
                    receipts=[r for r in receipts if r['id']!=row['gecko_id']]
                con.execute('UPDATE daily_aliases SET candidate=? WHERE candidate=?',(target,row['key']))
                for alias in aliases(job):con.execute('INSERT OR IGNORE INTO daily_aliases VALUES(?,?)',(alias,target))
                con.execute("UPDATE daily_candidates SET state='duplicate',published=1,reason=? WHERE key=?",(reason,row['key']))
                con.execute('INSERT INTO daily_events(candidate,at,state,reason) VALUES(?,?,?,?)',(row['key'],datetime.now(timezone.utc).isoformat(),'duplicate',reason))
                changes.append({'key':row['key'],'gecko_id':row['gecko_id'],'canonical_key':target,'canonical_gecko_id':canonical_id,'requisition':req,'source_posting_id':raw.source_job_id})
    save('verified-jobs.json',receipts);save('verified-requisition-aliases.json',changes);save('duplicate-history-rows.json',duplicates)
    print(json.dumps({'verified_unique_jobs':len(receipts),'duplicate_tracker_rows_retained':len(duplicates),'verified_candidate_aliases':len(changes),'requisitions':len({r['requisition'] for r in changes})}))
