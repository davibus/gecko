"""Show verified search activity in the existing Daily Run status area."""
import argparse
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'job-scout'))
from google_tracker import GoogleTracker, Config, load_environment

LIVE = ROOT / 'reports/discovery/live-status.json'
LABELS = ['Search status', 'New jobs added', 'Current activity', 'Last progress', 'Last checked']
ZONE = ZoneInfo('America/Denver')


def process_state(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_ulonglong)] * 4
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False, None
    try:
        code = ctypes.c_ulong()
        created, ended, system, user = [ctypes.c_ulonglong() for _ in range(4)]
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False, None
        kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in (created, ended, system, user)))
        return code.value == 259, created.value
    finally:
        kernel.CloseHandle(handle)


def activity(pid):
    command = ("Get-CimInstance Win32_Process -Filter 'ParentProcessId=" + str(pid)
               + "' | Select-Object -ExpandProperty Name")
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
                            capture_output=True, text=True, timeout=15,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if 'codex' in result.stdout.lower():
        return 'Reviewing job details and matching evidence'
    return 'Collecting postings and checking job links'


def display_time(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).astimezone(ZONE).strftime('%m-%d | %I:%M:%S %p %Z')


def prepare_panel(remote):
    meta = remote.api.get(spreadsheetId=remote.config.spreadsheet_id,
        ranges=["'Daily Run'!H1:L2"], includeGridData=True,
        fields='sheets(properties(sheetId,title,gridProperties),data(rowData(values(userEnteredValue,dataValidation))),protectedRanges(range))').execute()
    sheet = next(s for s in meta['sheets'] if s['properties']['title'] == 'Daily Run')
    rows = [r for data in sheet.get('data', []) for r in data.get('rowData', [])]
    values = [[v.get('userEnteredValue', {}).get('stringValue', '') for v in r.get('values', [])] for r in rows]
    populated = any(v.get('userEnteredValue') or v.get('dataValidation') for r in rows for v in r.get('values', []))
    if populated and (not values or values[0] != LABELS):
        raise RuntimeError('Daily Run H1:L2 contains unrelated content; status panel was not written')
    if sheet.get('protectedRanges'):
        raise RuntimeError('Daily Run has protected ranges; status panel requires review')
    ident = sheet['properties']['sheetId']
    area = {'sheetId': ident, 'startRowIndex': 0, 'endRowIndex': 2, 'startColumnIndex': 7, 'endColumnIndex': 12}
    requests = [{'repeatCell': {'range': area,
        'cell': {'userEnteredFormat': {'wrapStrategy': 'WRAP', 'verticalAlignment': 'MIDDLE',
                                     'textFormat': {'fontSize': 10}}},
        'fields': 'userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment,userEnteredFormat.textFormat.fontSize'}},
        {'repeatCell': {'range': {**area, 'endRowIndex': 1},
         'cell': {'userEnteredFormat': {'backgroundColor': {'red': .9, 'green': .93, 'blue': .96},
                                      'textFormat': {'bold': True}}},
         'fields': 'userEnteredFormat.backgroundColor,userEnteredFormat.textFormat.bold'}},
        {'updateDimensionProperties': {'range': {'sheetId': ident, 'dimension': 'ROWS', 'startIndex': 0, 'endIndex': 2},
            'properties': {'pixelSize': 48}, 'fields': 'pixelSize'}}]
    for col, width in enumerate((180, 120, 320, 200, 200), 7):
        requests.append({'updateDimensionProperties': {'range': {'sheetId': ident, 'dimension': 'COLUMNS',
            'startIndex': col, 'endIndex': col + 1}, 'properties': {'pixelSize': width}, 'fields': 'pixelSize'}})
    frozen = sheet['properties']['gridProperties'].get('frozenRowCount', 0)
    if frozen < 1:
        requests.append({'updateSheetProperties': {'properties': {'sheetId': ident,
            'gridProperties': {'frozenRowCount': 1}}, 'fields': 'gridProperties.frozenRowCount'}})
    remote.api.batchUpdate(spreadsheetId=remote.config.spreadsheet_id, body={'requests': requests}).execute()
    return ident


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--worker-pid', type=int, required=True)
    parser.add_argument('--interval', type=int, default=30)
    args = parser.parse_args()
    report_path = args.report.resolve()
    assert report_path.parent == (ROOT / 'reports/discovery/unified').resolve()
    assert args.interval >= 15
    report = json.loads(report_path.read_text(encoding='utf-8'))
    run_id = report['run_id']
    alive, original_created = process_state(args.worker_pid)
    assert alive, 'Search worker is no longer running'
    load_environment()
    remote = GoogleTracker(config=Config.from_environment())
    sheet_id = prepare_panel(remote)
    known_ids = None
    verified_ids = []
    started = report_path.stat().st_ctime
    while True:
        report = json.loads(report_path.read_text(encoding='utf-8'))
        alive, created = process_state(args.worker_pid)
        alive = alive and created == original_created
        ids = sorted(set(report.get('published_job_ids', [])))
        if ids != known_ids:
            rows = remote.scout().rows
            verified_ids = []
            for ident in ids:
                hits = [r for _, r in rows if str(r.get('Scout ID', r.get('ID', ''))) == str(ident)]
                if len(hits) == 1 and hits[0].get('Query Used to Find') and float(hits[0].get('Match Score') or 0) >= 60:
                    verified_ids.append(ident)
            known_ids = ids
        now = datetime.now(timezone.utc)
        progress = max([started, report_path.stat().st_mtime] +
            [p.stat().st_mtime for p in (ROOT / 'job-scout/data/resume-match').glob('*.json') if p.stat().st_mtime >= started])
        report_status = report.get('status')
        if not alive:
            complete = report_status == 'complete'
            state = 'FINISHED' if complete else 'STOPPED — needs attention'
            current = ('Search finished; ' + str(len(verified_ids)) + ' new jobs verified') if complete else 'Worker stopped before a completed report'
        elif report_status == 'complete':
            state, current = 'FINISHING', 'Completing tracker synchronization'
        elif now.timestamp() - progress > 480:
            state, current = 'WAITING — check needed', 'Worker is alive; no verified progress in over 8 minutes'
        else:
            state, current = 'RUNNING', activity(args.worker_pid)
        snapshot = {'run_id': run_id, 'status': state, 'worker_pid': args.worker_pid,
            'worker_alive': alive, 'published_jobs_verified': len(verified_ids), 'verified_job_ids': verified_ids,
            'target_jobs': 20, 'activity': current, 'last_progress_at': datetime.fromtimestamp(progress, timezone.utc).isoformat(),
            'checked_at': now.isoformat(), 'tracker_status_url': f'https://docs.google.com/spreadsheets/d/{remote.config.spreadsheet_id}/edit#gid={sheet_id}&range=H1:L2'}
        # A newer run may have taken ownership of the same panel.
        if LIVE.exists():
            old = json.loads(LIVE.read_text(encoding='utf-8'))
            if old.get('run_id') != run_id and old.get('worker_pid'):
                other_alive, _ = process_state(int(old['worker_pid']))
                if other_alive:
                    return
        cells = [LABELS, [state, f'{len(verified_ids)} / 20', current, display_time(progress), display_time(now.timestamp())]]
        remote.api.values().update(spreadsheetId=remote.config.spreadsheet_id,
            range="'Daily Run'!H1:L2", valueInputOption='RAW', body={'values': cells}).execute()
        readback = remote.api.values().get(spreadsheetId=remote.config.spreadsheet_id,
            range="'Daily Run'!H1:L2", valueRenderOption='UNFORMATTED_VALUE').execute().get('values', [])
        assert readback == cells, 'Live status panel readback failed'
        temporary = LIVE.with_suffix('.tmp')
        temporary.write_text(json.dumps(snapshot, indent=2), encoding='utf-8')
        temporary.replace(LIVE)
        print(json.dumps(snapshot), flush=True)
        if not alive:
            return
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
