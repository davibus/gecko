"""Manual unified discovery, using Gecko providers, Firecrawl and existing writers."""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

from google_tracker import GoogleTracker, Config
from description_retrieval import description_is_sufficient
from firecrawl_state import config, DATABASE, History
from firecrawl_discovery import run_discovery, flush_pending, build_queries
from job_extraction import tracker_notes, sheet_description
from sources.http import safe_error

ROOT = Path(__file__).resolve().parents[1]
PENDING = ROOT / 'reports/discovery/unified-pending.json'
REPORTS = ROOT / 'reports/discovery/unified'
ZONE = ZoneInfo('America/Denver')


def _save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def _pending():
    return json.loads(PENDING.read_text(encoding='utf-8')) if PENDING.exists() else {'job_ids': [], 'reports': []}


def _sheet_report_fields(fields):
    """Keep oversized diagnostics in the full audit and bound Sheet cells."""
    result = dict(fields)
    audit = REPORTS / (str(fields['Run ID']).replace(':', '-') + '.json')
    for name, value in fields.items():
        if not isinstance(value, str) or len(value) <= 45000:
            continue
        preview = value[:12000]
        while True:
            summary = json.dumps({'summary': preview, 'original_characters': len(value),
                                  'full_audit': str(audit), 'truncated_for_sheet': True})
            if len(summary) <= 45000:
                break
            preview = preview[:len(preview)//2]
        result[name] = summary
    return result


def plan(args, preferences):
    settings = config()
    print(json.dumps({'mode': 'unified-search-plan', 'internal_sources': 'all configured providers',
                     'roles': preferences['target_roles'], 'firecrawl_enabled': settings['enabled'] and settings['daily_enabled'],
                     'firecrawl_queries': build_queries(preferences), 'budget': settings,
                     'network_requests': 0, 'database_writes': 0, 'spreadsheet_writes': 0,
                     'resumes_generated': 0, 'applications_submitted': 0}, indent=2))
    return 0


def deliver(store, remote=None):
    """Publish durable pending IDs/reports without searches or enrichment."""
    from sheet_sync import ensure_frozen_headers
    from normalize import posting_identity, posting_aliases
    pending = _pending()
    remote = remote or GoogleTracker(config=Config.from_environment())
    ensure_frozen_headers(remote)
    # Retain the established Firecrawl outbox, including fee/review rows.
    flush_pending(remote=remote, store=store)
    jobs = [store.get(i) for i in pending['job_ids']]
    if any(job is None for job in jobs):
        raise RuntimeError('Pending discovery job is missing; publication stopped')
    notes = {}
    for job in jobs:
        job.description = max((job.description or '', job.enriched_description or ''), key=len)
        notes[job.id] = tracker_notes(job.details)
        if not sheet_description(job.description):
            notes[job.id] += '\nFull description retained in Gecko storage, job ID ' + str(job.id)
    result = remote.upsert_scout(jobs, discovery_notes=notes, fill_blanks_only=True)
    if result.get('skipped') or not result.get('readback_verified'):
        raise RuntimeError('Discovery publication needs review; pending IDs retained')
    rows = remote.scout().rows
    match_exclusions = {entry['job_id']: entry for entry in result.get('match_excluded', [])}
    for job in jobs:
        if job.id in match_exclusions:
            continue
        from url_resolution import best_job_url
        expected_url = best_job_url(job)
        matches = [v for _,v in rows if str(v.get('ID', v.get('Scout ID', ''))) == str(job.id)]
        aliases = posting_aliases(job) | {posting_identity(expected_url)}
        if len(matches) != 1 or posting_identity(matches[0].get('Job URL', '')) not in aliases:
            raise RuntimeError('Discovery identity readback failed; pending IDs retained')
    pending['job_ids'] = [key for key, value in match_exclusions.items() if value['status'] == 'pending']
    _save(PENDING, pending)
    sys.path.append(str(ROOT / 'scripts'))
    from daily_run_history import write_history
    for fields in list(pending['reports']):
        write_history(remote, _sheet_report_fields(fields))  # Existing Run ID check makes retries idempotent.
        pending['reports'].remove(fields)
        _save(PENDING, pending)
    ensure_frozen_headers(remote)
    return result


def run(args, store, preferences):
    import scout
    import sheet_sync
    sys.path.append(str(ROOT / 'scripts'))
    from run_gecko import run_lock
    with run_lock():
        if args.sync_only:
            result = deliver(store)
            sheet_sync.sync()
            print(json.dumps({'mode': 'sync-only', 'publication': result, 'discovery_requests': 0}))
            return 0
        started = datetime.now(ZONE)
        report = {'run_id': 'search:' + started.strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8],
                  'day': started.date().isoformat(), 'warnings': [], 'resumes_generated': 0, 'applications_submitted': 0}
        preexisting_ids = {job.id for job in store.all()}
        # Adopt the primary tracker before deduplication; conflicts must stop.
        try:
            sheet_sync.sync()
        except (OSError, RuntimeError) as exc:
            report['warnings'].append('Initial tracker sync unavailable: ' + safe_error(exc))
        ordinary = argparse.Namespace(**vars(args))
        ordinary.unified = False; ordinary.source = 'all'; ordinary.defer_tracker_sync = True
        ordinary.safe_discovery = True
        ordinary.adopt_primary_ids = True
        internal_code = scout.search(ordinary, store, preferences)
        report['gecko'] = ordinary.run_result
        ids = list(dict.fromkeys(ordinary.run_result['new_job_ids'] + ordinary.run_result['existing_job_ids']))
        # Existing enrichment only for incomplete job content; publication never
        # replaces a manual Sheet description with this cached source evidence.
        from service import _capture_full_description
        for job_id in ids:
            job = store.get(job_id)
            if not description_is_sufficient(max((job.description, job.enriched_description), key=len)):
                try:
                    _capture_full_description(job, store)
                except Exception as exc:
                    report['warnings'].append('Enrichment pending for ' + str(job_id) + ': ' + safe_error(exc))
        report['firecrawl'] = {'status': 'disabled', 'new_job_ids': [], 'provider_confirmed_credits': 0,
                               'estimated_or_reserved_credits': 0, 'total_credits_accounted': 0}
        try:
            settings = config()
            if settings['enabled'] and settings['daily_enabled']:
                try:
                    remote = GoogleTracker(config=Config.from_environment()); remote.scout()
                except Exception:
                    remote = None
                report['firecrawl'] = run_discovery(store, preferences, tracker=remote, publish=False)
                ids += report['firecrawl'].get('new_job_ids', [])
        except Exception as exc:
            # Firecrawl access/billing/availability cannot cancel internal jobs.
            report['firecrawl'] = {'status': 'unavailable', 'error': safe_error(exc), 'new_job_ids': []}
        try:
            if DATABASE.exists():
                report['firecrawl'].update(History().usage(report['day']))
        except Exception as exc:
            report['warnings'].append('Firecrawl usage unavailable: ' + safe_error(exc))
        ids = list(dict.fromkeys(ids))
        new_ids = [i for i in dict.fromkeys(ordinary.run_result['new_job_ids'] + report['firecrawl'].get('new_job_ids', [])) if i not in preexisting_ids]
        report['new_job_ids'] = new_ids; report['new_unique_jobs'] = len(new_ids)
        report['status'] = 'complete' if internal_code == 0 or report['firecrawl'].get('new_job_ids') else 'failed'
        pending = _pending()
        pending['job_ids'] = list(dict.fromkeys(pending['job_ids'] + ids))
        fields = {'Run ID': report['run_id'], 'Run Date': report['day'], 'Mode': 'Manual unified job search',
                  'Overall Status': report['status'], 'New Unique Jobs': len(new_ids),
                  'Gecko Discovery': {key: ordinary.run_result.get(key) for key in ('sources_searched', 'fetched', 'duplicates', 'newly_discovered', 'already_existed', 'source_health', 'source_errors')},
                  'Firecrawl Discovery': report['firecrawl'],
                  'Applications Submitted': 0, 'Resumes Generated': 0,
                  'Jobs by Source': dict(Counter(store.get(i).source for i in new_ids)),
                  **{'Firecrawl ' + key.replace('_', ' '): value for key,value in report['firecrawl'].items()}}
        fields = {key: json.dumps(value) if isinstance(value, (dict,list)) and key != 'Jobs by Source' else value
                  for key,value in fields.items()}
        pending['reports'].append(fields)
        _save(PENDING, pending)  # Saved before any writes; retries spend no credits.
        try:
            report['publication'] = deliver(store)
            sheet_sync.sync()
        except Exception as exc:
            report['publication'] = 'pending: ' + safe_error(exc)
        _save(REPORTS / (report['run_id'].replace(':', '-') + '.json'), report)
        print('Unified discovery report: ' + json.dumps(report))
        return 0 if report['status'] == 'complete' else 1
