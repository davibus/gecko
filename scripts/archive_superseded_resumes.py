"""Preserve unused older versions of completed Yes-row resumes in scratch."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from google_tracker import GoogleTracker, _a1, _col, verified_resume_uri_target
import resume_naming

LINK = re.compile(r'^=HYPERLINK\("((?:[^"]|"")*)","((?:[^"]|"")*)"\)$', re.I)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    tracker = GoogleTracker()
    tab = tracker.scout(value_render_option="FORMULA")
    col = tab.headers["Resume Link"]
    last = max(row for row, _ in tab.rows)
    grid = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
        ranges=[_a1(tab.title, f"{_col(col)}2:{_col(col)}{last}")],
        includeGridData=True,
        fields="sheets(data(startRow,rowData(values(hyperlink))))").execute()
    grid_links = {}
    for sheet in grid.get("sheets", []):
        for block in sheet.get("data", []):
            for offset, row_data in enumerate(block.get("rowData", [])):
                cells = row_data.get("values", [])
                if cells and cells[0].get("hyperlink"):
                    grid_links[block["startRow"] + offset + 1] = cells[0]["hyperlink"]
    all_linked = set()
    owned = []
    for row, data in tab.rows:
        raw = str(data.get("Resume Link") or "").strip()
        match = LINK.fullmatch(raw)
        candidate = match.group(1).replace('""', '"') if match else raw
        candidate = grid_links.get(row) or candidate
        try:
            uri = verified_resume_uri_target(candidate)
            path = Path(unquote(urlsplit(uri).path.lstrip("/"))).resolve()
        except (ValueError, OSError):
            continue
        all_linked.add(path)
        if (str(data.get("Apply?") or "").strip().casefold() == "yes"
                and str(data.get("Resume Created") or "").strip().casefold() == "x"):
            owned.append((row, data, path))
    plans = []
    for row, data, final in owned:
        parts = final.stem.split("+")
        if len(parts) < 4 or parts[0] != "Dave-Call":
            continue
        company, number = parts[1], resume_naming.job_number(final)
        for path in (ROOT / "output/resumes").glob("*.docx"):
            if (path.resolve() in all_linked or not path.name.startswith(f"Dave-Call+{company}+")
                    or resume_naming.job_number(path) != number):
                continue
            destination = ROOT / "scratch" / f"{company}+{number}" / "superseded" / path.name
            if destination.exists() or any(item["source"] == str(path) for item in plans):
                continue
            plans.append({"row": row, "id": data.get("Scout ID"),
                          "source": str(path), "destination": str(destination),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    report = ROOT / "reports" / "superseded-resume-archive.json"
    summary = {"time": datetime.now(timezone.utc).isoformat(),
               "status": "planned", "files": plans}
    report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if args.apply:
        for item in plans:
            source = Path(item["source"]).resolve()
            destination = Path(item["destination"]).resolve()
            if source.parent != (ROOT / "output/resumes").resolve() or not destination.is_relative_to(
                    (ROOT / "scratch").resolve()):
                raise RuntimeError("Superseded file path escaped the Gecko workspace")
            if source in all_linked or destination.exists():
                raise RuntimeError("Superseded file changed before move")
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)
            if not destination.is_file() or hashlib.sha256(destination.read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError(f"Superseded file copy verification failed: {destination}")
        summary["status"] = "verified"
        report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "files": len(plans),
                      "report": str(report)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
