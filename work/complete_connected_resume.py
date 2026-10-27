"""Retry only verified completion after a connected delivery handoff interruption."""
import json,sys,time,os
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path('C:/gecko_main');sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'job-scout')]
import generate_apply_queue as queue
from google_tracker import GoogleTracker,Config,load_environment,_col
from run_gecko import run_lock
import resume_delivery
from description_columns import description_value
from zoneinfo import ZoneInfo
ident=int(sys.argv[1]);out=Path(os.environ.get('GECKO_CONNECTED_REPORT',str(ROOT/'reports/resume-connected-2985-2991')))
load_environment();remote=GoogleTracker(config=Config.from_environment())
before=json.loads((out/f'input-{ident}.json').read_text(encoding='utf-8'))
review=json.loads((out/f'agent-review-{ident}.json').read_text(encoding='utf-8'))
tab=remote.scout();hits=[(r,d) for r,d in tab.rows if str(d.get('Scout ID'))==str(ident)]
if len(hits)!=1:raise ValueError('Unique stable ID required')
row,data=hits[0];item=queue._queue_item(tab,row,data)
if description_value(data)!=description_value(before['record']):raise ValueError('Description changed since tailoring')
scratch=ROOT/'scratch'/(item.company.replace(' ','-')+'+'+queue._row_job_number(item))
request=json.loads((scratch/'visual-review-request.json').read_text(encoding='utf-8'))
plan=json.loads((scratch/'tailoring-plan.json').read_text(encoding='utf-8'))
artifacts=queue.Artifacts(Path(request['resume']),Path(plan['listing']),visual_review=Path(request['decision_path']))
url=resume_delivery.publish(artifacts.resume)
start=time.perf_counter()
with run_lock():
    queue.record_success(item,artifacts,GoogleTracker())
    tab=remote.scout();matches=[(r,d) for r,d in tab.rows if str(d.get('Scout ID'))==str(ident)]
    if len(matches)!=1:raise ValueError('Completion ID readback failed')
    row,data=matches[0]
    if data.get('Resume Created')!='X' or data.get('Resume Link')!=url or data.get('Resume Created Date')!=datetime.now(ZoneInfo('America/Denver')).date().isoformat():
        raise ValueError('Completion marker/date/link readback failed')
    link_range=f"'{tab.title}'!{_col(tab.headers['Resume Link'])}{row}"
    result=remote.api.get(spreadsheetId=remote.config.spreadsheet_id,ranges=[link_range],includeGridData=True,
        fields='sheets(data(rowData(values(hyperlink))))').execute()
    links=[c.get('hyperlink') for s in result.get('sheets',[]) for g in s.get('data',[]) for r in g.get('rowData',[]) for c in r.get('values',[])]
    if links!=[url]:raise ValueError('Actual hyperlink target differs')
prior=json.loads((out/f'result-{ident}.json').read_text(encoding='utf-8'))
prior['prior_completion_attempt']={k:prior.get(k) for k in ('status','reason','elapsed_seconds')}
prior.update(status='complete',link=url,resume=str(artifacts.resume),started_at=before['started_at'],
    completed_at=datetime.now(timezone.utc).isoformat(),elapsed_seconds=(datetime.now(timezone.utc)-datetime.fromisoformat(before['started_at'])).total_seconds(),
    retry_tracker_seconds=time.perf_counter()-start,hyperlink_range=link_range,hyperlink_target=links[0],
    readback={k:data.get(k) for k in ('Scout ID','Company','Job Title','Resume Created','Resume Created Date','Resume Link')})
prior.pop('reason',None);prior.pop('traceback',None)
(out/f'result-{ident}.json').write_text(json.dumps(prior,indent=2),encoding='utf-8')
print(json.dumps({k:prior[k] for k in ('id','company','status','elapsed_seconds','link')},indent=2))
