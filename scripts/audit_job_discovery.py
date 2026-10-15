"""GET-only discovery evidence collection; never opens the writable JobStore."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'job-scout'))
import scout
from google_tracker import GoogleTracker
from sources.base import SearchRequest
from sources.config import load_source_config
from sources.acquisition import search_pages
from preferences import load_preferences

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

def safe_error(value):
    return re.sub(r'([?&](?:app_id|app_key|api_key|key|token)=)[^&\s]+',
                  r'\1[redacted]', str(value), flags=re.I)

def snapshot(tracker):
    tabs = tracker.discover_workbook()
    ranges = ["'" + name.replace("'", "''") + "'!A:AZ" for name in tabs]
    values = tracker.api.values().batchGet(spreadsheetId=tracker.config.spreadsheet_id,
        ranges=ranges, valueRenderOption='FORMULA').execute()
    ledger = tracker.scout()
    return {'tabs': tabs, 'values': values, 'ledger_rows': ledger.rows,
            'ledger_headers': ledger.headers, 'hash': digest(values)}

def collect(name, provider, prefs, out):
    result = {'source': name, 'configured': provider.configured(), 'queries': [],
              'errors': [], 'tracker_written': 0, 'raw': []}
    if not provider.configured():
        result['status'] = getattr(provider, 'reason', '') or 'missing credentials / no employers'
    else:
        try:
            if callable(getattr(type(provider), 'full_feed', None)):
                result['raw'] = [asdict(raw) for raw in provider.full_feed()]
                result['queries'].append({'kind': 'full feed', 'returned': len(result['raw'])})
            else:
                queries = prefs['target_roles']
                for query in queries:
                    for location in prefs['preferred_locations']:
                        entry = {'query': query, 'location': location, 'page': 1}
                        try:
                            rows = list(search_pages(provider, SearchRequest(query, location, 1, 50)))
                            entry['returned'] = len(rows)
                            result['raw'].extend(asdict(raw) for raw in rows)
                        except Exception as exc:
                            entry['error'] = safe_error(exc)
                            result['errors'].append(safe_error(exc))
                        result['queries'].append(entry)
                        # Authentication/payment failures are source-wide. Do not retry 32 times.
                        if entry.get('error') and any(t in entry['error'] for t in ['402', '401', '403', '429']):
                            break
                    if result['errors'] and any(t in result['errors'][-1] for t in ['402', '401', '403', '429']):
                        break
        except Exception as exc:
            result['errors'].append(safe_error(exc))
        result['status'] = 'error' if result['errors'] else ('success' if result['raw'] else 'zero results')
    result['board_errors'] = getattr(provider, 'board_errors', [])
    result['detail_errors'] = getattr(provider, 'errors', [])
    result['feed_results'] = getattr(provider, 'feed_results', [])
    if callable(getattr(provider, 'diagnostics', None)):
        result['diagnostics'] = provider.diagnostics()
    if name == 'remotive':
        result['rss_raw'] = provider.rss_raw_count
        result['rss_duplicates'] = provider.rss_duplicate_count
    # Source payload timestamps: observational windows, not server query equivalence.
    windows = Counter()
    now = datetime.now(timezone.utc)
    for raw in result['raw']:
        try:
            dt = datetime.fromisoformat(raw['date_posted'].replace('Z', '+00:00'))
            dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
            for days in [1, 7, 30]:
                if now-timedelta(days=days) <= dt <= now:
                    windows[str(days)] += 1
        except (ValueError, TypeError):
            windows['unknown_date'] += 1
    result['observed_date_windows'] = dict(windows)
    (out / f'{name}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return {k:v for k,v in result.items() if k not in ['raw','queries']}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    scout.load_local_environment()
    tracker = GoogleTracker()
    before = snapshot(tracker)
    (out/'live-before.json').write_text(json.dumps(before, indent=2, default=str), encoding='utf-8')
    config = load_source_config(); prefs = load_preferences()
    (out/'configuration.json').write_text(json.dumps({'sources':config,'preferences':prefs}, indent=2), encoding='utf-8')
    # Explicit SQLite URI read-only connection; no migrations, cache updates, or sequence writes.
    db = ROOT/'job-scout/data/jobs.sqlite3'
    with sqlite3.connect(db.as_uri()+'?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        data = {table:[dict(row) for row in conn.execute('SELECT * FROM '+table)]
                for table in ['jobs','source_links','scout_state']}
    (out/'database.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    print('Live snapshot:', len(before['ledger_rows']), 'rows', flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(collect,n,p,prefs,out):n for n,p in scout.providers().items()}
        for f in as_completed(futures):
            r=f.result(); print(r['source'],r['status'], 'errors',len(r['errors']),flush=True)
    after=snapshot(tracker)
    (out/'live-after.json').write_text(json.dumps(after, indent=2, default=str), encoding='utf-8')
    unchanged=before['hash']==after['hash']
    (out/'safety.json').write_text(json.dumps({'workbook_values_formulas_unchanged':unchanged,
        'before_hash':before['hash'],'after_hash':after['hash'],'tracker_writes':0,
        'resumes_created':0,'applications_submitted':0},indent=2))
    if not unchanged:
        raise RuntimeError('Workbook changed externally during audit; inspect snapshots')

if __name__ == '__main__':
    main()
