"""One-time audited restoration of currently reachable jobs from an older database."""

import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "job-scout"))

from deduplicate import find_duplicate
from google_tracker import GoogleTracker
from link_validation import DailyLinkValidator
from scout import load_local_environment
from source_policy import is_jooble_candidate
from storage import DEFAULT_DB, JobStore


def main():
    source = ROOT / "job-scout/data/backups/jobs-before-fresh-discovery-20261011T090814.sqlite3"
    report_dir = Path(__file__).parent
    audit_path = report_dir / "backup-restoration-audit.json"
    backup_path = report_dir / "active-db-before-restoration.sqlite3"
    working_copy = report_dir / "historical-working-copy.sqlite3"
    load_local_environment()
    load_local_environment(ROOT / ".env.google-sheets.local")
    rejection_index = GoogleTracker().rejected_jobs_index()
    counts = Counter()
    decisions = {}
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as original:
        with sqlite3.connect(working_copy) as temporary:
            original.backup(temporary)
    with JobStore(working_copy) as old_store:
        jobs = old_store.all()
    counts["backup_total"] = len(jobs)
    candidates = []
    for job in jobs:
        reason = None
        if is_jooble_candidate(source=job.source, urls=(job.url, job.canonical_url, job.authoritative_url)):
            reason = "disabled_jooble"
        elif job.status not in {"new", "reviewing"}:
            reason = "protected_lifecycle"
        elif rejection_index.matches_job(job):
            reason = "rejected_history"
        elif not (job.url or job.canonical_url or job.authoritative_url):
            reason = "missing_url"
        if reason:
            counts[reason] += 1
            decisions[str(job.id)] = reason
        else:
            candidates.append(job)
    print(f"Checking {len(candidates)} historical posting URLs", flush=True)
    validator = DailyLinkValidator()
    results = validator.check_existing(candidates)
    valid = []
    for job, result in results:
        if result.status == "valid":
            valid.append(job)
        else:
            reason = "expired_or_dead" if result.status == "dead" else "unverified_url"
            counts[reason] += 1
            decisions[str(job.id)] = reason
    print(f"URL checks complete: {len(valid)} valid", flush=True)
    with JobStore(DEFAULT_DB) as current:
        existing = current.all()
        retained = []
        for job in sorted(valid, key=lambda item: item.id):
            if current.get(job.id) is not None or find_duplicate(job, existing + retained):
                counts["duplicate_or_existing"] += 1
                decisions[str(job.id)] = "duplicate_or_existing"
            else:
                retained.append(job)
        print(f"Unique valid restoration candidates: {len(retained)}", flush=True)
        with sqlite3.connect(backup_path) as backup:
            current.connection.backup(backup)
        for job in retained:
            current.save(job, job_id=job.id)
            counts["restored"] += 1
            decisions[str(job.id)] = "restored"
        counts["current_db_after"] = len(current.all())
    counts["excluded"] = counts["backup_total"] - counts["restored"]
    audit_path.write_text(json.dumps({
        "source": str(source), "active_db_backup": str(backup_path),
        "completed_at": datetime.now().isoformat(),
        "counts": dict(counts), "url_validation": validator.report(),
        "decisions": decisions,
    }, indent=2), encoding="utf-8")
    print(json.dumps({"counts": dict(counts), "audit": str(audit_path)}, indent=2))


if __name__ == "__main__":
    main()
