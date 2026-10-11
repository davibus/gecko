"""Owned A:F vertical dashboard in the existing Daily Tasks worksheet."""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path

from google_tracker import _a1
from tracker_schema import DAILY_TASKS_TAB

TITLE = "GECKO DAILY TASKS REPORT"
TOP = "DAILY TASKS"
MAX_DATES = 5
SECTIONS = (
    ("RUN INFORMATION", ("Run Date", "Run ID", "Started At", "Completed At", "Mode", "Overall Status")),
    ("JOB DISCOVERY", ("Job Scout Found", "Indeed Found", "Total Found", "New Unique Jobs", "Existing Jobs", "Duplicate Discoveries", "Cross-Source Duplicates", "Qualified Jobs", "Rejected Jobs")),
    ("TRACKER CHANGES", ("Job Scout Actual Before", "Job Scout Actual After", "Job Scout Projected After", "Indeed Actual Before", "Indeed Actual After", "Indeed Projected After", "Projected Adds", "Projected Updates")),
    ("DELETED JOBS PROTECTION", ("Deleted Actual Before", "Deleted Actual After", "Deleted Projected After", "Rediscovered Deleted Jobs", "Projected Moves")),
    ("INDEED STATUS", ("Indeed Rows Evaluated", "Indeed Blank Status Before", "Indeed Blank Status Projected After", "Indeed Blank Status Actual After")),
    ("RESUME READINESS", ("Resumes Needed", "Existing Resumes", "Invalid Resume Links", "Resumes Reused", "Duplicate Resumes Prevented")),
    ("APPLICATION READINESS", ("Jobs Ready to Apply", "Jobs Already Applied", "Jobs Needing Review")),
    ("ERRORS & SCRIPT HEALTH", ("Errors", "Warnings", "Execution Seconds")),
    ("AUDIT INFORMATION", ("Audit Log Location", "Report Details")),
)
FIELDS = tuple(field for _, fields in SECTIONS for field in fields)
SOURCE_NAMES = {"adzuna": "Adzuna", "ashby": "Ashby", "greenhouse": "Greenhouse",
                "indeed": "Indeed", "jobicy": "Jobicy", "jooble": "Jooble",
                "lever": "Lever", "linkedin": "LinkedIn", "remoteok": "RemoteOK",
                "remotive": "Remotive", "web-careers": "Web Careers",
                "weworkremotely": "We Work Remotely", "workable": "Workable",
                "workingnomads": "Working Nomads"}


def cell(rows, row, col):
    return rows[row-1][col-1] if row <= len(rows) and col <= len(rows[row-1]) else ""


def read(tracker):
    return tracker.api.values().get(spreadsheetId=tracker.config.spreadsheet_id,
        range=_a1(DAILY_TASKS_TAB, "A1:AT"), valueRenderOption="FORMULA").execute().get("values", [])


def _trim(rows):
    result = [list(row[:6]) + [""] * max(0, 6-len(row)) for row in rows]
    while result and not any(v not in (None, "") for v in result[-1]):
        result.pop()
    return result


def _block(fields, *, display_sources=True):
    run_date = date.fromisoformat(str(fields["Run Date"]))
    rows = [[TITLE, "", "", "", "", ""],
            [f"{run_date:%B} {run_date.day}, {run_date.year}", "", "", "", "", ""],
            ["", "", "", "", "", ""]]
    styles = {"title": [0], "date": [1], "section": [], "source_header": [],
              "status_pass": [], "status_warning": [], "status_fail": [],
              "numbers": [], "audit": []}
    counts = fields.get("Jobs by Source", {})
    if not isinstance(counts, dict):
        raise RuntimeError("Jobs by Source must contain current tracker counts")
    sources = sorted(counts.items(), key=lambda item: (-int(item[1]), str(item[0]).casefold()))
    for section, names in SECTIONS:
        styles["section"].append(len(rows))
        rows.append([section, "", "", "", "", ""])
        first = len(rows)
        for name in names:
            value = fields.get(name, "Unavailable")
            if value is None:
                value = "Unavailable"
            if name in {"Started At", "Completed At"} and value != "Unavailable" and "T" in str(value):
                value = datetime.fromisoformat(str(value)).strftime("%I:%M %p")
            if name == "Overall Status":
                styles["status_" + str(value).lower()].append(len(rows))
            if name in {"Audit Log Location", "Report Details"}:
                styles["audit"].append(len(rows))
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                styles["numbers"].append(len(rows))
            rows.append([name, value, "", "", "", ""])
        if section == "JOB DISCOVERY":
            styles["source_header"].append(first)
            needed = first + 1 + len(sources)
            while len(rows) < needed:
                rows.append(["", "", "", "", "", ""])
            rows[first][4:6] = ["Existing Tracker Jobs by Source", "Jobs in Tracker"]
            for offset, (source, count) in enumerate(sources, first + 1):
                display = SOURCE_NAMES.get(str(source).casefold(), str(source)) if display_sources else str(source)
                rows[offset][4:6] = [display, int(count)]
        rows.append(["", "", "", "", "", ""])
    rows.append(["", "", "", "", "", ""])
    return rows, styles


def _parse(rows):
    """Read only a complete dashboard; reject unknown A:F content."""
    grid = _trim(rows)
    if not grid:
        return {}, 0
    if grid[0][0] != TOP or any(grid[0][1:]):
        raise RuntimeError("Daily Tasks A:F contains unrelated content; no write made")
    starts = [i for i, row in enumerate(grid) if row[0] == TITLE]
    if not starts:
        raise RuntimeError("Daily Tasks has no recognizable dashboard blocks")
    if any(any(v not in (None, "") for v in row) for row in grid[1:starts[0]]):
        raise RuntimeError("Unrelated Daily Tasks content precedes dashboard")
    found = {}
    for index, start in enumerate(starts):
        end = starts[index+1] if index+1 < len(starts) else len(grid)
        segment = grid[start:end]
        values = {row[0]: row[1] for row in segment if row[0] in FIELDS}
        run_date = str(values.get("Run Date") or "")
        if not run_date or not values.get("Run ID"):
            raise RuntimeError("Partial Daily Tasks dashboard block; inspect local audit before retry")
        date.fromisoformat(run_date)
        if run_date in found:
            raise RuntimeError("Daily Tasks has duplicate report date")
        sources = {}
        for row in segment:
            if row[4] and row[4] != "Existing Tracker Jobs by Source":
                if not isinstance(row[5], (int, float)):
                    raise RuntimeError("Daily Tasks source table is incomplete")
                sources[str(row[4])] = int(row[5])
        values["Jobs by Source"] = sources
        found[run_date] = values
    if list(found) != sorted(found, reverse=True) or len(found) > MAX_DATES:
        raise RuntimeError("Daily Tasks report dates are not in canonical order")
    expected, _, _ = _render(found)
    prior_labels, _, _ = _render(found, display_sources=False)
    if _trim(expected) != grid and _trim(prior_labels) != grid:
        raise RuntimeError("Daily Tasks dashboard contains partial or unrelated content")
    return found, len(grid)


def _render(entries, *, display_sources=True):
    rows = [[TOP, "", "", "", "", ""], ["", "", "", "", "", ""]]
    styles = {name: [] for name in ("title", "date", "section", "source_header",
                                     "status_pass", "status_warning", "status_fail",
                                     "numbers", "audit")}
    starts = {}
    for report_date in sorted(entries, reverse=True):
        starts[report_date] = len(rows) + 1
        block, local = _block(entries[report_date], display_sources=display_sources)
        base = len(rows)
        rows.extend(block)
        for name, offsets in local.items():
            styles[name].extend(base + offset for offset in offsets)
    return rows, styles, starts


def _format_requests(sheet_id, styles, end_row, initial):
    navy = {"red": .13, "green": .22, "blue": .32}
    pale = {"red": .91, "green": .94, "blue": .97}
    requests = []
    requests.append({"repeatCell": {"range": {"sheetId": sheet_id,
        "startRowIndex": 0, "endRowIndex": end_row,
        "startColumnIndex": 0, "endColumnIndex": 6},
        "cell": {"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 1, "blue": 1},
            "textFormat": {"foregroundColor": {"red": .15, "green": .18, "blue": .22},
                           "fontFamily": "Arial", "fontSize": 10}}},
        "fields": "userEnteredFormat"}})
    def rep(row, start, end, fmt):
        requests.append({"repeatCell": {"range": {"sheetId": sheet_id,
            "startRowIndex": row, "endRowIndex": row+1, "startColumnIndex": start,
            "endColumnIndex": end}, "cell": {"userEnteredFormat": fmt},
            "fields": "userEnteredFormat"}})
    rep(0, 0, 6, {"backgroundColor": navy, "textFormat": {"bold": True,
        "foregroundColor": {"red": 1, "green": 1, "blue": 1}, "fontSize": 13}})
    for row in styles["title"]:
        rep(row, 0, 6, {"backgroundColor": navy, "textFormat": {"bold": True,
            "foregroundColor": {"red": 1, "green": 1, "blue": 1}, "fontSize": 12}})
    for row in styles["date"]:
        rep(row, 0, 2, {"textFormat": {"bold": True, "fontSize": 11}})
    for row in styles["section"]:
        rep(row, 0, 6, {"backgroundColor": pale,
            "textFormat": {"bold": True, "foregroundColor": navy}})
    for row in styles["source_header"]:
        rep(row, 4, 6, {"backgroundColor": pale,
            "textFormat": {"bold": True, "foregroundColor": navy}, "wrapStrategy": "WRAP"})
    for status, color in (("pass", {"red": .86, "green": .95, "blue": .88}),
                          ("warning", {"red": 1, "green": .94, "blue": .79}),
                          ("fail", {"red": .98, "green": .85, "blue": .85})):
        for row in styles["status_" + status]:
            rep(row, 1, 2, {"backgroundColor": color,
                "textFormat": {"bold": True, "foregroundColor": navy}})
    for row in styles["numbers"]:
        rep(row, 1, 2, {"horizontalAlignment": "RIGHT"})
    for row in styles["audit"]:
        rep(row, 1, 2, {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"})
        requests.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id,
            "dimension": "ROWS", "startIndex": row, "endIndex": row+1},
            "properties": {"pixelSize": 54}, "fields": "pixelSize"}})
    for row in range(2, end_row):
        requests.append({"repeatCell": {"range": {"sheetId": sheet_id,
            "startRowIndex": row, "endRowIndex": row+1, "startColumnIndex": 5,
            "endColumnIndex": 6}, "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT"}},
            "fields": "userEnteredFormat.horizontalAlignment"}})
    if initial:
        for col, pixels in ((0, 280), (1, 260), (2, 24), (3, 24), (4, 260), (5, 130)):
            requests.append({"updateDimensionProperties": {"range": {"sheetId": sheet_id,
                "dimension": "COLUMNS", "startIndex": col, "endIndex": col+1},
                "properties": {"pixelSize": pixels}, "fields": "pixelSize"}})
        requests.append({"updateSheetProperties": {"properties": {"sheetId": sheet_id,
            "gridProperties": {"frozenRowCount": 1}}, "fields": "gridProperties.frozenRowCount"}})
    return requests


def write(tracker, fields, *, pending_path: Path | None = None):
    props = [p for p in tracker._sheet_properties() if p.get("title") == DAILY_TASKS_TAB]
    if len(props) != 1:
        raise RuntimeError("Daily Tasks tab was not found exactly once; no tab was created")
    prop = props[0]
    before = read(tracker)
    if pending_path and pending_path.exists():
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
        original, intended = pending["before"], pending["desired"]
        limit = max(len(original), len(intended))
        for row in range(1, limit+1):
            for col in range(1, 7):
                if cell(before,row,col) not in (cell(original,row,col), cell(intended,row,col)):
                    raise RuntimeError("Daily Tasks differs from pending report plan; manual review required")
        tracker.api.values().update(spreadsheetId=tracker.config.spreadsheet_id,
            range=_a1(DAILY_TASKS_TAB, f"A1:F{limit}"), valueInputOption="RAW",
            body={"values": intended + [[""]*6 for _ in range(limit-len(intended))]}).execute()
        before = read(tracker)
        if _trim(before) != _trim(intended):
            raise RuntimeError("Pending Daily Tasks report recovery failed readback")
        pending_path.unlink()
    existing, old_height = _parse(before)
    report_date = str(fields["Run Date"])
    date.fromisoformat(report_date)
    if any(d != report_date and str(v["Run ID"]) == str(fields["Run ID"]) for d,v in existing.items()):
        raise RuntimeError("Run ID already belongs to a different reporting date")
    proposed = {**existing, report_date: fields}
    dates = sorted(proposed, reverse=True)[:MAX_DATES]
    if report_date not in dates:
        return None, dates, set(range(1,7)), set()
    entries = {d: proposed[d] for d in dates}
    desired, styles, starts = _render(entries)
    height = max(len(desired), old_height)
    if height > prop.get("gridProperties", {}).get("rowCount", 1000):
        raise RuntimeError("Daily Tasks has insufficient rows for reporting")
    if prop.get("gridProperties", {}).get("columnCount", 26) < 6:
        raise RuntimeError("Daily Tasks has insufficient columns for reporting")
    meta = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
        fields="sheets(properties(sheetId),protectedRanges(range))").execute()
    for sheet in meta.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") != prop["sheetId"]:
            continue
        for protected in sheet.get("protectedRanges", []):
            target = protected.get("range", {})
            if target.get("startRowIndex", 0) < height and target.get("endRowIndex", height) > 0 \
                    and target.get("startColumnIndex", 0) < 6 and target.get("endColumnIndex", 6) > 0:
                raise RuntimeError("Daily Tasks reporting area has a protected range")
    for row in range(1, height+1):
        for col in range(1, 7):
            value = cell(before, row, col)
            if isinstance(value, str) and value.lstrip().startswith("="):
                raise RuntimeError(f"Formula protects Daily Tasks {row}, {col}")
            if row > old_height and value not in (None, ""):
                raise RuntimeError("Unrelated Daily Tasks content occupies new report area")
    for r, line in enumerate(before, 1):
        for c, value in enumerate(line, 1):
            if c > 6 and isinstance(value, str) and "ARRAYFORMULA" in value.upper() and value.lstrip().startswith("="):
                if r <= height:
                    raise RuntimeError("ARRAYFORMULA may spill into reporting area")
    if pending_path:
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_text(json.dumps({"run_id": fields["Run ID"], "date": report_date,
            "before": _trim(before), "desired": desired}, default=str), encoding="utf-8")
    padded = desired + [[""]*6 for _ in range(height-len(desired))]
    tracker.api.values().update(spreadsheetId=tracker.config.spreadsheet_id,
        range=_a1(DAILY_TASKS_TAB, f"A1:F{height}"), valueInputOption="RAW",
        body={"values": padded}).execute()
    after = read(tracker)
    if _trim(after) != _trim(desired):
        raise RuntimeError("Daily Tasks dashboard failed cell readback; local pending plan retained")
    for row, line in enumerate(before, 1):
        for col in range(7, len(line)+1):
            if cell(after, row, col) != cell(before, row, col):
                raise RuntimeError("Unrelated Daily Tasks content changed")
    initially_blank = not any(any(value not in (None, "") for value in row[:6]) for row in before)
    tracker.api.batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
        body={"requests": _format_requests(prop["sheetId"], styles, height,
                                            initially_blank)}).execute()
    if pending_path:
        pending_path.unlink(missing_ok=True)
    changed = {r for r in range(1, height+1) if [cell(before,r,c) for c in range(1,7)] != padded[r-1]}
    return starts[report_date], dates, set(range(1,7)), changed
