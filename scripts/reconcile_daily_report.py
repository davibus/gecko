"""Reconcile a failed report from its validated audit, without running jobs."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import daily_report as report
from daily_run_history import preflight_history, write_history, read_history
from daily_tasks_dashboard import _parse as parse_dashboard, SOURCE_NAMES
from tracker_schema import DAILY_RUN_TAB


def _load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if path.name != data.get("run_id", "") + ".json" or path.parent.name != data.get("run_date"):
        raise RuntimeError("Audit path does not match its run identity")
    return data


def _restore_tab_if_missing(tracker, *, allowed: bool) -> bool:
    props = [p for p in tracker._sheet_properties() if p.get("title") == DAILY_RUN_TAB]
    if len(props) == 1:
        return False
    if props or not allowed:
        raise RuntimeError("Daily Run tab is missing or ambiguous; explicit restore required")
    try:
        tracker.api.batchUpdate(spreadsheetId=tracker.config.spreadsheet_id, body={"requests": [
            {"addSheet": {"properties": {"title": DAILY_RUN_TAB,
                "gridProperties": {"rowCount": 1000, "columnCount": 46}}}}
        ]}).execute()
    except Exception:
        # A successful addSheet may lose its response. Inspect the server first.
        if len([p for p in tracker._sheet_properties() if p.get("title") == DAILY_RUN_TAB]) != 1:
            raise
    props = [p for p in tracker._sheet_properties() if p.get("title") == DAILY_RUN_TAB]
    if len(props) != 1 or any(any(v not in (None, "") for v in row) for row in read_history(tracker)):
        raise RuntimeError("Restored Daily Run is not uniquely empty")
    tracker.api.batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
        body={"requests": [{"updateDimensionProperties": {
            "range": {"sheetId": props[0]["sheetId"], "dimension": "ROWS",
                      "startIndex": 0, "endIndex": props[0]["gridProperties"]["rowCount"]},
            "properties": {"pixelSize": 21}, "fields": "pixelSize"}}]}).execute()
    return True


def reconcile(tracker, failed_audit: Path, *, restore_missing_daily_run: bool,
              historical_audit: Path | None = None, report_api=None) -> dict:
    report = report_api or globals()["report"]
    source = _load(failed_audit)
    if source.get("overall_status") != "FAIL" or not source.get("metrics"):
        raise RuntimeError("Reconciliation requires a failed audit with complete metrics")
    expected_hash = source.get("validation", {}).get("before_hash")
    if not expected_hash or source.get("validation", {}).get("after_hash") != expected_hash:
        raise RuntimeError("Failed audit lacks a validated source snapshot")
    result_path = failed_audit.with_name(failed_audit.stem + ".reconciliation.json")
    result = {"run_id": source["run_id"], "run_date": source["run_date"],
              "source_audit": str(failed_audit), "overall_status": "FAIL",
              "tab_results": {"Daily Tasks": {"state": "not written"},
                              "Daily Run": {"state": "not written"}},
              "restored_historical_dates": [], "errors": []}
    prepared = dict(source)
    prepared["overall_status"] = "WARNING"
    prepared["errors"] = []
    prepared["warnings"] = list(source.get("warnings", [])) + [
        "Reconciled from the original failed audit; original failure retained separately."]
    try:
        with report.report_lock(failed_audit.parent.parent / ".daily-report.lock"):
            if report.fingerprint(report.snapshot(tracker)) != expected_hash:
                raise RuntimeError("Job-tracking data changed since failed audit; reconciliation stopped")
            baseline = report.report_values(tracker)
            existing, _ = parse_dashboard(baseline)
            today = source["run_date"]
            if today in existing and existing[today]["Run ID"] != source["run_id"]:
                raise RuntimeError("Daily Tasks has a different report for this date; no replacement made")
            restore_fields = None
            if historical_audit and not existing:
                prior = _load(historical_audit)
                if prior.get("overall_status") not in ("WARNING", "PASS") or not prior.get("report_row"):
                    raise RuntimeError("Historical audit was not a verified report")
                if prior["run_date"] >= today:
                    raise RuntimeError("Historical audit date is not earlier than failed run")
                restore_fields = report.report_fields(prior, historical_audit)
            created = _restore_tab_if_missing(tracker, allowed=restore_missing_daily_run)
            result["daily_run_tab_created"] = created
            fields = report.report_fields(prepared, result_path)
            preflight_history(tracker, fields)
            pending = failed_audit.parent.parent / ".dashboard-pending.json"
            if restore_fields:
                report.write_report(tracker, restore_fields, pending_path=pending)
                result["restored_historical_dates"].append(restore_fields["Run Date"])
                report.atomic_json(result_path, result)
            row, dates, _, changed = report.write_report(tracker, fields, pending_path=pending)
            after_tasks = report.report_values(tracker)
            entries, _ = parse_dashboard(after_tasks)
            if row is None or entries[today]["Run ID"] != source["run_id"]:
                raise RuntimeError("Daily Tasks reconciliation failed readback")
            if report.unrelated_tasks(baseline, set(range(1, 7))) != report.unrelated_tasks(after_tasks, set(range(1, 7))):
                raise RuntimeError("Unrelated Daily Tasks cells changed")
            result["tab_results"]["Daily Tasks"] = {"state": "verified", "row": row,
                "dates": dates, "changed_rows": sorted(changed),
                "changed_cells": report.changed_dashboard_cells(baseline, after_tasks)}
            report.atomic_json(result_path, result)
            history_row, height = write_history(tracker, fields)
            preflight_history(tracker, fields)
            result["tab_results"]["Daily Run"] = {"state": "inserted" if height else "already present and verified",
                "row": history_row if height else None, "rows_inserted": height}
            if report.fingerprint(report.snapshot(tracker)) != expected_hash:
                raise RuntimeError("Job-tracking data changed after reconciliation")
            if parse_dashboard(report.report_values(tracker))[0][today]["Run ID"] != source["run_id"]:
                raise RuntimeError("Daily Tasks final readback failed")
            result["overall_status"] = "WARNING"
    except Exception as error:
        result["errors"].append(report.public_error(error))
    finally:
        report.atomic_json(result_path, result)
    return result


def restore_tasks(tracker, audit_path: Path, *, historical_audit: Path | None = None,
                  report_api=None) -> dict:
    """Restore missing Daily Tasks values for an already committed Daily Run."""
    report = report_api or globals()["report"]
    source = _load(audit_path)
    expected_hash = source.get("validation", {}).get("after_report_hash")
    if source.get("overall_status") not in ("WARNING", "PASS") or not expected_hash:
        raise RuntimeError("Daily Tasks restoration requires a verified successful audit")
    result_path = audit_path.with_name(audit_path.stem + ".tasks-restoration.json")
    result = {"run_id": source["run_id"], "run_date": source["run_date"],
              "source_audit": str(audit_path), "status": "FAIL", "action": "none",
              "restored_historical_dates": [], "changed_cells": [], "errors": []}
    try:
        with report.report_lock(audit_path.parent.parent / ".daily-report.lock"):
            if report.fingerprint(report.snapshot(tracker)) != expected_hash:
                raise RuntimeError("Job-tracking data changed since audit; restoration stopped")
            fields = report.report_fields(source, audit_path)
            _, _, history_present = preflight_history(tracker, fields)
            if not history_present:
                raise RuntimeError("Daily Run entry is missing; Daily Tasks-only restoration stopped")
            before = report.report_values(tracker)
            entries, _ = parse_dashboard(before)
            day = source["run_date"]
            if day in entries:
                visible = entries[day]
                if visible.get("Run ID") != source["run_id"]:
                    raise RuntimeError("Daily Tasks has a different run for this date")
                for name, expected in fields.items():
                    if name == "Jobs by Source":
                        labels = {SOURCE_NAMES.get(str(k).casefold(), str(k)): int(v)
                                  for k, v in expected.items()}
                        if visible.get(name) != labels:
                            raise RuntimeError("Daily Tasks source counts differ from audit")
                    elif name not in {"Execution Seconds", "Report Details", "Started At", "Completed At"}:
                        if visible.get(name) != expected:
                            raise RuntimeError(f"Daily Tasks {name} differs from audit; no overwrite made")
                for name in ("Started At", "Completed At"):
                    if visible.get(name) != datetime.fromisoformat(fields[name]).strftime("%I:%M %p"):
                        raise RuntimeError(f"Daily Tasks {name} differs from audit; no overwrite made")
                result["action"] = "already populated and verified"
                result["row"] = 3 if list(entries)[0] == day else None
            else:
                if not entries and historical_audit:
                    prior = _load(historical_audit)
                    if prior.get("overall_status") not in ("WARNING", "PASS") or not prior.get("report_row"):
                        raise RuntimeError("Historical audit was not a verified report")
                    if prior["run_date"] >= day:
                        raise RuntimeError("Historical audit date is not earlier than target")
                    report.write_report(tracker, report.report_fields(prior, historical_audit),
                                        pending_path=audit_path.parent.parent / ".dashboard-pending.json")
                    result["restored_historical_dates"].append(prior["run_date"])
                row, dates, _, _ = report.write_report(tracker, fields,
                                      pending_path=audit_path.parent.parent / ".dashboard-pending.json")
                after = report.report_values(tracker)
                restored, _ = parse_dashboard(after)
                if row is None or restored.get(day, {}).get("Run ID") != source["run_id"]:
                    raise RuntimeError("Daily Tasks restoration failed readback")
                if report.unrelated_tasks(before, set(range(1, 7))) != report.unrelated_tasks(after, set(range(1, 7))):
                    raise RuntimeError("Unrelated Daily Tasks cells changed")
                result.update({"action": "restored", "row": row, "retained_dates": dates,
                               "changed_cells": report.changed_dashboard_cells(before, after)})
            if report.fingerprint(report.snapshot(tracker)) != expected_hash:
                raise RuntimeError("Job-tracking data changed after restoration")
            _, _, history_present = preflight_history(tracker, fields)
            if not history_present:
                raise RuntimeError("Daily Run entry disappeared during restoration")
            result["status"] = "VERIFIED"
    except Exception as error:
        result["errors"].append(report.public_error(error))
    finally:
        report.atomic_json(result_path, result)
    return result
