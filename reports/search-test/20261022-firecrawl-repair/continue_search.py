"""Continue today's saved Firecrawl groups with the existing shared 200 cap."""
import sys, json
from pathlib import Path
from datetime import datetime, timezone
ROOT = Path('C:/gecko_main')
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT/'job-scout'), str(ROOT/'scripts')]
sys.stdout.reconfigure(encoding='utf-8'); sys.stderr.reconfigure(encoding='utf-8')
import scout, sheet_sync, unified_search
from run_gecko import run_lock
from sqlite_daily_report import backup_workspace
from storage import JobStore, DEFAULT_DB
from preferences import load_preferences
from google_tracker import GoogleTracker, Config
from firecrawl_state import History, config
from sources.firecrawl import FirecrawlClient
from firecrawl_discovery import run_discovery
from normalize import posting_identity
from url_resolution import best_job_url
from description_columns import description_column
from description_retrieval import description_is_sufficient
from hard_filters import deterministic_filter

scout.load_local_environment(); scout.load_local_environment(ROOT/'.env.google-sheets.local')
settings = config()
assert settings['enabled'] and settings['daily_enabled'] and settings['daily_hard_credits'] == 200
history = History(settings=settings)
report = {'started_at': datetime.now(timezone.utc).isoformat(), 'usage_before': history.usage(),
          'resumes_generated': 0, 'applications_submitted': 0}
HERE.mkdir(parents=True, exist_ok=True)
with run_lock():
    report['initial_sync'] = sheet_sync.sync()
    report['backup_before'] = backup_workspace()
    remote = GoogleTracker(config=Config.from_environment())
    with JobStore(DEFAULT_DB) as store:
        existing_ids = {j.id for j in store.all()}
        print(json.dumps({'event': 'resuming', 'usage': history.usage()}), flush=True)
        report['firecrawl'] = run_discovery(store, load_preferences(), history=history,
            client=FirecrawlClient(history=history, settings=settings), tracker=remote, publish=False)
        (HERE/'search-result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'event': 'search_finished', 'firecrawl': report['firecrawl']}), flush=True)
        pending = unified_search._pending()
        pending['job_ids'] = list(dict.fromkeys(pending['job_ids'] + report['firecrawl'].get('new_job_ids', [])))
        unified_search._save(unified_search.PENDING, pending)
        report['publication'] = unified_search.deliver(store, remote=remote)
        report['sync'] = sheet_sync.sync()
        table = remote.scout()
        rows = {str(v.get('Scout ID')): v for _, v in table.rows}
        report['verified_jobs'] = []
        for job_id in report['firecrawl'].get('new_job_ids', []):
            job = store.get(job_id); row = rows[str(job_id)]
            column = description_column(table.headers, 'Firecrawl')
            assert row['Company'] == job.company
            assert posting_identity(row['Job URL']) == posting_identity(best_job_url(job))
            assert description_is_sufficient(row.get(column, ''))
            assert deterministic_filter(job, load_preferences())[0]
            report['verified_jobs'].append({'id':job_id, 'company':job.company, 'title':job.title,
                'new_this_continuation':job_id not in existing_ids, 'description_characters':len(row[column]), 'url':row['Job URL']})
        report['usage_after'] = history.usage()
        assert report['usage_after']['total_credits_accounted'] <= 200
        report['backup_after'] = backup_workspace()
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        report['status'] = 'verified'
        (HERE/'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'event':'verified', 'jobs':report['verified_jobs'], 'usage':report['usage_after']}), flush=True)
