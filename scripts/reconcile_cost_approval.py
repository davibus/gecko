"""Correct workflow-owned Job List approvals after removing the free-cost gate.

This command changes only existing Apply? cells. It never discovers jobs or
generates resumes. Prior validator audit provenance is required for No -> Yes.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import (GoogleTracker, _a1, _col, application_fee_required,
                            is_expired_indeed, marked, resume_approval_value)
from source_policy import is_jooble_candidate
from storage import DEFAULT_DB, JobStore
from tracker_schema import REJECT_STATUSES

TAB = "Job List"
AUDIT = ROOT / "reports/job-list-validation/20261011T125507.jsonl"
REPORTS = ROOT / "reports/cost-eligibility"
STATUS = "Apply or on Company Website (If Indeed)"


def text(value) -> str:
    return str(value or "").strip()


def norm(value) -> str:
    return text(value).casefold()


def valid_url(value) -> bool:
    parts = urlsplit(text(value))
    return parts.scheme.casefold() in {"http", "https"} and bool(parts.hostname) and not (parts.username or parts.password)


def prior_validator_no() -> set[tuple[int, str]]:
    if not AUDIT.is_file():
        raise RuntimeError(f"Missing prior validator audit: {AUDIT}")
    return {(int(event["row"]), str(event["id"]))
            for line in AUDIT.read_text(encoding="utf-8").splitlines()
            if (event := json.loads(line)).get("event") == "verified_change"
            and event.get("field") == "Apply?"
            and event.get("old_value") == "" and event.get("new_value") == "No"}


def counts(tab) -> dict[str, int]:
    result = Counter()
    for _, row in tab.rows:
        if text(row.get("ID")):
            result[norm(row.get("Apply?")) or "blank"] += 1
    return dict(result)


def plan(tab, formula_rows, store, rejected, provenance) -> tuple[list[dict], dict[str, int]]:
    rows = dict(tab.rows)
    identities = Counter(text(row.get("ID")) for row in rows.values() if text(row.get("ID")))
    urls = Counter(text(row.get("Job URL")).casefold() for row in rows.values()
                   if text(row.get("ID")) and text(row.get("Job URL")))
    anchors = [(number, column) for number, raw in formula_rows.items()
               for column, value in enumerate(raw, 1)
               if isinstance(value, str) and value.lstrip().upper().startswith("=ARRAYFORMULA(")]
    decisions = []
    reasons = Counter()
    for number, row in tab.rows:
        identity = text(row.get("ID"))
        if not identity:
            continue
        old = text(row.get("Apply?"))
        cost = row.get("Cost")
        reason = ""
        desired = old
        if norm(old) in REJECT_STATUSES:
            reason = "rejection_marker_preserved"
        elif application_fee_required(cost):
            desired = "No"
            reason = "required_application_fee"
        elif norm(old) == "no" and (number, identity) in provenance:
            status = norm(row.get(STATUS))
            notes = norm(row.get("Notes"))
            url = text(row.get("Job URL"))
            try:
                db_job = store.get(int(identity))
            except ValueError:
                db_job = None
            if identities[identity] != 1 or (url and urls[url.casefold()] != 1):
                reason = "duplicate_identity_or_url"
            elif db_job is None or db_job.status not in {"new", "reviewing"}:
                reason = "missing_or_inactive_database_job"
            elif rejected.matches_job(db_job):
                reason = "rejected_history"
            elif is_jooble_candidate(source=row.get("Source"), urls=(url,)):
                reason = "disabled_source"
            elif "rejected" in notes or notes == "no" or "invalid link" in notes:
                reason = "rejected_or_invalid_note"
            elif is_expired_indeed(status) or (status and status != "apply now"):
                reason = "expired_or_other_application_status"
            elif marked(row.get("Applied")):
                reason = "already_applied"
            elif not valid_url(url):
                reason = "invalid_url"
            elif not text(row.get("Company")) or not text(row.get("Job Title")):
                reason = "missing_job_identity"
            elif resume_approval_value(row.get("Location"), row.get("Work Arrangement"), cost) != "Yes":
                reason = "outside_utah_and_not_explicit_remote"
            else:
                desired = "Yes"
                reason = "eligible_blank_cost"
        else:
            reason = "existing_decision_preserved"
        raw = formula_rows.get(number, ())
        column = tab.headers["Apply?"]
        if desired != old and (column <= len(raw) and isinstance(raw[column - 1], str)
                               and raw[column - 1].startswith("=")):
            desired, reason = old, "formula_protected"
        if desired != old and any(number >= r and column >= c for r, c in anchors):
            desired, reason = old, "arrayformula_range_protected"
        reasons[reason] += 1
        if desired != old:
            decisions.append({"row": number, "id": identity, "old": old,
                              "new": desired, "reason": reason})
    return decisions, dict(reasons)


def run() -> dict:
    tracker = GoogleTracker()
    workbook = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
                               fields="properties(title)").execute()["properties"]["title"]
    if workbook != "Gecko Job Tracker":
        raise RuntimeError(f"Unexpected workbook: {workbook!r}")
    tab = tracker.scout(value_render_option="FORMULA")
    effective = tracker.scout()
    if tab.sheet_id != effective.sheet_id or tab.header_values != effective.header_values:
        raise RuntimeError("Job List changed during initial reads")
    if tab.title != TAB or tab.headers.get("Cost") != 8 or tab.headers.get("Apply?") != 5:
        raise RuntimeError("Current unique Cost/Apply? mapping is not H/E")
    if tab.headers.get("ID") is None or tab.headers.get("Job URL") is None:
        raise RuntimeError("Required Job List identity headers are missing")
    provenance = prior_validator_no()
    with JobStore(DEFAULT_DB) as store:
        proposed, reasons = plan(effective, tab.raw_rows or {}, store,
                                 tracker.rejected_jobs_index(), provenance)
    timestamp = datetime.now(ZoneInfo("America/Denver")).strftime("%Y%m%dT%H%M%S")
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{timestamp}-approval-reconciliation.json"
    before_rows = {str(n): row for n, row in effective.rows}
    report = {"workbook": workbook, "tab": TAB, "sheet_id": tab.sheet_id,
              "headers": list(tab.header_values), "before": counts(effective),
              "provenance_audit": str(AUDIT), "reasons": reasons,
              "proposed": proposed, "before_rows": before_rows, "applied": False}
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    fresh = tracker.scout(value_render_option="FORMULA")
    if fresh.sheet_id != tab.sheet_id or fresh.header_values != tab.header_values:
        raise RuntimeError("Job List headers changed before write")
    fresh_rows = dict(fresh.rows)
    for change in proposed:
        number = change["row"]
        if number not in fresh_rows or text(fresh_rows[number].get("ID")) != change["id"]:
            raise RuntimeError(f"Job List row {number} identity changed before write")
        if fresh_rows[number] != dict(tab.rows)[number]:
            raise RuntimeError(f"Job List row {number} changed before write")
    if proposed:
        tracker.api.values().batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
            body={"valueInputOption": "RAW", "data": [
                {"range": _a1(TAB, f"{_col(tab.headers['Apply?'])}{item['row']}"),
                 "values": [[item["new"]]]} for item in proposed]}).execute()
    after = tracker.scout()
    after_rows = dict(after.rows)
    expected = {item["row"]: item["new"] for item in proposed}
    if after.sheet_id != tab.sheet_id or after.header_values != tab.header_values:
        raise RuntimeError("Job List headers changed after write")
    for number, original in effective.rows:
        current = after_rows.get(number)
        if current is None or any(current.get(field) != original.get(field)
                                  for field in effective.headers if field != "Apply?"):
            raise RuntimeError(f"Non-approval value changed at Job List row {number}")
        if text(current.get("Apply?")) != expected.get(number, text(original.get("Apply?"))):
            raise RuntimeError(f"Approval readback failed at Job List row {number}")
    report.update(applied=True, after=counts(after), changed=len(proposed),
                  verified_rows=len(effective.rows), report_path=str(path))
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps({key: result[key] for key in
                      ("before", "after", "changed", "reasons", "report_path")}, indent=2))
