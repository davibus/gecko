"""Back up and clear only the three owned Gecko tracker data areas.

This intentionally does not run discovery, resume generation, or reporting.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "job-scout"))
from google_tracker import GoogleTracker, _a1, _col  # noqa: E402
from tracker_schema import SCOUT_TAB, DAILY_TASKS_TAB, DAILY_RUN_TAB  # noqa: E402

TARGETS = (DAILY_TASKS_TAB, DAILY_RUN_TAB, SCOUT_TAB)
FIRST_DATA_ROW = {DAILY_TASKS_TAB: 3, DAILY_RUN_TAB: 3, SCOUT_TAB: 2}
WIDTH = {DAILY_TASKS_TAB: 6, DAILY_RUN_TAB: 6, SCOUT_TAB: 20}


def nonempty(value):
    return value not in (None, "")


def occupied_end(rows):
    return max((i for i, row in enumerate(rows, 1) if any(map(nonempty, row))), default=0)


def planned_range(title, rows, headers):
    first = FIRST_DATA_ROW[title]
    last = occupied_end(rows)
    if title == SCOUT_TAB:
        if headers != ["ID", "Source", "Company", "Job Title", "Apply?", "Resume Created",
                       "Applied", "Cost", "Notes", "Apply or on Company Website (If Indeed)",
                       "Response", "Location", "Work Arrangement", "Employment Type",
                       "Salary", "Job URL", "Resume Link", "Date Posted", "Date Found", "Last Seen"]:
            raise RuntimeError("Job List headers changed or approval is not column E")
    elif title == DAILY_TASKS_TAB:
        if not rows or rows[0] != ["DAILY TASKS"]:
            raise RuntimeError("Daily Tasks instruction row changed")
        if any(nonempty(v) for v in (rows[1] if len(rows) > 1 else [])):
            raise RuntimeError("Daily Tasks row 2 contains instructions or unrelated content")
        if last >= first and rows[first - 1][0] != "GECKO DAILY TASKS REPORT":
            raise RuntimeError("Daily Tasks generated report boundary changed")
    elif title == DAILY_RUN_TAB:
        if any(any(nonempty(v) for v in row) for row in rows[:2]):
            raise RuntimeError("Daily Run rows 1:2 contain instructions or unrelated content")
        if last >= first and rows[first - 1][0] != "Daily Run":
            raise RuntimeError("Daily Run generated report boundary changed")
    for row_number, row in enumerate(rows, 1):
        if row_number >= first and any(nonempty(v) for v in row[WIDTH[title]:]):
            raise RuntimeError(f"{title} has unrelated content outside owned area at row {row_number}")
        if row_number >= first:
            for column, value in enumerate(row[:WIDTH[title]], 1):
                if isinstance(value, str) and value.startswith("="):
                    raise RuntimeError(f"Formula protects {title}!{_col(column)}{row_number}")
    return f"A{first}:{_col(WIDTH[title])}{last}" if last >= first else ""


def read_values(tracker, title, width):
    return tracker.api.values().get(spreadsheetId=tracker.config.spreadsheet_id,
        range=_a1(title, f"A1:{_col(width)}"), valueRenderOption="FORMULA").execute().get("values", [])


def metadata(tracker):
    return tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
        fields=("spreadsheetId,properties(title),sheets(properties,merges,"
                "basicFilter,conditionalFormats,protectedRanges)" )).execute()


def backup(tracker, title, info, rows, folder):
    end = max(1, occupied_end(rows))
    grid = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
        ranges=[_a1(title, f"A1:{_col(info['grid']['columnCount'])}{end}")],
        includeGridData=True,
        fields=("sheets(properties,merges,basicFilter,conditionalFormats,protectedRanges,"
                "data(rowData(values(userEnteredValue,userEnteredFormat,dataValidation,"
                "note,textFormatRuns)),rowMetadata(pixelSize),columnMetadata(pixelSize)))")
    ).execute()
    payload = {"title": title, "sheet_id": info["sheet_id"], "formula_values": rows,
               "grid_snapshot": grid, "captured_at": datetime.now(ZoneInfo("America/Denver")).isoformat()}
    path = folder / (title.lower().replace(" ", "-") + ".json")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"file": str(path), "sha256": digest, "bytes": path.stat().st_size}


def set_all_row_heights(tracker, tabs):
    requests = [{"updateDimensionProperties": {"range": {"sheetId": info["sheet_id"],
        "dimension": "ROWS", "startIndex": 0, "endIndex": info["grid"]["rowCount"]},
        "properties": {"pixelSize": 21}, "fields": "pixelSize"}}
        for info in tabs.values() if info["grid"]["rowCount"]]
    tracker.api.batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
                            body={"requests": requests}).execute()
    checked = {}
    for title, info in tabs.items():
        count = info["grid"]["rowCount"]
        check = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
            ranges=[_a1(title, f"A1:A{count}")], includeGridData=True,
            fields="sheets(properties(sheetId,title,gridProperties(rowCount)),data(rowMetadata(pixelSize)))"
        ).execute().get("sheets", [])
        if len(check) != 1 or check[0]["properties"]["sheetId"] != info["sheet_id"]:
            raise RuntimeError(f"Could not verify row metadata for {title}")
        sizes = [r.get("pixelSize") for block in check[0].get("data", [])
                 for r in block.get("rowMetadata", [])]
        if len(sizes) != count or any(size != 21 for size in sizes):
            raise RuntimeError(f"{title}: expected {count} rows at 21 pixels; got {len(sizes)} metadata rows")
        checked[title] = count
    return checked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", required=True)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args()
    tracker = GoogleTracker()
    tabs = tracker.discover_workbook(required=TARGETS)
    if set(TARGETS) - tabs.keys():
        raise RuntimeError("Required reset tab missing")
    before_metadata = metadata(tracker)
    if before_metadata.get("properties", {}).get("title") != "Gecko Job Tracker":
        raise RuntimeError("Configured workbook title is not Gecko Job Tracker")
    if args.resume:
        folder = args.resume
        manifest_path = folder / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["workbook_id"] != tracker.config.spreadsheet_id:
            raise RuntimeError("Resume manifest names a different workbook")
        plans, backups = manifest["ranges"], manifest["backups"]
        for item in backups.values():
            path = Path(item["file"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError(f"Backup changed: {path}")
        rows = {title: json.loads(Path(backups[title]["file"]).read_text(encoding="utf-8"))["formula_values"]
                for title in TARGETS}
    else:
        rows = {title: read_values(tracker, title, tabs[title]["grid"]["columnCount"])
                for title in TARGETS}
        plans = {title: planned_range(title, rows[title], tabs[title]["physical_headers"])
                 for title in TARGETS}
        folder = Path("reports/tracker-reset") / datetime.now(ZoneInfo("America/Denver")).strftime("%Y%m%dT%H%M%S")
        folder.mkdir(parents=True, exist_ok=False)
        backups = {title: backup(tracker, title, tabs[title], rows[title], folder)
                   for title in TARGETS}
        manifest = {"workbook_id": tracker.config.spreadsheet_id,
                    "metadata": before_metadata, "ranges": plans, "backups": backups,
                    "cleared": [], "row_heights_verified": {}}
        manifest_path = folder / "manifest.json"
    def save():
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    save()
    for title, area in plans.items():
        current = read_values(tracker, title, tabs[title]["grid"]["columnCount"])
        if tracker.discover_workbook()[title]["sheet_id"] != tabs[title]["sheet_id"]:
            raise RuntimeError(f"{title} changed after backup; no clear attempted for it")
        if title in manifest["cleared"]:
            continue
        first = FIRST_DATA_ROW[title]
        expected_prefix = rows[title][:first-1]
        prefix = current[:first-1] + [[] for _ in range(max(0, first-1-len(current)))]
        saved_prefix = expected_prefix + [[] for _ in range(max(0, first-1-len(expected_prefix)))]
        already_clear = prefix == saved_prefix and not any(
            any(nonempty(v) for v in row) for row in current[first-1:])
        if current != rows[title] and not already_clear:
            raise RuntimeError(f"{title} changed after backup; no clear attempted for it")
        if already_clear:
            manifest["cleared"].append(title)
            save()
            continue
        if area:
            tracker.api.values().clear(spreadsheetId=tracker.config.spreadsheet_id,
                                       range=_a1(title, area), body={}).execute()
            after = read_values(tracker, title, tabs[title]["grid"]["columnCount"])
            after_prefix = after[:first-1] + [[] for _ in range(max(0, first-1-len(after)))]
            if after_prefix != saved_prefix or any(
                any(nonempty(v) for v in row) for row in after[first-1:]):
                raise RuntimeError(f"{title} clear failed readback; backup is {backups[title]['file']}")
        manifest["cleared"].append(title)
        save()
    manifest["row_heights_verified"] = set_all_row_heights(tracker, tabs)
    save()
    print(json.dumps({"backup": str(folder), "ranges": plans,
                      "row_heights_verified": manifest["row_heights_verified"]}, indent=2))


if __name__ == "__main__":
    main()
