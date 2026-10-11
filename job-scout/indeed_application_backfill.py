"""Targeted Job Scout application-button backfill from rendered browser observations.

The browser observations must be captured from the visible Indeed job page. This
module never fetches Indeed over HTTP or consults the local job database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from google_tracker import (GoogleTracker, INDEED_APPLICATION_HEADER, _a1, _col,
                            normalized_indeed_status, is_expired_indeed)
from sources.indeed import extract_indeed_job_key


@dataclass
class BackfillResult:
    total_rows_before: int = 0
    indeed_rows: int = 0
    blank_before: int = 0
    existing_nonblank: dict[str, int] = field(default_factory=dict)
    statuses_found: dict[str, int] = field(default_factory=dict)
    unresolved_rows: list[int] = field(default_factory=list)
    changed_rows: list[int] = field(default_factory=list)
    blank_after: int = 0
    total_rows_after: int = 0

    def as_dict(self) -> dict[str, Any]:
        return vars(self)


def load_browser_observations(path: Path | None) -> dict[int, dict[str, Any]]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Browser observations must be a JSON array")
    result = {}
    for item in payload:
        if not isinstance(item, dict) or type(item.get("row")) is not int or item["row"] < 2:
            raise ValueError("Every browser observation needs a spreadsheet row number")
        if item["row"] in result:
            raise ValueError(f"Duplicate browser observation for row {item['row']}")
        result[item["row"]] = item
    return result


def _verified_status(row: int, job_url: str, evidence: dict[str, Any] | None,
                     now: datetime) -> str:
    if not evidence or evidence.get("row") != row:
        return ""
    if evidence.get("visible") is not True:
        return ""
    expected_key = extract_indeed_job_key(job_url)
    observed_key = extract_indeed_job_key(str(evidence.get("page_url") or ""))
    source_url = str(evidence.get("source_url") or "")
    try:
        source = urlsplit(job_url)
    except ValueError:
        return ""
    if (not observed_key or
            (expected_key and observed_key != expected_key) or
            (not expected_key and (source.hostname != "to.indeed.com" or source_url != job_url))):
        return ""
    try:
        observed_at = datetime.fromisoformat(str(evidence.get("observed_at") or ""))
        if observed_at.tzinfo is None or not 0 <= (now - observed_at).total_seconds() <= 7200:
            return ""
    except ValueError:
        return ""
    if evidence.get("primary_blue") is True:
        raw = evidence.get("button_text")
    elif evidence.get("primary_status") is True:
        raw = evidence.get("status_text")
    else:
        return ""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 200:
        return ""
    return raw.strip()


def _snapshot(tab) -> dict[int, tuple[Any, ...]]:
    return dict(tab.raw_rows or {})


def _same_except_target(before, after, target: int, allowed_rows: set[int],
                        apply_column: int | None = None) -> bool:
    if set(before) != set(after):
        return False
    for row in before:
        left, right = before[row], after[row]
        width = max(len(left), len(right))
        for col in range(1, width + 1):
            if col in (target, apply_column) and row in allowed_rows:
                continue
            if (left[col - 1] if col <= len(left) else "") != (right[col - 1] if col <= len(right) else ""):
                return False
    return True


def backfill(tracker: GoogleTracker, observations: dict[int, dict[str, Any]], *,
             now: datetime | None = None, batch_size: int = 25) -> BackfillResult:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    now = now or datetime.now(timezone.utc)
    tab = tracker.scout()
    target = tab.headers[INDEED_APPLICATION_HEADER]
    apply_column = tab.headers["Apply?"]
    original = _snapshot(tab)
    result = BackfillResult(total_rows_before=len(tab.rows))
    indeed = [(number, data) for number, data in tab.rows
              if str(data.get("Source") or "").strip().casefold() == "indeed"]
    result.indeed_rows = len(indeed)
    for _, data in indeed:
        current = str(data.get(INDEED_APPLICATION_HEADER) or "")
        if current:
            result.existing_nonblank[current] = result.existing_nonblank.get(current, 0) + 1
        else:
            result.blank_before += 1
    print(json.dumps({"before": {"total_rows": result.total_rows_before,
                             "indeed_rows": result.indeed_rows,
                             "blank": result.blank_before,
                             "existing_nonblank": result.existing_nonblank,
                             "target_column": _col(target)}}))

    planned: dict[int, str] = {}
    for number, data in indeed:
        existing_status = str(data.get(INDEED_APPLICATION_HEADER) or "")
        if is_expired_indeed(existing_status) and (
                existing_status != "Expired" or str(data.get("Apply?") or "").strip().casefold() != "no"):
            planned[number] = "Expired"
        desired = _verified_status(number, str(data.get("Job URL") or ""),
                                   observations.get(number), now)
        if not desired:
            result.unresolved_rows.append(number)
            continue
        result.statuses_found[desired] = result.statuses_found.get(desired, 0) + 1
        normalized = ("Expired" if is_expired_indeed(existing_status)
                      else normalized_indeed_status(desired))
        if existing_status != normalized or (normalized == "Expired" and
                str(data.get("Apply?") or "").strip().casefold() != "no"):
            planned[number] = normalized

    current = tab
    for offset in range(0, len(planned), batch_size):
        changes = list(planned.items())[offset:offset + batch_size]
        latest = tracker.scout()
        if (latest.sheet_id != tab.sheet_id or latest.headers[INDEED_APPLICATION_HEADER] != target
                or not _same_except_target(original, _snapshot(latest), target,
                                           set(result.changed_rows), apply_column)):
            raise RuntimeError("Job Scout structure or unrelated cells changed before the next batch; stopped")
        latest_rows = dict(latest.rows)
        for number, value in changes:
            initial = dict(tab.rows)[number]
            current_data = latest_rows.get(number)
            if current_data is None or str(current_data.get("Source") or "").strip().casefold() != "indeed":
                raise RuntimeError(f"Indeed row {number} moved or disappeared; stopped")
            if current_data.get("Job URL") != initial.get("Job URL"):
                raise RuntimeError(f"Indeed row {number} URL changed; stopped")
            if current_data.get(INDEED_APPLICATION_HEADER, "") != initial.get(INDEED_APPLICATION_HEADER, ""):
                raise RuntimeError(f"Indeed row {number} application value changed; stopped")
        entries, expected = tracker._prepare_writes(
            latest, {(number, INDEED_APPLICATION_HEADER): value for number, value in changes}
        )
        changes = [(number, value) for number, value in changes
                   if any(key[0] == number for key in expected)]
        if not entries:
            continue
        try:
            tracker.api.values().batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": entries}).execute()
        except Exception as error:
            raise RuntimeError(f"Google Sheets write failed for rows "
                               f"{[n for n, _ in changes]}: {error}") from error
        current = tracker.scout()
        actual = _snapshot(current)
        for (number, field), value in expected.items():
            raw = actual.get(number, ())
            col = latest.headers[field]
            stored = raw[col - 1] if col <= len(raw) else ""
            if stored != value:
                raise RuntimeError(f"Readback failed after batch for rows {[n for n, _ in changes]}; "
                                   f"row {number} expected {value!r}, found {stored!r}")
        if not _same_except_target(original, actual, target,
                                    set(result.changed_rows) | {n for n, _ in changes}, apply_column):
            raise RuntimeError(f"Unrelated cell or row structure changed after batch "
                               f"{[n for n, _ in changes]}; stopped")
        result.changed_rows.extend(number for number, _ in changes)
    if not planned:
        current = tracker.scout()
    result.total_rows_after = len(current.rows)
    result.blank_after = sum(
        not str(data.get(INDEED_APPLICATION_HEADER) or "")
        for _, data in current.rows if str(data.get("Source") or "").strip().casefold() == "indeed")
    if not _same_except_target(original, _snapshot(current), target,
                                set(result.changed_rows), apply_column):
        raise RuntimeError("Job Scout rows or unrelated cells changed during backfill")
    return result
