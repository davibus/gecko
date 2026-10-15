"""Audit and conservatively maintain the live Gecko Job List (no resume creation)."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import html
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
sys.path.insert(0, str(ROOT / "scripts"))
from google_tracker import (GoogleTracker, _a1, _col, verified_resume_uri_target,
                            resume_approval_value, marked)  # noqa: E402
from tracker_schema import header_key  # noqa: E402
from check_job_links import (  # noqa: E402
    BOT_RE, CheckResult, ThrottledFetcher, check_job_url, visible_text,
)

TAB = "Job List"
REQUIRED = ("ID", "Source", "Company", "Job Title", "Apply?", "Applied", "Cost", "Notes",
            "Location", "Work Arrangement",
            "Apply or on Company Website (If Indeed)", "Job URL", "Resume Link")
STATUS = "Apply or on Company Website (If Indeed)"
REPORT_DIR = ROOT / "reports" / "job-list-validation"
RED = {"red": 252 / 255, "green": 232 / 255, "blue": 230 / 255}
BUTTON_RE = re.compile(r"<(?:button|a|input)\b[^>]*(?:>.*?</(?:button|a)>|/?>)", re.I | re.S)
ATTR_RE = re.compile(r'''(?:aria-label|value|title)\s*=\s*["']([^"']+)["']''', re.I)
FEE_RE = re.compile(r"\b(?:application|apply|submission|processing)\s+fee\b.{0,100}?(?:\$\s*\d+(?:\.\d{2})?|required|mandatory)|(?:\$\s*\d+(?:\.\d{2})?).{0,100}?\b(?:application|apply|submission)\s+fee\b", re.I)
FREE_RE = re.compile(r"\b(?:no application fee|free to apply|apply for free)\b", re.I)
OPTIONAL_RE = re.compile(r"\b(?:optional|not required|upgrade|premium|subscription|course|membership)\b", re.I)


def now() -> str:
    return datetime.now(ZoneInfo("America/Denver")).isoformat(timespec="seconds")


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def log_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"time": now(), **event}, ensure_ascii=False) + "\n")
        stream.flush()


def schema(tracker: GoogleTracker, *, verify_title: bool = True):
    if verify_title:
        title = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
                                fields="properties(title)").execute()["properties"]["title"]
        if title != "Gecko Job Tracker":
            raise RuntimeError(f"Unexpected workbook title: {title!r}")
    tab = tracker.tab(TAB, value_render_option="FORMULA")
    names = [header_key(x) for x in tab.header_values if x]
    if len(names) != len(set(names)) or any(name not in tab.headers for name in REQUIRED):
        raise RuntimeError("Job List has missing or ambiguous required headers")
    # Inserted/custom columns are safe: every target is resolved by header.
    return tab


def value(data: dict, name: str) -> str:
    return str(data.get(name) or "").strip()


def _tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", text.casefold()) if len(x) > 2 and x not in
            {"the", "and", "for", "with", "senior", "manager", "director", "remote", "job"}}


def identity_supported(result: CheckResult, company: str, title: str) -> bool:
    page = visible_text(result.content)[:50000]
    page_tokens = _tokens(page)
    company_tokens = _tokens(company)
    title_tokens = _tokens(title)
    return bool(company_tokens and title_tokens and
                company_tokens <= page_tokens and
                len(title_tokens & page_tokens) >= max(1, min(2, len(title_tokens))))


def indeed_status(content: str) -> str:
    page = visible_text(content)
    if re.search(r"\b(?:this job has expired on Indeed|job no longer available|this job is no longer available)\b", page, re.I):
        return "Expired"
    labels = []
    for match in BUTTON_RE.finditer(content):
        fragment = match.group(0)
        candidates = [visible_text(fragment), *(html.unescape(x) for x in ATTR_RE.findall(fragment))]
        for candidate in candidates:
            clean = " ".join(candidate.split())
            if re.fullmatch(r"(?i)(?:apply now|apply on company website|apply on indeed|easily apply|already applied|applied)", clean):
                labels.append(clean)
    return labels[0] if len({x.casefold() for x in labels}) == 1 else ""


def cost_evidence(content: str) -> tuple[str, str]:
    text = visible_text(content)
    if FREE_RE.search(text):
        return "free", "Explicit free application statement"
    match = FEE_RE.search(text)
    if match and not OPTIONAL_RE.search(text[max(0, match.start() - 100):match.end() + 100]):
        return "paid", " ".join(match.group(0).split())
    return "unverified", ""


def inspect(row: int, data: dict) -> dict:
    url = value(data, "Job URL")
    result = {"row": row, "id": value(data, "ID"), "url": url,
              "classification": "needs_review", "reason": "Job URL is blank",
              "status": "", "cost": "unverified", "cost_evidence": "", "final_url": ""}
    if not url:
        return result
    parts = urlsplit(url)
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        result.update(classification="invalid", reason="Invalid URL syntax or unsupported protocol")
        return result
    fetcher = ThrottledFetcher(timeout=12, delay=0.8)
    try:
        checked = check_job_url(url, fetcher, retries=0)
        for attempt in range(2):
            if not checked.retryable:
                break
            time.sleep(2 ** attempt)
            checked = check_job_url(url, fetcher, retries=0)
    except Exception as error:
        result["reason"] = f"Inspection error: {type(error).__name__}: {error}"
        return result
    result["final_url"] = checked.final_url
    result["http_status"] = checked.http_status
    if checked.http_status in {404, 410} and checked.reason == f"HTTP {checked.http_status}":
        result.update(classification="invalid", reason=checked.reason)
    elif checked.status == "removed":
        # Explicit 404/410 is definitive. Text/redirect removals require job identity.
        if checked.http_status in {404, 410} or identity_supported(checked, value(data, "Company"), value(data, "Job Title")):
            result.update(classification="invalid", reason=checked.reason)
        else:
            result["reason"] = "Removal signal without confirmed job identity: " + checked.reason
    elif checked.status == "exists":
        if identity_supported(checked, value(data, "Company"), value(data, "Job Title")):
            result.update(classification="valid", reason=checked.reason)
        else:
            result["reason"] = "Loaded page did not verify company and title"
    else:
        result["reason"] = checked.reason or "Page could not be inspected reliably"
    if checked.content and checked.http_status == 200 and not BOT_RE.search(visible_text(checked.content)[:5000]):
        if value(data, "Source").casefold() == "indeed" and result["classification"] in {"valid", "invalid"}:
            result["status"] = indeed_status(checked.content)
        if result["classification"] == "valid":
            result["cost"], result["cost_evidence"] = cost_evidence(checked.content)
    return result


def marker_note(existing: str, status: str, owned: bool) -> str | None:
    clean = re.sub(r"(?:\n)?(?:Invalid Link|Needs Review)$", "", existing).strip() if owned else existing
    desired = status
    if existing == desired or (owned and clean + ("\n" if clean else "") + desired == existing):
        return None
    return clean + ("\n" if clean else "") + desired


def resume_target(raw: str) -> tuple[str, str]:
    if not raw:
        return "", "missing"
    match = re.fullmatch(r'=HYPERLINK\("((?:[^"]|"")*)","((?:[^"]|"")*)"\)', raw, re.I)
    target = match.group(1).replace('""', '"') if match else raw
    scheme = urlsplit(target).scheme.casefold()
    if scheme == "file":
        try:
            return verified_resume_uri_target(target), "valid"
        except (ValueError, OSError):
            return target, "broken"
    if scheme == "https" and urlsplit(target).hostname:
        return target, "valid"
    return target, "unverified"


def formula(target: str, label: str) -> str:
    return '=HYPERLINK("{}","{}")'.format(target.replace('"', '""'), label.replace('"', '""'))


def plan(data: dict, result: dict, owned: dict, effective_cost: str) -> tuple[dict[str, str], list[str]]:
    writes: dict[str, str] = {}
    warnings: list[str] = []
    classification = result["classification"]
    note = value(data, "Notes")
    if classification == "invalid":
        desired = marker_note(note, "Invalid Link", bool(owned.get("note")))
        if desired is not None:
            writes["Notes"] = desired
        if value(data, "Job URL"):
            writes["Job URL"] = ""
    elif classification == "needs_review":
        desired = marker_note(note, "Needs Review", bool(owned.get("note")))
        if desired is not None:
            writes["Notes"] = desired
    elif owned.get("note"):
        cleared = re.sub(r"(?:\n)?(?:Invalid Link|Needs Review)$", "", note).strip()
        if cleared != note:
            writes["Notes"] = cleared
    if result["status"] and value(data, "Source").casefold() == "indeed":
        if value(data, STATUS) != result["status"]:
            writes[STATUS] = result["status"]
    if result["cost"] == "paid" and effective_cost.casefold() != "x":
        writes["Cost"] = "x"
    status = writes.get(STATUS, value(data, STATUS))
    confirmed_status = bool(result["status"] or owned.get("status") == status)
    cost = writes.get("Cost", effective_cost)
    reject = value(data, "Notes").casefold() == "rejected" or value(data, "Apply?").casefold() == "reject"
    should_no = (classification == "invalid" or marked(data.get("Applied")) or
                 resume_approval_value(data.get("Location"), data.get("Work Arrangement"), cost) != "Yes" or
                 (confirmed_status and bool(status) and status.strip().casefold() != "apply now"))
    if should_no and not reject and value(data, "Apply?") != "No":
        writes["Apply?"] = "No"
    if reject:
        warnings.append("Explicit rejection preserved")
    target, state = resume_target(value(data, "Resume Link"))
    if owned.get("resume_target") and value(data, "Resume Link") == owned.get("resume_label"):
        target, state = owned["resume_target"], "valid"
    if state == "missing":
        warnings.append("Resume Link Missing")
    elif state == "broken":
        warnings.append("Existing resume link is broken; preserved")
    elif state == "unverified":
        warnings.append("Existing resume link cannot be verified; preserved")
    elif target:
        label = f'{value(data, "Company")} - {value(data, "Job Title")}'
        desired = formula(target, label) if target.startswith("https://") else label
        if value(data, "Resume Link") != desired or (target.startswith("file:") and owned.get("resume_target") != target):
            writes["Resume Link"] = desired
    return writes, warnings


def _raw(tab, row: int, field: str) -> str:
    values = (tab.raw_rows or {}).get(row, ())
    col = tab.headers[field]
    return str(values[col - 1]) if col <= len(values) else ""


def restore_resume_link(tracker: GoogleTracker, row: int, original: str) -> None:
    """Restore the named Resume Link cell if Sheets rejects its link target."""
    tab = schema(tracker, verify_title=False)
    cell = f"{_col(tab.headers['Resume Link'])}{row}"
    tracker.api.values().update(spreadsheetId=tracker.config.spreadsheet_id,
        range=_a1(TAB, cell), valueInputOption="USER_ENTERED" if original.startswith("=") else "RAW",
        body={"values": [[original]]}).execute()
    if _raw(schema(tracker, verify_title=False), row, "Resume Link") != original:
        raise RuntimeError(f"Could not restore original Resume Link at {cell}")


def ensure_red_rule(tracker: GoogleTracker, tab) -> None:
    """Add one scoped rule; leave every pre-existing rule unchanged."""
    apply_col = _col(tab.headers['Apply?'])
    cost_col = _col(tab.headers['Cost'])
    status_col = _col(tab.headers[STATUS])
    notes_col = _col(tab.headers['Notes'])
    rule_formula = (f'=AND(${apply_col}2="No",OR(LOWER(TRIM(${cost_col}2))="x",'
                    f'AND(LEN(TRIM(${status_col}2))>0,LOWER(TRIM(${status_col}2))<>"apply now"),'
                    f'REGEXMATCH(${notes_col}2,"Invalid Link")))')
    metadata = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
        fields="sheets(properties(sheetId,title),conditionalFormats)").execute()
    matches = [sheet for sheet in metadata.get("sheets", [])
               if sheet.get("properties", {}).get("sheetId") == tab.sheet_id and
               sheet.get("properties", {}).get("title") == TAB]
    if len(matches) != 1:
        raise RuntimeError("Job List identity changed before formatting")
    for existing in matches[0].get("conditionalFormats", []):
        values = existing.get("booleanRule", {}).get("condition", {}).get("values", [])
        if any(item.get("userEnteredValue") == rule_formula for item in values):
            return
    rule = {"ranges": [{"sheetId": tab.sheet_id, "startRowIndex": 1,
                        "endRowIndex": tab.grid_rows, "startColumnIndex": 0,
                        "endColumnIndex": 5}],
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA",
                                          "values": [{"userEnteredValue": rule_formula}]},
                            "format": {"backgroundColor": RED}}}
    tracker.api.batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
        body={"requests": [{"addConditionalFormatRule": {"rule": rule, "index": 0}}]}).execute()
    check = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
        fields="sheets(properties(sheetId),conditionalFormats)").execute()
    if not any(any(v.get("userEnteredValue") == rule_formula
                   for v in r.get("booleanRule", {}).get("condition", {}).get("values", []))
               for sheet in check.get("sheets", []) if sheet.get("properties", {}).get("sheetId") == tab.sheet_id
               for r in sheet.get("conditionalFormats", [])):
        raise RuntimeError("Job List red formatting rule failed readback")


def run(apply: bool, workers: int) -> dict:
    tracker = GoogleTracker()
    before = schema(tracker)
    displayed = tracker.tab(TAB)
    if before.sheet_id != displayed.sheet_id or before.header_values != displayed.header_values:
        raise RuntimeError("Job List changed during inventory")
    run_id = datetime.now(ZoneInfo("America/Denver")).strftime("%Y%m%dT%H%M%S")
    checkpoint = REPORT_DIR / "checkpoint.json"
    state = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
    if state.get("completed") or state.get("sheet_id") != before.sheet_id:
        state = {"run_id": run_id, "sheet_id": before.sheet_id, "completed": False,
                 "rows": {}, "ownership": state.get("ownership", {})}
    audit = REPORT_DIR / f'{state["run_id"]}.jsonl'
    results = {}
    pending = []
    row_data = dict(before.rows)
    display_data = dict(displayed.rows)
    job_count = sum(bool(value(data, "ID")) for _, data in before.rows)
    for row, data in before.rows:
        key = value(data, "ID")
        if not key:
            continue
        old = state["rows"].get(key)
        if old and old.get("url") == value(data, "Job URL") and old.get("row") == row:
            results[key] = old
        elif (not value(data, "Job URL") and state["ownership"].get(key, {}).get("note")
              and "Invalid Link" in value(data, "Notes")):
            results[key] = {"row": row, "id": key, "url": "", "classification": "invalid",
                            "reason": "Previously confirmed invalid; original URL is in the audit log",
                            "status": "", "cost": "unverified", "cost_evidence": "", "final_url": ""}
        else:
            pending.append((row, data))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(inspect, row, data): (row, data) for row, data in pending}
        for future in as_completed(futures):
            row, data = futures[future]
            key = value(data, "ID")
            try:
                result = future.result()
            except Exception as error:
                result = {"row": row, "id": key, "url": value(data, "Job URL"),
                          "classification": "needs_review", "reason": f"Worker error: {error}",
                          "status": "", "cost": "unverified", "cost_evidence": "", "final_url": ""}
            results[key] = result
            state["rows"][key] = result
            log_event(audit, {"event": "inspected", **result})
            save_json(checkpoint, state)
            if len(results) % 50 == 0:
                print(f"Inspected {len(results)}/{job_count} Job List rows", flush=True)
    summary = {"job_rows_scanned": job_count, "valid_urls": 0, "invalid_urls_cleared": 0,
               "urls_needing_review": 0, "indeed_apply_now": 0, "indeed_company_website": 0,
               "expired_jobs": 0, "other_application_statuses": 0, "confirmed_paid": 0,
               "apply_no_changed": 0, "resume_links_formatted": 0, "resume_links_missing": 0,
               "rows_highlighted": 0, "affected_rows": {}, "warnings": [], "audit_log": str(audit)}
    proposed = []
    for row, data in before.rows:
        key = value(data, "ID")
        if not key or key not in results:
            continue
        result = results[key]
        summary[{"valid": "valid_urls", "invalid": "invalid_urls_cleared", "needs_review": "urls_needing_review"}[result["classification"]]] += 1 if result["classification"] != "invalid" else 0
        if result["status"]:
            bucket = ("indeed_apply_now" if result["status"].casefold() == "apply now" else
                      "indeed_company_website" if result["status"].casefold() == "apply on company website" else
                      "expired_jobs" if result["status"] == "Expired" else "other_application_statuses")
            summary[bucket] += 1
        if result["cost"] == "paid":
            summary["confirmed_paid"] += 1
        owned = state["ownership"].get(key, {})
        effective = value(display_data[row], "Cost")
        writes, warnings = plan(data, result, owned, effective)
        if "Last Updated" in before.headers and any(number == row for number, _ in pending):
            writes["Last Updated"] = now() + " | Gecko (job validation)"
        if "Resume Link Missing" in warnings:
            summary["resume_links_missing"] += 1
        for warning in warnings:
            if warning in {"Resume Link Missing", "Existing resume link is broken; preserved",
                           "Existing resume link cannot be verified; preserved"}:
                log_event(audit, {"event": "link_warning", "row": row, "id": key,
                                  "warning": warning, "original_link": value(data, "Resume Link")})
            if warning != "Resume Link Missing":
                summary["warnings"].append({"row": row, "warning": warning})
        if writes:
            proposed.append((row, key, data, writes, result))
    if apply:
        # Re-read before each batch. A changed identity or target cell is skipped.
        for offset in range(0, len(proposed), 30):
            live = schema(tracker, verify_title=False)
            batch = proposed[offset:offset + 30]
            anchors = [(anchor_row, col) for anchor_row, raw in (live.raw_rows or {}).items()
                       for col, cell in enumerate(raw, 1)
                       if isinstance(cell, str) and cell.lstrip().upper().startswith("=ARRAYFORMULA(")]
            entries = []
            rich_requests = []
            expected = []
            for row, key, original, writes, result in batch:
                current = dict(live.rows).get(row)
                if not current or value(current, "ID") != key or any(
                    _raw(live, row, field) != value(original, field)
                    for field in set(writes) | {"ID", "Source", "Company", "Job Title", "Job URL"}
                ):
                    summary["warnings"].append({"row": row, "warning": "Row changed before write; skipped"})
                    continue
                for field, desired in writes.items():
                    old = _raw(live, row, field)
                    if any(row >= anchor_row and live.headers[field] >= anchor_col
                           for anchor_row, anchor_col in anchors):
                        summary["warnings"].append({"row": row, "warning":
                            f"Possible ARRAYFORMULA output protected: {field}"})
                        continue
                    if old.startswith("=") and field != "Resume Link":
                        summary["warnings"].append({"row": row, "warning": f"Formula protected: {field}"})
                        continue
                    # Formula-based resume links are user-owned unless created by this workflow.
                    if field == "Resume Link" and old.startswith("=") and not state["ownership"].get(key, {}).get("resume"):
                        summary["warnings"].append({"row": row, "warning": "Formula protected: Resume Link"})
                        continue
                    # Audit the old URL/link before any destructive value write.
                    if field in {"Job URL", "Resume Link"}:
                        log_event(audit, {"event": "before_change", "row": row, "id": key,
                                          "field": field, "old_value": old, "new_value": desired})
                    if field == "Resume Link" and not desired.startswith("=HYPERLINK"):
                        target, target_state = resume_target(old)
                        if target_state != "valid" or not target.startswith("file:"):
                            summary["warnings"].append({"row": row, "warning": "Resume target changed; skipped"})
                            continue
                        rich_requests.append({"updateCells": {
                            "range": {"sheetId": live.sheet_id, "startRowIndex": row - 1,
                                      "endRowIndex": row, "startColumnIndex": live.headers[field] - 1,
                                      "endColumnIndex": live.headers[field]},
                            "rows": [{"values": [{"userEnteredValue": {"stringValue": desired},
                                                   "textFormatRuns": [{"startIndex": 0,
                                                                       "format": {"link": {"uri": target}}}]}]}],
                            "fields": "userEnteredValue,textFormatRuns"}})
                    else:
                        entries.append({"range": _a1(TAB, f"{_col(live.headers[field])}{row}"),
                                        "values": [[desired]]})
                    expected.append((row, key, field, desired, result))
            if not entries and not rich_requests:
                continue
            if entries:
                tracker.api.values().batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
                    body={"valueInputOption": "USER_ENTERED", "data": entries}).execute()
            if rich_requests:
                accepted = []
                for request, item in zip(rich_requests,
                                         [item for item in expected if item[2] == "Resume Link" and
                                          not item[3].startswith("=HYPERLINK")]):
                    try:
                        tracker.api.batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
                            body={"requests": [request]}).execute()
                        accepted.append(item)
                    except Exception as error:
                        summary["warnings"].append({"row": item[0], "warning":
                            f"Google Sheets rejected file hyperlink; original preserved: {error}"})
                expected = [item for item in expected if item[2] != "Resume Link" or
                            item[3].startswith("=HYPERLINK") or item in accepted]
            verified = schema(tracker, verify_title=False)
            link_rows = [row for row, _, field, _, _ in expected if field == "Resume Link"]
            link_grid = {}
            if link_rows:
                ranges = [_a1(TAB, f"{_col(verified.headers['Resume Link'])}{row}") for row in link_rows]
                grid = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
                    ranges=ranges, includeGridData=True,
                    fields="sheets(data(startRow,startColumn,rowData(values(hyperlink,textFormatRuns))))").execute()
                for sheet in grid.get("sheets", []):
                    for block in sheet.get("data", []):
                        cells = block.get("rowData", [{}])[0].get("values", [])
                        if cells:
                            link_grid[block.get("startRow", -1) + 1] = cells[0]
            for row, key, field, desired, result in expected:
                actual = _raw(verified, row, field)
                if value(dict(verified.rows)[row], "ID") != key:
                    raise RuntimeError(f"Readback failed at {_col(verified.headers[field])}{row}: {field}")
                if field == "Resume Link":
                    old_target, _ = resume_target(value(row_data[row], "Resume Link"))
                    cell = link_grid.get(row, {})
                    actual_target = cell.get("hyperlink") or next(
                        (run.get("format", {}).get("link", {}).get("uri") for run in cell.get("textFormatRuns", [])
                         if run.get("format", {}).get("link", {}).get("uri")), "")
                    if actual != desired or actual_target != old_target:
                        original = value(row_data[row], "Resume Link")
                        restore_resume_link(tracker, row, original)
                        summary["warnings"].append({"row": row, "warning":
                            "Resume hyperlink target did not survive readback; original restored"})
                        log_event(audit, {"event": "resume_link_restored", "row": row,
                                          "id": key, "original_link": original})
                        continue
                elif actual != desired:
                    raise RuntimeError(f"Readback failed at {_col(verified.headers[field])}{row}: {field}")
                if field == "Job URL":
                    summary["invalid_urls_cleared"] += 1
                if field == "Apply?":
                    summary["apply_no_changed"] += 1
                if field == "Resume Link":
                    summary["resume_links_formatted"] += 1
                owned = state["ownership"].setdefault(key, {})
                if field == "Notes": owned["note"] = bool(desired and
                    desired.splitlines()[-1] in {"Invalid Link", "Needs Review"})
                if field == "Cost": owned["cost"] = desired == "x"
                if field == STATUS: owned["status"] = desired
                if field == "Resume Link":
                    owned["resume"] = True
                    owned["resume_target"] = old_target
                    owned["resume_label"] = desired
                log_event(audit, {"event": "verified_change", "row": row, "id": key,
                                  "field": field, "old_value": value(row_data[row], field), "new_value": desired,
                                  "evidence": result.get("cost_evidence") if field == "Cost" else result.get("reason"),
                                  "source_url": result.get("final_url") or result.get("url")})
            save_json(checkpoint, state)
            # The shared service account has a per-minute Sheets read quota.
            time.sleep(6)
        ensure_red_rule(tracker, schema(tracker, verify_title=False))
        after = tracker.tab(TAB)
        summary["rows_highlighted"] = sum(
            value(data, "Apply?") == "No" and (
                value(data, "Cost").casefold() == "x" or
                bool(value(data, STATUS)) and value(data, STATUS).casefold() != "apply now" or
                "Invalid Link" in value(data, "Notes"))
            for _, data in after.rows)
        summary["highlighted_rows"] = [row for row, data in after.rows if
            value(data, "Apply?") == "No" and (
                value(data, "Cost").casefold() == "x" or
                bool(value(data, STATUS)) and value(data, STATUS).casefold() != "apply now" or
                "Invalid Link" in value(data, "Notes"))]
        state["completed"] = True
        save_json(checkpoint, state)
    summary["affected_rows"] = {name: sorted({e["row"] for e in _read_events(audit)
                                             if e.get("event") == "verified_change" and e.get("field") == name})
                                for name in ("Job URL", "Cost", "Notes", STATUS, "Apply?", "Resume Link")}
    if apply:
        summary["affected_rows"]["light_red"] = summary["highlighted_rows"]
    summary_path = REPORT_DIR / f'{state["run_id"]}-summary.json'
    save_json(summary_path, summary)
    summary["summary_path"] = str(summary_path)
    return summary


def _read_events(path: Path):
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            yield json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write verified changes to Job List")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent website checks (1-4)")
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        parser.error("--workers must be between 1 and 4")
    try:
        print(json.dumps(run(args.apply, args.workers), indent=2))
    except Exception as error:
        print(f"Job List validation stopped: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
