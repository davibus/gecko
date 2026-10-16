"""Export the final SQLite tracker to Google Sheets and retain verified evidence."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'job-scout')]
from sqlite_tracker import SQLiteTracker, stamp
from dashboard.grid import export_sheet
from tracker_backend import sqlite_enabled


def main():
    if not sqlite_enabled():
        print('Google Sheets is already the active tracker; SQLite export skipped.')
        return 0
    os.environ['GECKO_GOOGLE_AUTH_SERVER_CLOCK'] = '1'
    folder = ROOT/'reports/sheets-exports'
    folder.mkdir(parents=True,exist_ok=True)
    result = {'started_at':stamp(),'status':'running'}
    try:
        result.update(export_sheet(SQLiteTracker()), status='verified', finished_at=stamp())
        print(json.dumps(result),flush=True)
        return 0
    except Exception as exc:
        result.update(status='failed',finished_at=stamp(),error=str(exc))
        print('Google Sheets export failed; SQLite data is retained. '+str(exc),file=sys.stderr)
        return 1
    finally:
        target = folder/'latest.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(result,indent=2),encoding='utf-8')
        temporary.replace(target)


if __name__ == '__main__':
    raise SystemExit(main())
