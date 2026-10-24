"""Append a report block at row 3 of the existing Daily Run sheet.

The fixed A/B and E/F layout belongs to this module. Other tabs use named
headers. No tab is created, and an unknown Daily Run layout blocks insertion.
"""

from __future__ import annotations

import json

from google_tracker import GoogleTracker, _a1
from tracker_schema import DAILY_RUN_TAB

FIRST_ROW = 3
SOURCE_LABEL_OFFSET = 6  # E9 for the newest block.
ZERO_FALLBACK_METRICS = frozenset({
    "Job Scout Found", "Indeed Found", "Total Found", "New Unique Jobs",
    "Existing Jobs", "Duplicate Discoveries", "Cross-Source Duplicates",
    "Qualified Jobs", "Rejected Jobs", "Rediscovered Deleted Jobs",
    "Job Scout Projected After", "Indeed Projected After",
    "Deleted Projected After", "Projected Adds", "Projected Updates",
    "Projected Moves", "Resumes Reused",
})


def _display_value(name: str, value):
    if name in ZERO_FALLBACK_METRICS and (
        value is None or isinstance(value, str) and value.strip().casefold() in {"", "unavailable"}
    ):
        return 0
    if value is None:
        return ""
    return value


def _cell(rows: list[list], row: int, col: int):
    return rows[row - 1][col - 1] if row <= len(rows) and col <= len(rows[row - 1]) else ""


def build_block(fields: dict) -> list[list]:
    """Return A:F rows, including one blank separator row."""
    sources = fields["Jobs by Source"]
    if isinstance(sources, str):
        sources = json.loads(sources)
    if not isinstance(sources, dict):
        raise RuntimeError("Jobs by Source must be a source/count mapping")
    metrics = [(name, _display_value(name, value)) for name, value in fields.items()
               if name not in {"Run Date", "Run ID", "Jobs by Source", "Report Details"}]
    height = max(2 + len(metrics), SOURCE_LABEL_OFFSET + 1 + len(sources)) + 1
    rows = [[""] * 6 for _ in range(height)]
    rows[0][:2] = ["Daily Run", fields["Run Date"]]
    rows[1][:2] = ["Run ID", fields["Run ID"]]
    for offset, (name, value) in enumerate(metrics, 2):
        rows[offset][:2] = [name, value]
    rows[SOURCE_LABEL_OFFSET][4] = "Jobs by Source"
    for offset, (source, count) in enumerate(sorted(sources.items(), key=lambda pair: pair[0].casefold()),
                                             SOURCE_LABEL_OFFSET + 1):
        if isinstance(count, bool) or not isinstance(count, (int, float)):
            raise RuntimeError(f"Jobs by Source count is not numeric for {source!r}")
        rows[offset][4:6] = [str(source), count]
    return rows


def inspect_history(rows: list[list], run_id: str) -> bool:
    """Validate recognizable history and report whether this Run ID exists."""
    if any(_cell(rows, row, col) not in (None, "") for row in (1, 2) for col in range(1, 7)):
        raise RuntimeError("Daily Run rows 1-2 are occupied; no report inserted")
    if any(isinstance(value, str) and value.lstrip().startswith("=")
           for row in rows for value in row):
        raise RuntimeError("Daily Run contains formulas; row insertion requires manual review")
    if len(rows) >= FIRST_ROW and any(value not in (None, "") for value in rows[FIRST_ROW - 1]):
        if _cell(rows, FIRST_ROW, 1) != "Daily Run" or _cell(rows, FIRST_ROW + 1, 1) != "Run ID":
            raise RuntimeError("Daily Run row 3 has an unknown layout; no report inserted")
    elif any(value not in (None, "") for row in rows[FIRST_ROW - 1:] for value in row):
        raise RuntimeError("Daily Run has a blank gap before existing history; no report inserted")
    ids = [str(_cell(rows, number + 1, 2))
           for number in range(FIRST_ROW, len(rows) + 1)
           if _cell(rows, number, 1) == "Daily Run"
           and _cell(rows, number + 1, 1) == "Run ID"]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Daily Run contains duplicate Run IDs")
    return str(run_id) in ids


def _verify_existing(rows: list[list], fields: dict) -> None:
    """Accept a retry only when its existing run block is complete and readable."""
    starts = [number for number in range(FIRST_ROW, len(rows) + 1)
              if _cell(rows, number, 1) == "Daily Run"
              and _cell(rows, number + 1, 1) == "Run ID"
              and str(_cell(rows, number + 1, 2)) == str(fields["Run ID"])]
    if len(starts) != 1:
        raise RuntimeError("Daily Run retry has no unique completed run block")
    start = starts[0]
    if str(_cell(rows, start, 2)) != str(fields["Run Date"]):
        raise RuntimeError("Daily Run Run ID belongs to a different date")
    expected = build_block(fields)
    for offset, line in enumerate(expected):
        if line[0] and _cell(rows, start + offset, 1) != line[0]:
            raise RuntimeError("Daily Run existing block has missing or shifted metrics")
    if _cell(rows, start + SOURCE_LABEL_OFFSET, 5) != "Jobs by Source":
        raise RuntimeError("Daily Run existing block has no source table")
    for offset in range(SOURCE_LABEL_OFFSET + 1, len(expected) - 1):
        source = _cell(rows, start + offset, 5)
        count = _cell(rows, start + offset, 6)
        if source != expected[offset][4]:
            raise RuntimeError("Daily Run existing block has missing or shifted sources")
        if source and (isinstance(count, bool) or not isinstance(count, (int, float))):
            raise RuntimeError("Daily Run existing source count is not numeric")
    if any(_cell(rows, start + len(expected) - 1, column) not in (None, "")
           for column in range(1, 7)):
        raise RuntimeError("Daily Run existing block has no blank separator")
    for name in ZERO_FALLBACK_METRICS:
        for offset, line in enumerate(expected):
            if line[0] == name:
                value = _cell(rows, start + offset, 2)
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise RuntimeError(f"Daily Run existing {name} is not numeric")
                break


def _cell_data(value) -> dict:
    if value in (None, ""):
        return {}
    if isinstance(value, bool):
        return {"userEnteredValue": {"boolValue": value}}
    if isinstance(value, (int, float)):
        return {"userEnteredValue": {"numberValue": value}}
    return {"userEnteredValue": {"stringValue": str(value)}}


def read_history(tracker: GoogleTracker) -> list[list]:
    return tracker.api.values().get(spreadsheetId=tracker.config.spreadsheet_id,
        range=_a1(DAILY_RUN_TAB, "A1:AT"), valueRenderOption="FORMULA").execute().get("values", [])


def preflight_history(tracker: GoogleTracker, fields: dict) -> tuple[dict, list[list], bool]:
    """Validate the destination and any existing retry before another tab writes."""
    props = [p for p in tracker._sheet_properties() if p.get("title") == DAILY_RUN_TAB]
    if len(props) != 1:
        raise RuntimeError("Daily Run tab was not found exactly once")
    sheet = props[0]
    if sheet.get("gridProperties", {}).get("columnCount", 0) < 6:
        raise RuntimeError("Daily Run needs columns A:F")
    protected = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
        fields="sheets(properties(sheetId),protectedRanges(range))").execute().get("sheets", [])
    if any(item.get("protectedRanges") for item in protected
           if item.get("properties", {}).get("sheetId") == sheet["sheetId"]):
        raise RuntimeError("Daily Run contains protected ranges; no rows inserted")
    before = read_history(tracker)
    existing = inspect_history(before, str(fields["Run ID"]))
    if existing:
        _verify_existing(before, fields)
    return sheet, before, existing


def write_history(tracker: GoogleTracker, fields: dict) -> tuple[int | None, int]:
    """Insert a complete new block; return (starting row, inserted height)."""
    sheet, before, existing = preflight_history(tracker, fields)
    if existing:
        return None, 0
    block = build_block(fields)
    if read_history(tracker) != before:
        raise RuntimeError("Daily Run changed before insertion")
    try:
        tracker.api.batchUpdate(spreadsheetId=tracker.config.spreadsheet_id, body={"requests": [
        {"insertDimension": {"range": {"sheetId": sheet["sheetId"], "dimension": "ROWS",
                                      "startIndex": FIRST_ROW - 1, "endIndex": FIRST_ROW - 1 + len(block)},
                             "inheritFromBefore": False}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet["sheetId"],
            "dimension": "ROWS", "startIndex": FIRST_ROW - 1,
            "endIndex": FIRST_ROW - 1 + len(block)},
            "properties": {"pixelSize": 21}, "fields": "pixelSize"}},
        {"updateCells": {"start": {"sheetId": sheet["sheetId"],
                                   "rowIndex": FIRST_ROW - 1, "columnIndex": 0},
                         "rows": [{"values": [_cell_data(value) for value in row]} for row in block],
                         "fields": "userEnteredValue"}}
        ]}).execute()
    except Exception:
        # A lost response can follow a committed insert. Never insert again until
        # the server state has been reread and the complete block verified.
        current = read_history(tracker)
        if not inspect_history(current, str(fields["Run ID"])):
            raise
        _verify_existing(current, fields)
        for offset, line in enumerate(block):
            for column, value in enumerate(line, 1):
                actual = _cell(current, FIRST_ROW + offset, column)
                if ("" if actual is None else actual) != ("" if value is None else value):
                    raise RuntimeError("Daily Run ambiguous write differs from intended report")
    after = read_history(tracker)
    for offset, expected in enumerate(block):
        for column, value in enumerate(expected, 1):
            if _cell(after, FIRST_ROW + offset, column) != value:
                raise RuntimeError("Daily Run inserted report failed cell readback")
    for old_row in range(FIRST_ROW, len(before) + 1):
        for column in range(1, len(before[old_row - 1]) + 1):
            if _cell(before, old_row, column) != _cell(after, old_row + len(block), column):
                raise RuntimeError("Daily Run history changed during insertion")
    return FIRST_ROW, len(block)
