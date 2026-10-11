"""Read-only daily tracker inventory and proposed resume work.

Discovery is deliberately separate: a snapshot cannot claim that a new job was
found or added by a run that never executed discovery.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

from normalize import canonicalize_url
from sources.indeed import extract_indeed_job_key
from tracker_schema import (
    DELETED_JOBS_TAB, INDEED_APPLICATION_HEADER,
    COST_EXCLUSION_MARKER, REJECT_STATUSES, INDEED_EXPIRED_TEXTS,
    CURRENT_SCOUT_HEADERS,
)


def _value(row: dict[str, Any], name: str) -> str:
    return str(row.get(name) or "").strip()


def _key(value: Any) -> str:
    return str(value or "").strip().casefold()


def build_snapshot(rows: list[tuple[int, dict[str, Any]]], *, deleted_count: int = 0,
                   report_tab_empty: bool = True) -> dict[str, Any]:
    """Count observed ledger state; proposed actions never enter completed counts."""
    sources: Counter[str] = Counter()
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    duplicates = eligible = missing_links = blank_indeed = indeed_count = 0
    warnings: list[str] = []
    for number, row in rows:
        source = (_value(row, "Source") or "(blank)").casefold()
        sources[source] += 1
        is_indeed = _key(source) == "indeed"
        if is_indeed:
            indeed_count += 1
            if not _value(row, INDEED_APPLICATION_HEADER):
                blank_indeed += 1
        url = _value(row, "Job URL")
        stable_id = _value(row, "Scout ID") or _value(row, "ID")
        if is_indeed:
            stable_id = extract_indeed_job_key(url) or stable_id
        identity = f"{_key(source)}:{stable_id}" if stable_id else ""
        normalized_url = canonicalize_url(url) if url else ""
        if (identity and identity in seen_ids) or (normalized_url and normalized_url in seen_urls):
            duplicates += 1
        if identity:
            seen_ids.add(identity)
        if normalized_url:
            seen_urls.add(normalized_url)
        marker = _key(row.get("Resume Created"))
        link = _value(row, "Resume Link")
        if marker == "x" and not link:
            missing_links += 1
        if link and not marker:
            warnings.append(f"Row {number}: Resume Link exists without Resume Created; manual review")
        if marker or link or _key(row.get("Cost")) == COST_EXCLUSION_MARKER:
            continue
        if _key(row.get("Gecko Status") or row.get("Status")) in REJECT_STATUSES | {"ignored", "expired"}:
            continue
        if is_indeed and _key(row.get(INDEED_APPLICATION_HEADER)) in INDEED_EXPIRED_TEXTS:
            continue
        if _key(row.get("Apply?")) == "yes" and _value(row, "Company") and _value(row, "Job Title"):
            eligible += 1
    if report_tab_empty:
        warnings.append("Legacy console report does not write a persistent daily summary")
    warnings.append("Discovery and Indeed page verification were not run; run-level counts are unavailable")
    total = len(rows)
    return {
        "kind": "read-only tracker snapshot",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "observed": {
            "job_scout_jobs_found_in_ledger": total - indeed_count,
            "indeed_jobs_found_in_ledger": indeed_count,
            "existing_duplicate_rows": duplicates,
            "jobs_by_source": dict(sorted(sources.items())),
            "total_jobs_before": total,
            "total_jobs_after": total,
            "deleted_jobs_tab_rows": deleted_count,
            "indeed_rows_evaluated_for_blank_status": indeed_count,
            "blank_indeed_statuses_before": blank_indeed,
            "blank_indeed_statuses_after": blank_indeed,
            "eligible_jobs": eligible,
            "missing_resume_links": missing_links,
        },
        "proposed": {"resume_generations": eligible, "new_jobs_added": None,
                     "jobs_moved_to_deleted_jobs": None},
        "completed_by_this_command": {
            "new_jobs_added": 0, "jobs_moved_to_deleted_jobs": 0,
            "resume_generations": 0, "failures": 0,
        },
        "validation_warnings": warnings,
    }


def read_live_snapshot(tracker) -> dict[str, Any]:
    properties = tracker._sheet_properties()
    titles = {item.get("title") for item in properties}
    required = {tracker.config.scout_tab, DELETED_JOBS_TAB}
    missing = sorted(required - titles)
    if missing:
        raise RuntimeError("Live tracker is missing tabs: " + ", ".join(missing))
    scout = tracker.scout()
    def tab_rows(title: str) -> list[list[Any]]:
        from google_tracker import _a1, _col
        prop = next(item for item in properties if item.get("title") == title)
        width = prop.get("gridProperties", {}).get("columnCount", 26)
        return tracker.api.values().get(
            spreadsheetId=tracker.config.spreadsheet_id,
            range=_a1(title, f"A1:{_col(width)}"),
            valueRenderOption="UNFORMATTED_VALUE",
        ).execute().get("values", [])
    deleted = tab_rows(DELETED_JOBS_TAB)
    deleted_count = sum(any(value not in (None, "") for value in row) for row in deleted[1:])
    report = build_snapshot(scout.rows, deleted_count=deleted_count,
                            report_tab_empty=True)
    if tuple(scout.header_values[:len(CURRENT_SCOUT_HEADERS)]) != CURRENT_SCOUT_HEADERS:
        report["validation_warnings"].append(
            "Job Scout header order differs from the verified snapshot; fields were resolved by name"
        )
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from generate_apply_queue import read_queue
    queue = read_queue(tracker, auto_approve_geographic=True)
    report["observed"]["eligible_jobs"] = len(queue.pending)
    report["proposed"]["resume_generations"] = len(queue.pending)
    report["observed"]["missing_resume_links"] = sum(
        _key((item.fields or {}).get("Resume Created")) == "x"
        and not _value(item.fields or {}, "Resume Link")
        for item in queue.already_created
    )
    report["validation_warnings"].append(
        "Eligible count uses the read-only Gecko queue; listing retrieval and Word validation have not run"
    )
    return report
