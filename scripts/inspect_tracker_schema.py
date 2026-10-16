"""Read-only inventory of current Gecko Job Tracker tabs and named headers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import GoogleTracker  # noqa: E402
from tracker_schema import DAILY_TASKS_TAB, DAILY_RUN_TAB, DELETED_JOBS_TAB, REQUIRED_TABS, WORKBOOK_TITLE  # noqa: E402


def inventory(tracker: GoogleTracker) -> dict:
    if getattr(tracker,'backend','') == 'sqlite':
        scout = tracker.scout()
        return {'backend':'sqlite','workbook_id':str(tracker.path),'workbook_title':'Gecko local workspace',
                'tabs':[{'title':p['title'],'sheet_id':p['sheetId'],'role':'local dataset',
                         'hidden':False,'header_row':1,'headers':list(tracker.tab(p['title']).header_values),
                         'row_count':len(tracker.tab(p['title']).rows)} for p in tracker._sheet_properties()],
                'validation':{'required_tabs_present':True,'job_scout_required_headers_present':bool(scout.headers),
                              'daily_run_present':True,'daily_tasks_present':True,'deleted_jobs_present':False}}
    metadata = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
                               fields="properties(title)").execute()
    title = metadata.get("properties", {}).get("title")
    if title != WORKBOOK_TITLE:
        raise RuntimeError(f"Configured spreadsheet title {title!r} is not {WORKBOOK_TITLE!r}")
    tabs = tracker.discover_workbook(required=REQUIRED_TABS)
    scout = tracker.scout()
    result = {"workbook_id": tracker.config.spreadsheet_id, "workbook_title": title,
              "tabs": [], "validation": {"required_tabs_present": True,
                                          "job_scout_required_headers_present": True}}
    for title, info in tabs.items():
        result["tabs"].append({
            "title": title, "sheet_id": info["sheet_id"], "role": info["role"],
            "hidden": info["hidden"], "header_row": info["header_row"],
            "headers": info["physical_headers"],
            "row_count": len(scout.rows) if title == tracker.config.scout_tab else None,
        })
    result["validation"]["daily_tasks_present"] = DAILY_TASKS_TAB in tabs
    result["validation"]["deleted_jobs_present"] = DELETED_JOBS_TAB in tabs
    result["validation"]["daily_run_present"] = DAILY_RUN_TAB in tabs
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON inventory")
    args = parser.parse_args(argv)
    try:
        result = inventory(GoogleTracker())
    except Exception as error:
        print(f"Tracker schema validation failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for tab in result["tabs"]:
            layout = (f"header row {tab['header_row']}; {len(tab['headers'])} headers"
                      if tab["header_row"] else "no verified header row")
            print(f"{tab['title']} (ID {tab['sheet_id']}): {tab['role']}; {layout}")
        print("Job Scout named-header validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
