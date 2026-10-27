"""Exclude the pre-stop Spain-only row without deleting its history."""
from recover_gecko_pending import *
from sheet_sync import ensure_frozen_headers
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
with run_lock(),JobStore() as store:
    remote=GoogleTracker(config=Config.from_environment());history=History();job=store.get(2998)
    reason=location_blocker(job)
    if not reason or 'Spain' not in reason:raise RuntimeError('Exact source restriction not established')
    tab=remote.scout();n,row=next((n,v) for n,v in tab.rows if str(v.get('Scout ID',v.get('ID')))=='2998')
    if row['Company']!='Grafana Labs' or '6233353004' not in row['Job URL']:raise RuntimeError('Exact posting mismatch')
    remote._write(tab,n,{'Apply?':'No','Notes':str(row.get('Notes') or '')+'\nLocation review: '+reason})
    after=next(v for _,v in remote.scout().rows if str(v.get('Scout ID',v.get('ID')))=='2998')
    if after['Apply?']!='No':raise RuntimeError('Qualification readback failed')
    with history.connect() as con:con.execute("UPDATE daily_candidates SET state='pending',published=0,reason=? WHERE gecko_id=2998",(reason,))
    receipts=json.loads((OUT/'verified-jobs.json').read_text());blocked=json.loads((OUT/'blocked-location-jobs.json').read_text())
    blocked.extend(r for r in receipts if r['id']==2998)
    receipts=[r for r in receipts if r['id']!=2998]
    save('verified-jobs.json',receipts);save('blocked-location-jobs.json',blocked)
    save('spain-variant-correction.json',{'id':2998,'reason':reason,'readback_verified':True,'record_retained':True})
    ensure_frozen_headers(remote)
    print(json.dumps({'verified_matches':len(receipts),'pending_recovered':sum(r['kind']=='pending recovered' for r in receipts),'additional_new':sum(r['kind']=='additional new' for r in receipts),'held_id':2998}))
