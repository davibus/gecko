"""Safe plan/status and explicit smart-discovery entrypoint; never submits applications."""
import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'job-scout'))
from firecrawl_state import config, utcnow, DATABASE, History
from firecrawl_discovery import build_queries, run_discovery, flush_pending
from google_tracker import load_environment
from preferences import load_preferences


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true', help='Local plan only: no API, database writes or spreadsheet writes')
    mode.add_argument('--apply', action='store_true', help='Explicit run; both paid and daily feature flags must already be enabled')
    mode.add_argument('--sync-only', action='store_true', help='Publish pending jobs/reports without Firecrawl requests')
    parser.add_argument('--broad-discovery', action='store_true', help='Explicitly authorize this broad Firecrawl search mode')
    args = parser.parse_args(argv)
    if args.apply and not args.broad_discovery:
        parser.error('--apply requires --broad-discovery; use Gecko job search for incremental discovery')
    load_environment()
    settings = config()
    if not args.apply and not args.sync_only:
        now = utcnow()
        print(json.dumps({'mode': 'dry-run', 'enabled': settings['enabled'], 'daily_enabled': settings['daily_enabled'],
                          'cutoff': (now - timedelta(hours=96)).isoformat(), 'budget': settings,
                          'history_exists': DATABASE.exists(), 'queries': build_queries(load_preferences()),
                          'network_requests': 0, 'database_writes': 0, 'spreadsheet_writes': 0}, indent=2))
        return 0
    from run_gecko import run_lock
    with run_lock():
        if args.sync_only:
            import sheet_sync
            print(json.dumps(sheet_sync.sync(), indent=2))
            return 0
        if not settings['enabled'] or not settings['daily_enabled']:
            parser.error('Paid and daily Firecrawl discovery are disabled; enabling requires approval')
        from storage import JobStore
        with JobStore() as store:
            result = run_discovery(store, load_preferences())
        print('Firecrawl efficiency: ' + json.dumps(result))
        # Use the existing Daily Run block schema and idempotent delivery outbox.
        from gecko_daily import counts_from_output, history_fields
        from firecrawl_discovery import queue_report
        fields = history_fields('firecrawl:' + result['day'], result['day'],
                                counts_from_output('Firecrawl efficiency: ' + json.dumps(result)),
                                result['sources'], dry_run=False, exit_code=0)
        queue_report(fields)
        try:
            flush_pending()
        except Exception as exc:
            print('Daily Run publication pending: ' + type(exc).__name__)
        return 0 if result['status'] in {'complete', 'already_complete'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
