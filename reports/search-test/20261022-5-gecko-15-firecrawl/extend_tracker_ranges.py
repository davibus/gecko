"""Apply and audit the requested Job List range repair only."""
import sys,json
from pathlib import Path
ROOT=Path('C:/gecko_main');HERE=Path(__file__).resolve().parent/'range-extension'
sys.path[:0]=[str(ROOT/'job-scout'),str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8')
import scout
from google_tracker import GoogleTracker,Config
from run_gecko import run_lock
from sheet_ranges import extend_job_list,METADATA
from sqlite_daily_report import backup_workspace
scout.load_local_environment();scout.load_local_environment(ROOT/'.env.google-sheets.local')
HERE.mkdir(parents=True,exist_ok=True)
with run_lock():
    tracker=GoogleTracker(config=Config.from_environment())
    before=tracker.tab('Job List',value_render_option='FORMULA')
    metadata=tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,fields=METADATA).execute()
    (HERE/'before.json').write_text(json.dumps({'metadata':metadata,'headers':before.header_values,'rows':before.rows},indent=2),encoding='utf-8')
    result=extend_job_list(tracker,before)
    after=tracker.tab('Job List',value_render_option='FORMULA')
    expected=dict(before.rows)
    permitted={'Ready to Apply?','Create Resume','# Words','# Job Desc Words','Total Words'}
    assert before.header_values==after.header_values
    assert [n for n,_ in before.rows]==[n for n,_ in after.rows]
    changed=[]
    for n,data in after.rows:
        for header in before.header_values:
            old=expected[n].get(header,'');new=data.get(header,'')
            if old!=new:
                assert n>=1146 and header in permitted and old=='' and str(new).startswith('='),(n,header)
                changed.append({'row':n,'field':header,'formula':new})
    # A second pass must be a no-op, proving the automatic path is repeatable.
    second=extend_job_list(tracker,after)
    assert second['requests']==0
    after_metadata=tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,fields=METADATA).execute()
    target=next(s for s in after_metadata['sheets'] if s['properties']['title']=='Job List')
    assert 'basicFilter' not in target  # Dave explicitly chose to leave filters off.
    assert target['properties']['gridProperties']['frozenRowCount']>=1
    for original in metadata['sheets']:
        if original['properties']['title']!='Job List':
            assert original==next(s for s in after_metadata['sheets'] if s['properties']['sheetId']==original['properties']['sheetId'])
    report={'result':result,'second_pass':second,'changed_formulas':changed,'filters_off':'basicFilter' not in target,
            'frozen_rows':target['properties']['gridProperties']['frozenRowCount'],'verified':True}
    (HERE/'readback.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
