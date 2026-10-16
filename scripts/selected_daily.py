"""Bounded daily work: only named jobs, with canonical resume generation and QA."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'job-scout'), str(ROOT/'scripts')]
from sqlite_tracker import SQLiteTracker, stamp
from tracker_backend import DATABASE
from generate_apply_queue import validate_requested_ids, read_queue, run_queue, _append_run_log

def preflight(tracker, ids):
    validate_requested_ids(tracker, ids)
    for name in ('master-resume-v2.txt','MODEL-GECKO-PRODUCT_Dave_Call_Resume.pdf'):
        path = ROOT/'input/master-resume'/name
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError('Missing required resume authority: '+name)
    queue = read_queue(tracker, eligible_scout_ids=ids, auto_approve_geographic=False)
    if any(item.scout_id not in ids for item in queue.pending):
        raise RuntimeError('Queue escaped the selected job IDs')
    result = {'selected_ids':sorted(ids),'pending_ids':[i.scout_id for i in queue.pending],
              'discovery':'not run in selected-job mode; no other jobs are added or processed',
              'automatic_approval':False}
    print(json.dumps(result),flush=True)
    return result

class ResponseScope:
    def __init__(self, tracker, ids):
        self.tracker = tracker
        self.ids = ids
        self.rows = set(validate_requested_ids(tracker,ids).values())
    def applied_response_rows(self):
        return [r for r in self.tracker.applied_response_rows() if int(r['Scout ID']) in self.ids]
    def update_response_rows(self, updates):
        if set(updates)-self.rows:
            raise RuntimeError('Response write outside selected jobs blocked')
        return self.tracker.update_response_rows(updates)

def responses(tracker,ids):
    scoped = ResponseScope(tracker,ids)
    if not scoped.applied_response_rows():
        print('No selected jobs are marked Applied; employer response check is not applicable.',flush=True)
        return
    from gmail_response_tracker import GmailConfig,GmailReader,build_gmail_service,run_response_check
    config = GmailConfig.from_environment()
    gmail = GmailReader(build_gmail_service(config,interactive=False),request_delay_seconds=config.request_delay_seconds)
    result = run_response_check(scoped,gmail,config)
    print(f'Employer response rows updated: {result.tracker_rows_updated}',flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step',choices=['preflight','resumes','responses'])
    parser.add_argument('--ids',type=int,nargs='+',required=True)
    args=parser.parse_args()
    if len(set(args.ids)) != len(args.ids) or any(i<=0 for i in args.ids):
        parser.error('Distinct positive job IDs are required')
    ids=set(args.ids)
    inherited=os.environ.get('GECKO_ALLOWED_JOB_IDS')
    if inherited and {int(i) for i in inherited.split(',')} != ids:
        raise RuntimeError('Selected IDs differ from the parent run scope')
    os.environ['GECKO_ALLOWED_JOB_IDS']=','.join(map(str,sorted(ids)))
    tracker=SQLiteTracker()
    preflight(tracker,ids)
    if args.step=='resumes':
        result=run_queue(tracker,DATABASE,eligible_scout_ids=ids,auto_approve_geographic=False,logger=_append_run_log)
        summary={'selected_ids':sorted(ids),'created':result.created,'recovered':result.recovered,
                 'failures':len(result.failures),'exit_code':result.exit_code,'finished_at':stamp()}
        with tracker.connection() as con, con:
            con.execute('INSERT INTO workspace_runs VALUES(?,?,?,?)',
                        ('selected:'+summary['finished_at'],summary['finished_at'],'failed' if result.exit_code else 'complete',json.dumps(summary)))
        return result.exit_code
    if args.step=='responses':responses(tracker,ids)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
