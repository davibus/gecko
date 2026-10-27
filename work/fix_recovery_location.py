"""Correct one new ineligible row; retain its record and discovery evidence."""
import json
from recover_gecko_pending import *
from sheet_sync import ensure_frozen_headers

scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
with run_lock(),JobStore() as store:
    remote=GoogleTracker(config=Config.from_environment())
    tab=remote.scout()
    matches=[(number,row) for number,row in tab.rows if str(row.get('Scout ID',row.get('ID')))=='2992']
    if len(matches)!=1:raise RuntimeError('Exact new Mediboost ID is not unique')
    number,row=matches[0]
    if row['Company']!='Mediboost' or 'fc787ccedaf9' not in row['Job URL']:
        raise RuntimeError('Exact posting mismatch; correction stopped')
    reason='Location review: source applicantLocationRequirements=EG (Egypt). U.S./Utah eligibility is not established; keep ineligible/pending. Match score does not override location.'
    before=dict(row)
    remote._write(tab,number,{'Apply?':'No','Notes':str(row.get('Notes') or '')+'\n'+reason})
    after=next(v for _,v in remote.scout().rows if str(v.get('Scout ID',v.get('ID')))=='2992')
    if after['Apply?']!='No' or reason not in after.get('Notes',''):
        raise RuntimeError('Location correction readback failed')
    history=History()
    with history.connect() as con:
        con.execute("UPDATE daily_candidates SET state='pending',reason=?,published=0 WHERE gecko_id=2992",(reason,))
    receipts=json.loads((OUT/'verified-jobs.json').read_text())
    removed=[r for r in receipts if r['id']==2992]
    save('blocked-location-jobs.json',removed)
    save('verified-jobs.json',[r for r in receipts if r['id']!=2992])
    save('location-correction.json',{'id':2992,'reason':reason,'before':before,'after':after,
                                   'record_retained':True,'readback_verified':True})
    ensure_frozen_headers(remote)
    unexpected=[{'id':v.get('Scout ID',v.get('ID')),'company':v.get('Company'),'title':v.get('Job Title')}
        for _,v in remote.scout().rows if str(v.get('Scout ID',v.get('ID'))).isdigit()
        and int(v.get('Scout ID',v.get('ID')))>2975
        and int(v.get('Scout ID',v.get('ID'))) not in {r['id'] for r in receipts}]
    print(json.dumps({'corrected':2992,'verified_matches_retained':len(receipts)-len(removed),'unexpected_new_rows':unexpected}))
