"""Local daily summaries and consistent backups for the SQLite workspace."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'job-scout'))
from sqlite_tracker import SQLiteTracker, stamp


def report(tracker=None):
    tracker = tracker or SQLiteTracker()
    from generate_apply_queue import read_queue
    queue = read_queue(tracker,auto_approve_geographic=True)
    rows = [data for _,data in tracker.scout().rows if data.get('Scout ID')]
    result = {'backend':'sqlite','date':datetime.now(ZoneInfo('America/Denver')).date().isoformat(),
              'updated_at':stamp(),'jobs':len(rows),'pending_resumes':len(queue.pending),
              'completed_resumes':len(queue.already_created),
              'applied':sum(str(d.get('Applied','')).strip().casefold() in {'x','yes','true'} for d in rows),
              'sources':dict(Counter(d.get('Source','') for d in rows))}
    with tracker.connection() as con, con:
        con.execute('INSERT INTO workspace_runs VALUES(?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET at=excluded.at,report_json=excluded.report_json',
                    ('summary:'+result['date'],stamp(),'summary',json.dumps(result)))
    folder = ROOT/'reports/sqlite-daily'
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'latest.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2),flush=True)
    return result


def save_run(tracker,run_id,fields):
    with tracker.connection() as con, con:
        con.execute('INSERT INTO workspace_runs VALUES(?,?,?,?)',
                    (run_id,stamp(),'daily',json.dumps(fields)))
    if any(key.startswith('Firecrawl ') for key in fields):
        from firecrawl_discovery import queue_report
        queue_report(fields)
    return None,1


def backup_workspace():
    tracker = SQLiteTracker()
    folder = ROOT/'reports/sqlite-backups'
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/(datetime.now().strftime('%Y%m%dT%H%M%S%f')+'.sqlite3')
    with tracker.connection() as source, sqlite3.connect(path) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('SQLite backup integrity check failed')
    return {'backend':'sqlite','backup':str(path),'integrity':'ok','google_sheets_accessed':False}
