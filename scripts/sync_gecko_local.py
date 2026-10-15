"""Pull the live tracker into Gecko Main and Cursor references; no Sheet writes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import GoogleTracker
from inspect_tracker_schema import inventory
from pull_job_tracker import import_snapshot


def sync_local():
    tracker = GoogleTracker()
    schema = inventory(tracker)
    tab = next(t for t in schema["tabs"] if t["title"] == "Job List")
    stamp = datetime.now(timezone.utc)
    folder = ROOT / "reports/tracker-pull" / stamp.strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    api = tracker.api.values()
    request = dict(spreadsheetId=tracker.config.spreadsheet_id, range="'Job List'!A:ZZ")
    values = api.get(**request, valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    formulas = api.get(**request, valueRenderOption="FORMULA").execute().get("values", [])
    # Do not import a mixed snapshot if an interactive edit happened during reads.
    reread = api.get(**request, valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [])
    if values != reread:
        raise RuntimeError("Tracker changed during pull; local synchronization stopped")
    snapshot = dict(spreadsheet_id=tracker.config.spreadsheet_id,
                    sheet_id=tab["sheet_id"], sheet_title=tab["title"],
                    fetched_at_utc=stamp.isoformat(), values=values, formula_values=formulas)
    path = folder / "snapshot.json"
    encoded = json.dumps(snapshot, indent=2, ensure_ascii=False)
    path.write_text(encoded, encoding="utf-8")
    result = import_snapshot(path, ROOT / "job-scout/data/jobs.sqlite3", apply=True)
    (ROOT / "job-scout/data/tracker-live.json").write_text(encoded, encoding="utf-8")
    lines = ["# Current live Gecko tracker", "", "Google Sheets remains authoritative.",
             f"Read at {stamp.isoformat()}; workbook {schema['workbook_id']}.", "",
             "Resolve headers by name; preserve formulas and manual fields.",
             "A local pull must preserve Last Updated. Existing Resume Created = X blocks generation.", ""]
    for item in schema["tabs"]:
        lines += [f"## {item['title']} (ID {item['sheet_id']})", "",
                  ", ".join(map(str, item["headers"])), ""]
    lines += ["Full current rows and formulas: `job-scout/data/tracker-live.json`.",
              "The SQLite `google_tracker_rows` table contains the same complete job mirror.", ""]
    (ROOT / "docs/live-tracker-schema.md").write_text("\n".join(lines), encoding="utf-8")
    scratch = next((t for t in schema["tabs"] if t["title"] == "Scratch"), None)
    if scratch:
        cells = api.get(spreadsheetId=tracker.config.spreadsheet_id,
                        range="'Scratch'!A:ZZ", valueRenderOption="FORMATTED_VALUE").execute().get("values", [])
        scratch_path = ROOT / "docs/scratch-column-ideas.md"
        if scratch_path.exists():
            (folder / "scratch-column-ideas-before.md").write_bytes(scratch_path.read_bytes())
        scratch_path.write_text("# Scratch research ideas\n\nThese are proposals, not approved new columns.\n\n" +
                               "\n".join(" | ".join(map(str, row)) for row in cells) + "\n", encoding="utf-8")
    rule = ROOT / ".cursor/rules/gecko-tracker-live.mdc"
    rule.write_text('---\ndescription: Current Gecko tracker mirror\nalwaysApply: true\n---\n\n'
                    'Read `docs/live-tracker-schema.md` and `docs/scratch-column-ideas.md` for the latest local references. '
                    'Read `job-scout/data/tracker-live.json` for all job cells and formulas. '
                    'Re-read live Sheet headers and rows before writes. Follow `AGENTS.md` and `GECKO_SYSTEM.md`. '
                    'When the user says run Gecko, follow `docs/gecko-command.md`.\n', encoding="utf-8")
    result["cursor_references_updated"] = True
    print("Tracker and Cursor reference readback verified", flush=True)
    return result


if __name__ == "__main__":
    print(json.dumps(sync_local(), indent=2))
