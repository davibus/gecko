"""Read live Gecko state and update Daily Tasks and Daily Run reports.

No discovery, job mutation, resume generation, or Gmail operation is invoked.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import unquote, urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import GoogleTracker, _a1, _col, resume_approval_value, is_expired_indeed  # noqa: E402
from rejected_jobs import RejectedJob, RejectedJobsIndex, normalize_job_url  # noqa: E402
from tracker_schema import (DAILY_TASKS_TAB, DELETED_JOBS_TAB, REJECTED_TAB,
                            DAILY_RUN_TAB, INDEED_APPLICATION_HEADER, REJECT_STATUSES,
                            resolve_headers)  # noqa: E402
from daily_tasks_dashboard import (FIELDS as DASHBOARD_FIELDS, MAX_DATES,
                                   _parse as parse_dashboard, cell as dashboard_cell,
                                   write as write_dashboard)  # noqa: E402
from daily_run_history import preflight_history, write_history  # noqa: E402

ZONE = ZoneInfo("America/Denver")
UNAVAILABLE = "Unavailable"
HEADERS = (*DASHBOARD_FIELDS, "Jobs by Source")  # Metric keys, never Sheet columns.


def now() -> datetime:
    return datetime.now(ZONE)


def key(value) -> str:
    return str(value or "").strip().casefold()


def public_error(error: Exception) -> str:
    """Never put raw API exceptions, URLs, or credential material in reports."""
    name = type(error).__name__
    message = str(error).casefold()
    if any(word in message for word in ("401", "403", "invalid_grant", "credential", "auth")):
        return f"{name}: authentication or permission failure (details redacted)"
    if any(word in message for word in ("429", "quota", "rate limit")):
        return f"{name}: rate limit or quota failure (details redacted)"
    if isinstance(error, RuntimeError) and str(error).startswith((
            "Daily Tasks ", "Daily Run ", "Job-tracking data changed")):
        return f"{name}: {error}"
    return f"{name}: reporting operation failed (details redacted)"


def identity(row: dict) -> tuple[str, str] | None:
    source = key(row.get("Source"))
    url = str(row.get("Job URL") or "").strip()
    from rejected_jobs import normalize_job_id
    job_id = normalize_job_id(source, row.get("Job ID") or row.get("Scout ID") or row.get("ID"), url)
    if source and job_id:
        return (source, job_id)
    normal_url = normalize_job_url(url)
    return ("url", normal_url) if normal_url else None


def usable_url(value) -> bool:
    parsed = urlsplit(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def link_state(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "blank"
    parsed = urlsplit(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return "cloud_syntax_valid_access_unverified"
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        return "invalid"
    path_text = unquote(parsed.path)
    if re.fullmatch(r"/[A-Za-z]:/.*", path_text):
        path_text = path_text[1:]
    path = Path(path_text)
    if not path.is_absolute() or path.suffix.casefold() != ".docx":
        return "invalid"
    try:
        if not path.anchor or not Path(path.anchor).exists():
            return "local_unavailable"
        return "valid_local" if path.is_file() and path.stat().st_size > 0 else "missing_local_file"
    except (OSError, ValueError):
        return "local_unavailable"


def row_record(number: int, data: dict, reason: str, **extra) -> dict:
    return {"row": number, "job_id": str(data.get("Scout ID") or data.get("ID") or ""),
            "source": str(data.get("Source") or ""), "reason": reason, **extra}


def source_discoveries(events: list[dict], active: list[dict], rejected: RejectedJobsIndex) -> dict:
    """Pure discovery classifier for explicitly supplied, current run events only."""
    counts = Counter(key(event.get("Source")) for event in events)
    active_keys = {identity(row) for row in active}
    active_urls = {normalize_job_url(row.get("Job URL")) for row in active}
    seen = set()
    seen_urls = set()
    source_by_url = defaultdict(set)
    result = {"by_source": dict(counts), "total_found": len(events), "new_unique": 0,
              "existing": 0, "duplicate_discoveries": 0, "cross_source_duplicates": 0,
              "rejected": 0, "actions": []}
    for event in events:
        ident = identity(event)
        url = normalize_job_url(event.get("Job URL"))
        if url:
            source_by_url[url].add(key(event.get("Source")))
        if (ident and ident in seen) or (url and url in seen_urls):
            result["duplicate_discoveries"] += 1
            continue
        if ident:
            seen.add(ident)
        if url:
            seen_urls.add(url)
        if rejected.match(source=event.get("Source"), job_id=event.get("Job ID"),
                          url=event.get("Job URL")):
            result["rejected"] += 1
            result["actions"].append({"identity": ident, "action": "exclude", "reason": "permanent rejection"})
        elif ident in active_keys or (url and url in active_urls):
            result["existing"] += 1
        else:
            result["new_unique"] += 1
            result["actions"].append({"identity": ident, "action": "add", "reason": "new unique discovery"})
    result["cross_source_duplicates"] = sum(len(sources) > 1 for sources in source_by_url.values())
    return result


def snapshot(tracker: GoogleTracker) -> dict:
    """Read complete effective values in job tabs; no writer is reachable here."""
    properties = tracker._sheet_properties()
    titles = {item["title"] for item in properties}
    if tracker.config.scout_tab not in titles or REJECTED_TAB not in titles or DELETED_JOBS_TAB not in titles:
        raise RuntimeError(f"Required {tracker.config.scout_tab}, {REJECTED_TAB}, or {DELETED_JOBS_TAB} tab missing")
    tabs = {}
    for title in (tracker.config.scout_tab, REJECTED_TAB, DELETED_JOBS_TAB):
        if title == tracker.config.scout_tab:
            tab = tracker.scout()
            tabs[title] = {"rows": tab.rows, "headers": tab.headers, "sheet_id": tab.sheet_id}
        else:
            prop = next(item for item in properties if item["title"] == title)
            width = prop.get("gridProperties", {}).get("columnCount", 26)
            values = tracker.api.values().get(spreadsheetId=tracker.config.spreadsheet_id,
                range=_a1(title, f"A1:{_col(width)}"), valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
            if title == REJECTED_TAB and not values:
                raise RuntimeError("Rejected Jobs tab lacks its required header")
            headers = resolve_headers([str(x) for x in values[0]]) if values else {}
            rows = [(n, {h: row[c-1] if c <= len(row) else "" for h,c in headers.items()})
                    for n,row in enumerate(values[1:], 2) if any(x not in (None, "") for x in row)]
            tabs[title] = {"rows": rows, "headers": headers, "sheet_id": prop["sheetId"]}
    for title in titles:
        if title in tabs or title in {DAILY_TASKS_TAB, DAILY_RUN_TAB}:
            continue
        # Compare every other tab, including renamed or headerless user tabs.
        prop = next(item for item in properties if item["title"] == title)
        width = prop.get("gridProperties", {}).get("columnCount", 26)
        values = tracker.api.values().get(spreadsheetId=tracker.config.spreadsheet_id,
            range=_a1(title, f"A1:{_col(width)}"),
            valueRenderOption="FORMULA").execute().get("values", [])
        tabs[title] = {"rows": [(number, {"__raw__": row})
                                for number, row in enumerate(values[1:], 2)
                                if any(value not in (None, "") for value in row)],
                       "headers": {"__raw__": values[0] if values else []},
                       "sheet_id": prop["sheetId"]}
    return tabs


def fingerprint(tabs: dict) -> str:
    payload = {title: {"headers": item["headers"], "rows": item["rows"]}
               for title,item in sorted(tabs.items())}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def evaluate(tabs: dict, scout_title: str) -> dict:
    rows = tabs[scout_title]["rows"]
    rejected_rows = tabs[REJECTED_TAB]["rows"]
    rejected = RejectedJobsIndex(RejectedJob.from_mapping(data) for _,data in rejected_rows)
    deleted_rows = tabs[DELETED_JOBS_TAB]["rows"]
    deleted = RejectedJobsIndex(RejectedJob.from_mapping(data) for _,data in deleted_rows)
    resume_decisions, indeed_decisions = [], []
    source_counts = Counter()
    indeed_statuses = Counter()
    resume = Counter()
    app = Counter()
    blank_indeed = 0
    indeed_count = 0
    marked_reject = []
    for number, data in rows:
        source = key(data.get("Source"))
        source_counts[source or "(blank)"] += 1
        is_indeed = source == "indeed"
        if is_indeed:
            indeed_count += 1
            status = str(data.get(INDEED_APPLICATION_HEADER) or "").strip()
            indeed_statuses[status or "(blank)"] += 1
            blank_indeed += not bool(status)
            if is_expired_indeed(status):
                if status != "Expired":
                    indeed_decisions.append(row_record(number, data, "canonical expiry normalization",
                        field=INDEED_APPLICATION_HEADER, old=status, new="Expired"))
                if key(data.get("Apply?")) != "no":
                    indeed_decisions.append(row_record(number, data, "expired Indeed overrides approval",
                        field="Apply?", old=data.get("Apply?"), new="No"))
        state = link_state(data.get("Resume Link"))
        resume[state] += 1
        x = key(data.get("Resume Created")) == "x"
        resume["marked_x"] += x
        resume["existing"] += x or key(data.get("Resume Created")) == "c" or state != "blank"
        resume["x_missing_or_invalid_link"] += x and state in {
            "blank", "invalid", "missing_local_file"}
        resume["manual_review"] += ((x and state in {"blank", "invalid", "missing_local_file"})
                                   or (not key(data.get("Resume Created")) and state != "blank"))
        applied = key(data.get("Applied")) == "x"
        app["already_applied"] += applied
        if key(data.get("Apply?")) in REJECT_STATUSES:
            marked_reject.append(row_record(number, data, "marked permanent rejection; move unsafe if formulas exist"))
            continue
        if rejected.match(source=data.get("Source"), url=data.get("Job URL")):
            app["excluded_rejected"] += 1
            continue
        if key(data.get("Cost")) == "x":
            app["excluded_cost"] += 1
            continue
        expired = is_indeed and is_expired_indeed(data.get(INDEED_APPLICATION_HEADER))
        if expired:
            app["excluded_expired"] += 1
            continue
        apply = key(data.get("Apply?")) == "yes" and resume_approval_value(
            data.get("Location"), data.get("Work Arrangement"), data.get("Cost")) == "Yes"
        if not apply:
            app["excluded_apply"] += 1
            continue
        app["qualified_active"] += 1
        if not data.get("Company") or not data.get("Job Title") or not data.get("Location") or not usable_url(data.get("Job URL")):
            app["missing_information"] += 1
        if applied:
            continue
        if x or key(data.get("Resume Created")) == "c" or state != "blank":
            resume["duplicate_prevented"] += x
            if (x and state in {"blank", "invalid", "missing_local_file"}) or (not x and state != "blank"):
                resume_decisions.append(row_record(number, data, "existing completion or link requires manual review",
                                                   marker=data.get("Resume Created"), link_state=state))
                app["waiting_review"] += 1
            elif state in {"valid_local", "cloud_syntax_valid_access_unverified"}:
                app["ready_to_apply"] += 1
            else:
                app["waiting_review"] += 1
            continue
        resume["needed"] += 1
        app["waiting_resume"] += 1
        resume_decisions.append(row_record(number, data, "eligible for canonical queue evaluation; no file created"))
    # No discovery was run, so additions, moves, and new identity projections are unknown.
    tab_counts = {}
    for title, tab in tabs.items():
        count = len(tab["rows"])
        tab_counts[title] = {"actual_before": count, "actual_after": None,
                             "projected_after": None, "would_add": None,
                             "would_update": None, "would_move": None,
                             "would_exclude": None, "unchanged": None}
    indeed_projected_blank = blank_indeed  # No visible-page observations were gathered.
    return {"tabs": tab_counts, "jobs_by_source_in_ledger": dict(sorted(source_counts.items())),
            "discovery": {name: None for name in ("job_scout_found", "indeed_found", "total_found",
                "new_unique_jobs", "existing_jobs", "duplicate_discoveries", "cross_source_duplicates",
                "qualified_jobs", "rejected_jobs", "rediscovered_deleted_jobs")},
            "resume": dict(resume), "application": {
                **dict(app), "started_incomplete": None, "awaiting_final_user_review": None,
                "new_employer_responses": None, "blocked_by_errors": None},
            "indeed": {"rows_evaluated": indeed_count, "blank_before": blank_indeed,
                       "blank_projected_after": indeed_projected_blank,
                       "projected_after": None,
                       "status_breakdown": dict(sorted(indeed_statuses.items())),
                       "expired_from_existing_text": sum(
                           count for status, count in indeed_statuses.items() if is_expired_indeed(status)),
                       "blank_actual_after": None, "projected_status_updates": len([x for x in indeed_decisions if x["field"] == INDEED_APPLICATION_HEADER]),
                       "verified_live_page_status_updates": None},
            "deleted": {"current": len(deleted_rows), "duplicate_entries": 0 if not deleted_rows else None,
                        "active_conflicts": 0 if not deleted_rows else None, "proposed_moves": marked_reject,
                        "rediscovered": None},
            "proposed_actions": {"additions": [], "updates": indeed_decisions,
                                 "moves": marked_reject, "resume_decisions": resume_decisions},
            "warnings": ["Discovery not run: no safe current-run event stream was inspected",
                         "Indeed pages not verified: status projections use only existing expiry text",
                         "Gmail response checker not run because it writes Response and state"],
            "errors": [], "rejected_index_count": len(rejected.records)}


def add_canonical_queue(report: dict, tracker: GoogleTracker) -> None:
    """Reuse the canonical read-only queue classifier, never its runner."""
    from generate_apply_queue import read_queue
    queue = read_queue(tracker, auto_approve_geographic=True)
    metrics = report["metrics"]
    resume = metrics["resume"]
    resume["needed"] = len(queue.pending)
    resume["duplicate_prevented"] = len(queue.already_created) + len(queue.duplicate_excluded)
    resume["canonical_blockers"] = {
        "cost_x": len(queue.cost_excluded), "rejected": len(queue.rejected_excluded),
        "missing_identity": len(queue.missing_identity),
        "duplicates": len(queue.duplicate_excluded),
        "not_approved": len(queue.not_approved),
    }
    metrics["proposed_actions"]["resume_decisions"] = [
        row_record(item.row, item.fields or {}, decision)
        for item, decision in queue.decisions
    ]
    metrics["application"]["waiting_resume"] = len(queue.pending)
    metrics["queue_validation"] = {"eligible": len(queue.pending),
        "classified": sum(len(getattr(queue, name)) for name in (
            "pending", "already_created", "not_approved", "jooble_excluded",
            "link_backfill", "duplicate_excluded", "missing_identity",
            "cost_excluded", "rejected_excluded"))}


def annotate_formula_protection(report: dict, tracker: GoogleTracker) -> None:
    """Report conditional proposals separately from formula-protected cells."""
    formula_tab = tracker.scout(value_render_option="FORMULA")
    anchors = [(row, col) for row, cells in (formula_tab.raw_rows or {}).items()
               for col, value in enumerate(cells, 1)
               if isinstance(value, str) and value.lstrip().startswith("=")
               and "ARRAYFORMULA" in value.upper()]
    skipped = []
    for action in report["metrics"]["proposed_actions"]["updates"]:
        row, field = action["row"], action["field"]
        col = formula_tab.headers.get(field)
        if col is None:
            raise RuntimeError(f"Missing required live header {field}")
        raw = (formula_tab.raw_rows or {}).get(row, ())
        protected = (col <= len(raw) and isinstance(raw[col-1], str)
                     and raw[col-1].lstrip().startswith("="))
        spill = any(row >= anchor_row and col >= anchor_col for anchor_row,anchor_col in anchors)
        action["formula_protected"] = bool(protected or spill)
        action["simulation_only"] = True
        if protected or spill:
            skipped.append({"row": row, "field": field,
                            "reason": "formula cell" if protected else "possible ARRAYFORMULA output"})
    report["metrics"]["formula_skips"] = skipped


@contextmanager
def report_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def report_values(tracker: GoogleTracker) -> list[list]:
    """Read the entire Daily Tasks tab, including formulas for protection."""
    prop = next((item for item in tracker._sheet_properties()
                 if item.get("title") == DAILY_TASKS_TAB), None)
    if prop is None:
        return []
    width = prop.get("gridProperties", {}).get("columnCount", 26)
    return tracker.api.values().get(spreadsheetId=tracker.config.spreadsheet_id,
        range=_a1(DAILY_TASKS_TAB, f"A1:{_col(width)}"),
        valueRenderOption="FORMULA").execute().get("values", [])


def unrelated_tasks(rows: list[list], managed_columns: set[int]) -> dict[tuple[int, int], object]:
    """Every nonempty cell outside the dashboard's A:F columns is user-owned."""
    return {(row_number, col): value
            for row_number, row in enumerate(rows, 1)
            for col, value in enumerate(row, 1)
            if value not in (None, "") and col not in managed_columns}


def dashboard_baseline(rows: list[list], pending_path: Path) -> dict:
    """Use the prior complete dashboard when a journaled write is incomplete."""
    try:
        return parse_dashboard(rows)[0]
    except RuntimeError:
        if not pending_path.is_file():
            raise
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        return parse_dashboard(pending["before"])[0]


def changed_dashboard_cells(before: list[list], after: list[list]) -> list[str]:
    return [f"{_col(column)}{row}"
            for row in range(1, max(len(before), len(after)) + 1)
            for column in range(1, 7)
            if dashboard_cell(before, row, column) != dashboard_cell(after, row, column)]


def write_report(tracker: GoogleTracker, fields: dict, *, pending_path: Path | None = None):
    return write_dashboard(tracker, fields, pending_path=pending_path)


def atomic_json(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(content, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def report_fields(report: dict, path: Path) -> dict:
    m = report["metrics"]
    d, i, r, a = m["discovery"], m["indeed"], m["resume"], m["application"]
    tabs = m["tabs"]
    scout = tabs[report["configuration"]["scout_tab"]]
    deleted = tabs[DELETED_JOBS_TAB]
    total_indeed = i["rows_evaluated"]
    pairs = {
        "Run Date": report["run_date"], "Run ID": report["run_id"],
        "Started At": report["started_at"], "Completed At": report["completed_at"],
        "Mode": "Daily Tasks Refresh" if report["mode"] == "daily-tasks refresh" else "Dry Run",
        "Overall Status": report["overall_status"],
        "Job Scout Found": d["job_scout_found"], "Indeed Found": d["indeed_found"],
        "Total Found": d["total_found"], "New Unique Jobs": d["new_unique_jobs"],
        "Existing Jobs": d["existing_jobs"], "Duplicate Discoveries": d["duplicate_discoveries"],
        "Cross-Source Duplicates": d["cross_source_duplicates"],
        "Qualified Jobs": d["qualified_jobs"], "Rejected Jobs": d["rejected_jobs"],
        "Jobs by Source": m["jobs_by_source_in_ledger"],
        "Rediscovered Deleted Jobs": d["rediscovered_deleted_jobs"],
        "Job Scout Actual Before": scout["actual_before"], "Job Scout Actual After": scout["actual_after"],
        "Job Scout Projected After": scout["projected_after"],
        "Indeed Actual Before": total_indeed, "Indeed Actual After": i["actual_after"],
        "Indeed Projected After": i["projected_after"],
        "Deleted Actual Before": deleted["actual_before"], "Deleted Actual After": deleted["actual_after"],
        "Deleted Projected After": deleted["projected_after"],
        "Projected Adds": None, "Projected Updates": None, "Projected Moves": None,
        "Indeed Rows Evaluated": total_indeed, "Indeed Blank Status Before": i["blank_before"],
        "Indeed Blank Status Projected After": i["blank_projected_after"],
        "Indeed Blank Status Actual After": i["blank_actual_after"],
        "Resumes Needed": m["resume"].get("needed", 0), "Existing Resumes": m["resume"].get("existing", 0),
        "Invalid Resume Links": m["resume"].get("invalid", 0) + m["resume"].get("missing_local_file", 0),
        "Resumes Reused": None, "Duplicate Resumes Prevented": m["resume"].get("duplicate_prevented", 0),
        "Jobs Ready to Apply": a.get("ready_to_apply", 0), "Jobs Already Applied": a.get("already_applied", 0),
        "Jobs Needing Review": m["resume"].get("manual_review", 0),
        "Errors": len(report["errors"]), "Warnings": len(report["warnings"]),
        "Execution Seconds": report["execution_seconds"], "Audit Log Location": path.resolve().as_uri(),
        "Report Details": "Read-only tracker snapshot; discovery, Indeed page checks, and projections unavailable.",
    }
    return {name: (UNAVAILABLE if value is None else value) for name,value in pairs.items()}


def run(tracker: GoogleTracker, run_id: str, run_date: str, audit_root: Path,
        *, refresh_today: bool = False) -> tuple[dict, int | None]:
    started = now()
    folder = audit_root / run_date
    json_path = folder / f"{run_id}.json"
    log_path = folder / f"{run_id}.log"
    report = {"run_id": run_id, "run_date": run_date, "started_at": started.isoformat(),
              "mode": "daily-tasks refresh" if refresh_today else "dry-run report",
              "configuration": {"scout_tab": tracker.config.scout_tab,
              "spreadsheet_id_tail": tracker.config.spreadsheet_id[-6:]},
              "metrics": {}, "script_health": {}, "warnings": [], "errors": [],
              "validation": {}, "sheet_updated": False}
    row_number = None
    events = []
    def event(label, **details):
        events.append({"run_id": run_id, "at": now().isoformat(), "event": label, **details})
    try:
        if refresh_today and run_date != now().date().isoformat():
            raise RuntimeError("Daily Tasks refresh date must be today in America/Denver")
        tasks_before = report_values(tracker)
        before = snapshot(tracker)
        before_hash = fingerprint(before)
        report["metrics"] = evaluate(before, tracker.config.scout_tab)
        add_canonical_queue(report, tracker)
        annotate_formula_protection(report, tracker)
        try:
            from sources.config import load_source_config
            config = load_source_config()
            report["configuration"]["enabled_sources"] = sorted(
                name for name, settings in config["providers"].items() if settings["enabled"])
        except (OSError, RuntimeError, ValueError) as config_error:
            report["warnings"].append("Source configuration unavailable: " + public_error(config_error))
        report["warnings"].extend(report["metrics"]["warnings"])
        event("snapshot", tab_counts={k: len(v["rows"]) for k,v in before.items()})
        report["script_health"] = {
            "Job Scout": {"status": "Not Run", "read_only_simulation": "tracker snapshot only"},
            "Indeed discovery": {"status": "Unavailable", "blocker": "authorized provider request not made"},
            "Indeed status evaluation": {"status": "Partial", "records_evaluated": report["metrics"]["indeed"]["rows_evaluated"],
                                         "blocker": "visible page controls not observed"},
            "Resume generation readiness": {"status": "Partial", "blocker": "listing retrieval and Word validation not run"},
            "Deleted Jobs processing": {"status": "Partial", "blocker": "move safety requires formula inspection"},
            "Gmail response tracking": {"status": "Not Run", "blocker": "canonical checker writes Response and local state"},
            "Google Sheets integration": {"status": "Success"},
            "Daily reporting": {"status": "Partial"},
        }
        for health in report["script_health"].values():
            health.setdefault("started_at", started.isoformat())
            health.setdefault("ended_at", now().isoformat())
            health.setdefault("execution_seconds", 0)
            health.setdefault("records_evaluated", 0)
            health.setdefault("records_skipped", 0)
            health.setdefault("error_count", 0)
            health.setdefault("warning_count", 0)
            health.setdefault("rate_limit_issue", False)
            health.setdefault("authentication_problem", False)
            health.setdefault("missing_configuration", False)
        after = snapshot(tracker)
        unchanged = fingerprint(after) == before_hash
        report["validation"] = {"job_data_unchanged": unchanged,
            "before_hash": before_hash, "after_hash": fingerprint(after)}
        for title, item in report["metrics"]["tabs"].items():
            item["actual_after"] = len(after[title]["rows"])
        report["metrics"]["indeed"]["actual_after"] = sum(
            key(data.get("Source")) == "indeed" for _,data in after[tracker.config.scout_tab]["rows"])
        report["metrics"]["indeed"]["blank_actual_after"] = sum(
            key(data.get("Source")) == "indeed" and not str(data.get(INDEED_APPLICATION_HEADER) or "").strip()
            for _,data in after[tracker.config.scout_tab]["rows"])
        if not unchanged:
            report["errors"].append("Job-tracking data changed during report; no report row was written")
            raise RuntimeError("Job-tracking data changed during report")
        event("safety_verified", unchanged=True)
        report["overall_status"] = "WARNING"  # Discovery and page checks are unavailable.
        report["completed_at"] = now().isoformat()
        report["execution_seconds"] = round((now() - started).total_seconds(), 3)
        atomic_json(json_path, report)
        pending_path = audit_root / ".dashboard-pending.json"
        with report_lock(audit_root / ".daily-report.lock"):
            # Recheck protected tabs immediately before the report writes.
            if fingerprint(snapshot(tracker)) != before_hash:
                raise RuntimeError("Job-tracking data changed before report write")
            if report_values(tracker) != tasks_before:
                raise RuntimeError("Daily Tasks changed before report write")
            fields = report_fields(report, json_path)
            baseline_entries = dashboard_baseline(tasks_before, pending_path) if refresh_today else None
            if refresh_today:
                if run_date not in baseline_entries and len(baseline_entries) >= MAX_DATES:
                    raise RuntimeError("Daily Tasks already has five historical dates; refresh would evict one")
            else:
                preflight_history(tracker, fields)
            row_number, retained_dates, managed_columns, changed_rows = write_report(
                tracker, fields, pending_path=pending_path)
            history_row, history_height = (None, 0) if refresh_today else write_history(tracker, fields)
        report["sheet_updated"] = bool(changed_rows or history_height)
        report["tab_results"] = {"Daily Tasks": {"state": "verified" if row_number else "not retained",
                            "row": row_number},
            "Daily Run": {"state": "untouched" if refresh_today else
                          "inserted" if history_height else "already present and verified",
                          "row": history_row}}
        if refresh_today:
            report["daily_run_untouched"] = True
            report["entry_action"] = "updated" if run_date in baseline_entries else "created"
        else:
            report["daily_run_row"] = history_row
            report["daily_run_rows_inserted"] = history_height
            event("daily_run_history_verified", row=history_row,
                  inserted_rows=history_height)
        report["report_row"] = row_number
        report["retained_dates"] = retained_dates
        report["updated_rows"] = sorted(changed_rows)
        report["sheet_skipped_due_retention"] = row_number is None
        if row_number is None:
            report["warnings"].append("Requested older date is outside the five most recent report dates; local audit retained")
            event("older_date_not_retained", retained_dates=retained_dates)
        else:
            event("report_row_verified", row=row_number, retained_dates=retained_dates,
                  updated_rows=sorted(changed_rows))
        tasks_after = report_values(tracker)
        report["changed_cells"] = changed_dashboard_cells(tasks_before, tasks_after)
        tasks_safe = unrelated_tasks(tasks_before, managed_columns) == unrelated_tasks(tasks_after, managed_columns)
        report["validation"]["daily_tasks_unrelated_unchanged"] = tasks_safe
        if not tasks_safe:
            raise RuntimeError("Unrelated Daily Tasks content changed during report")
        if refresh_today:
            after_entries, _ = parse_dashboard(tasks_after)
            history_before = {d: value for d, value in baseline_entries.items() if d != run_date}
            history_after = {d: value for d, value in after_entries.items() if d != run_date}
            if history_before != history_after:
                raise RuntimeError("Historical Daily Tasks dates changed during refresh")
            if row_number is None or after_entries.get(run_date, {}).get("Run ID") != run_id:
                raise RuntimeError("Today's Daily Tasks report failed final readback")
            report["validation"]["daily_tasks_today_verified"] = True
            report["validation"]["historical_dates_unchanged"] = True
            event("daily_tasks_refresh_verified", row=row_number,
                  action=report["entry_action"], changed_cells=report["changed_cells"])
        final_hash = fingerprint(snapshot(tracker))
        report["validation"]["after_report_hash"] = final_hash
        if final_hash != before_hash:
            report["validation"]["job_data_unchanged"] = False
            raise RuntimeError("Job-tracking data changed after report write")
    except Exception as error:
        report["overall_status"] = "FAIL"
        report["errors"].append(public_error(error))
        report["tab_results"] = {"Daily Tasks": {"state": "write failed" if row_number is None else "written; final run failed",
                            "reason": public_error(error) if row_number is None else None},
            "Daily Run": {"state": "untouched" if refresh_today else "not verified",
                          "reason": public_error(error) if not refresh_today else None}}
        report["script_health"].setdefault("Daily reporting", {})["status"] = "Failed"
        event("failure", error=public_error(error))
        if row_number is not None and report["metrics"] and not refresh_today:
            try:
                with report_lock(audit_root / ".daily-report.lock"):
                    write_report(tracker, report_fields(report, json_path),
                                 pending_path=audit_root / ".dashboard-pending.json")
                event("failed_status_row_verified", row=row_number)
            except Exception as followup_error:
                report["warnings"].append("Could not update report row to FAIL: " + public_error(followup_error))
    finally:
        report["completed_at"] = now().isoformat()
        report["execution_seconds"] = round((now() - started).total_seconds(), 3)
        atomic_json(json_path, report)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in events), encoding="utf-8")
    return report, row_number


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Accepted for clarity; always dry run")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--date", type=lambda text: datetime.strptime(text, "%Y-%m-%d").date().isoformat())
    parser.add_argument("--refresh-today", action="store_true",
                        help="Refresh only today's Daily Tasks block; leave Daily Run unchanged")
    parser.add_argument("--run-id")
    parser.add_argument("--reconcile-audit", metavar="RUN_ID",
                        help="Repair a failed audit with the same Run ID and validated source data")
    parser.add_argument("--restore-daily-tasks-audit", metavar="RUN_ID",
                        help="Restore missing Daily Tasks from a verified audit whose Daily Run exists")
    parser.add_argument("--restore-missing-daily-run", action="store_true",
                        help="With --reconcile-audit, recreate the verified-missing Daily Run tab")
    parser.add_argument("--restore-history-audit", metavar="PATH",
                        help="With --reconcile-audit, restore an earlier verified Daily Tasks date if empty")
    args = parser.parse_args(argv)
    from tracker_backend import sqlite_enabled
    if sqlite_enabled():
        if args.reconcile_audit or args.restore_daily_tasks_audit or args.restore_missing_daily_run:
            parser.error('Historical Sheets repairs are unavailable after the SQLite cutover')
        from sqlite_daily_report import report
        report()
        return 0
    if args.restore_daily_tasks_audit:
        if args.reconcile_audit or args.refresh_today or args.date or args.run_id or args.restore_missing_daily_run:
            parser.error("--restore-daily-tasks-audit cannot be combined with a new run or history write")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.restore_daily_tasks_audit):
            parser.error("invalid audit Run ID")
        from reconcile_daily_report import restore_tasks
        audit_root = ROOT / "reports" / "daily"
        matches = list(audit_root.glob(f"*/{args.restore_daily_tasks_audit}.json"))
        if len(matches) != 1:
            parser.error("audit Run ID was not found exactly once")
        result = restore_tasks(GoogleTracker(), matches[0],
            historical_audit=Path(args.restore_history_audit) if args.restore_history_audit else None,
            report_api=sys.modules[__name__])
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "VERIFIED" else 1
    if args.reconcile_audit:
        if args.refresh_today or args.date or args.run_id:
            parser.error("--reconcile-audit cannot be combined with a new run or date")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.reconcile_audit):
            parser.error("invalid audit Run ID")
        from reconcile_daily_report import reconcile
        audit_root = ROOT / "reports" / "daily"
        matches = list(audit_root.glob(f"*/{args.reconcile_audit}.json"))
        if len(matches) != 1:
            parser.error("failed audit Run ID was not found exactly once")
        result = reconcile(GoogleTracker(), matches[0],
            restore_missing_daily_run=args.restore_missing_daily_run,
            historical_audit=Path(args.restore_history_audit) if args.restore_history_audit else None,
            report_api=sys.modules[__name__])
        print(json.dumps(result, indent=2))
        return 0 if result["overall_status"] == "WARNING" else 1
    if args.restore_missing_daily_run or args.restore_history_audit:
        parser.error("restore options require --reconcile-audit")
    if args.refresh_today and args.date:
        parser.error("--refresh-today uses the current America/Denver date; omit --date")
    run_id = args.run_id or f"{now():%Y%m%dT%H%M%S}-{uuid4().hex[:10]}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
        parser.error("--run-id must be 1-80 letters, digits, hyphens, or underscores")
    date = args.date or now().date().isoformat()
    try:
        tracker = GoogleTracker()
        report, row = run(tracker, run_id, date, ROOT / "reports" / "daily",
                          refresh_today=args.refresh_today)
    except Exception as error:
        print(f"Daily report {run_id} failed: {public_error(error)}; Google Sheet not updated", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        tasks_status = (f"row {row}" if row else "not retained" if report.get("sheet_skipped_due_retention")
                        else "not written")
        if args.refresh_today:
            print(f"Daily Tasks refresh {run_id}: {report['overall_status']} | {tasks_status}"
                  f" | {report.get('entry_action', 'no entry changed')}")
        else:
            history_status = (f"row {report['daily_run_row']}" if report.get("daily_run_row")
                              else "already recorded" if report.get("daily_run_rows_inserted") == 0
                                   and "daily_run_rows_inserted" in report else "not written")
            print(f"Daily report {run_id}: {report['overall_status']} | Daily Tasks {tasks_status}"
                  f" | Daily Run {history_status}")
        if report.get("retained_dates"):
            print("Retained dates: " + ", ".join(report["retained_dates"]))
            print("Updated rows: " + (", ".join(map(str, report["updated_rows"])) or "none"))
        if args.refresh_today and report.get("changed_cells") is not None:
            print("Changed cells: " + (", ".join(report["changed_cells"]) or "none"))
        if report["metrics"]:
            m = report["metrics"]
            print(f"Job Scout rows: {m['tabs'][tracker.config.scout_tab]['actual_after']}; "
                  f"Indeed rows: {m['indeed']['rows_evaluated']}; "
                  f"resume candidates: {m['resume'].get('needed', 0)}")
        print(f"Audit: reports/daily/{date}/{run_id}.json")
        if args.verbose:
            for warning in report["warnings"]:
                print(f"Warning: {warning}")
            for error in report["errors"]:
                print(f"Error: {error}")
    return 1 if report["overall_status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
