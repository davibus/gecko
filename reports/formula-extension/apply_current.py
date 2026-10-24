"""Repair formula/formatting gaps and save reviewed Enough Data values by ID."""
import sys,json
from pathlib import Path
sys.path[:0]=['C:/gecko_main/job-scout','C:/gecko_main/scripts']
sys.stdout.reconfigure(encoding='utf-8')
import scout,sheet_sync
from google_tracker import GoogleTracker,Config
from description_columns import description_value
from sheet_ranges import extend_job_list
from run_gecko import run_lock
from sqlite_daily_report import backup_workspace
P=Path(__file__).resolve().parent
scout.load_local_environment();scout.load_local_environment(Path('C:/gecko_main/.env.google-sheets.local'))
inputs={str(r['id']):r for r in json.loads((P/'readiness-input.json').read_text(encoding='utf-8'))}
reviews=json.loads((P/'readiness-results.json').read_text(encoding='utf-8'))
assert all(r['status']=='reviewed' for r in reviews.values()),'Content review pending; do not publish a fabricated decision'
with run_lock():
    backup=backup_workspace();remote=GoogleTracker(config=Config.from_environment());before=remote.scout()
    snapshot={str(r['Scout ID']):dict(r) for _,r in before.rows if r.get('Scout ID')}
    extension=extend_job_list(remote,before)
    fresh=remote.scout();updates={}
    for number,row in fresh.rows:
        key=str(row.get('Scout ID') or '')
        if key not in reviews or str(row.get('Enough Data') or '').strip():continue
        assert description_value(row)==inputs[key]['description'],(key,'Description changed during review')
        updates[number,'Enough Data']=reviews[key]['value']
        old=str(row.get('Notes') or '')
        updates[number,'Notes']=old+('\n' if old else '')+'Enough Data content review: '+reviews[key]['value']+' — '+reviews[key]['reason']
    entries,expected=remote._prepare_writes(fresh,updates)
    assert all(expected.get(key)==value for key,value in updates.items()),'Protected formula or concurrent change prevented a content review update'
    (P/'before-readiness-write.json').write_text(json.dumps({'backup':backup,'extension':extension,
        'before':{str(n):r for n,r in fresh.rows if (n,'Enough Data') in updates},
        'expected':[{'row':n,'field':h,'value':v} for (n,h),v in expected.items()]},indent=2),encoding='utf-8')
    if entries:remote.api.values().batchUpdate(spreadsheetId=remote.config.spreadsheet_id,
        body={'valueInputOption':'RAW','data':entries}).execute()
    after=remote.scout();actual=dict(after.rows)
    for (n,h),value in expected.items():assert actual[n].get(h,'')==value,(n,h,'Readback mismatch')
    formulas=remote.scout(value_render_option='FORMULA')
    count_headers=['# (Gecko) Words','# (FC) Job Desc Words','Total Words']
    for number,row in formulas.rows:
        if str(row.get('Scout ID') or '').isdigit():
            for h in count_headers:assert str(row.get(h,'')).startswith('='),(number,h,'Formula missing')
    by_id={str(r.get('Scout ID')):r for _,r in after.rows}
    protected=['Company','Job Title','Applied','Applied Date','Resume Created','Resume Link','Job URL',
               'Gecko Job Description','FireCrawl Job Description','Personal priority']
    for key,old in snapshot.items():
        for h in protected:assert old.get(h,'')==by_id[key].get(h,''),(key,h,'Unexpected data change')
    sheet_sync.ensure_frozen_headers(remote)
    result={'extension':extension,'content_reviews_saved':sum(h=='Enough Data' for n,h in expected),'last_job_row':max(n for n,r in after.rows if r.get('Scout ID')),
        'word_count_columns':count_headers,'all_word_formulas_verified':True,'sync':sheet_sync.sync(),'backup':backup_workspace()}
    (P/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2),flush=True)
