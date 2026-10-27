"""One bounded live incremental search; preserve before/after tracker evidence."""
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'job-scout'))
sys.path.append(str(ROOT/'scripts'))
import scout
from google_tracker import GoogleTracker, Config
from firecrawl_state import History, config
from run_gecko import run_lock

def main():
    scout.load_local_environment()
    scout.load_local_environment(ROOT/'.env.google-sheets.local')
    if config().get('usage_unlimited'):
        raise RuntimeError('Unlimited environment override is active; controlled run requires normal configured limits')
    folder = ROOT/'reports/discovery/incremental-live'/datetime.now(ZoneInfo('America/Denver')).strftime('%Y%m%dT%H%M%S')
    folder.mkdir(parents=True, exist_ok=True)
    def save(name, value):
        (folder/name).write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')
    def snapshot(remote):
        tab = remote.scout(value_render_option='FORMULA')
        rows = {str(v.get('Scout ID',v.get('ID'))):dict(zip(tab.header_values, tab.raw_rows[n]))
                for n,v in tab.rows if str(v.get('Scout ID',v.get('ID')) or '').isdigit()}
        return {'headers':tab.header_values, 'rows':rows, 'properties':remote._sheet_properties()}
    with run_lock():
        remote = GoogleTracker(config=Config.from_environment())
        history = History()
        before = snapshot(remote)
        save('tracker-before.json', before)
        save('ledger-before.json', history.usage())
        # Read-only provider balance; never buy/upgrade or infer per-request bills.
        from sources.firecrawl import FirecrawlClient
        try:
            FirecrawlClient(history=history).reconcile_balance()
            save('balance-check.json', {'status':'provider balance observed', 'ledger':history.usage()})
        except Exception as exc:
            save('balance-check.json', {'status':'unavailable', 'error':str(exc)})
        from incremental_discovery import run
        args = scout.build_parser().parse_args(['search','--max-new-candidates','3'])
        args.daily_mode=True  # This harness already holds the canonical outer lock.
        from storage import JobStore
        from preferences import load_preferences
        with JobStore() as store:
            code = run(args, store, load_preferences())
        after = snapshot(remote)
        save('tracker-after.json', after)
        save('ledger-after.json', history.usage())
        changed = [key for key,value in before['rows'].items() if after['rows'].get(key) != value]
        new = {key:value for key,value in after['rows'].items() if key not in before['rows']}
        verified = [str(i) for i in args.run_result['published_job_ids']]
        from sheet_sync import ensure_frozen_headers
        ensure_frozen_headers(remote)
        result = {'search_exit_code':code, 'run':args.run_result,
                  'existing_rows_changed':changed, 'headers_preserved':before['headers']==after['headers'],
                  'new_tracker_jobs':new, 'verified_new_ids_match':set(new)==set(verified),
                  'evidence_folder':str(folder), 'checked_at':datetime.now(timezone.utc).isoformat()}
        save('verification.json', result)
        print('LIVE VERIFICATION: '+json.dumps(result), flush=True)
        if changed or not result['headers_preserved'] or not result['verified_new_ids_match']:
            raise RuntimeError('Tracker verification needs review; evidence preserved')
        return code

if __name__ == '__main__':
    raise SystemExit(main())
