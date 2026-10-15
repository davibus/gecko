"""Undo this run's completions based on insufficient archived job descriptions."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "job-scout"), str(ROOT / "scripts")]

from description_retrieval import description_is_sufficient
from generate_apply_queue import _archived_description
from google_tracker import GoogleTracker, _a1, _col, verified_resume_uri_target
import resume_naming

CUTOFF = datetime(2026, 10, 11, 18, 44).timestamp()
REPORT = ROOT / "reports" / "insufficient-description-repair.json"
FORMULA = re.compile(r'^=HYPERLINK\("((?:[^"]|"")*)","((?:[^"]|"")*)"\)$', re.I)


def target(raw: str) -> str:
    match = FORMULA.fullmatch(raw)
    return match.group(1).replace('""', '"') if match else raw


def main() -> int:
    tracker = GoogleTracker()
    tab = tracker.scout(value_render_option="FORMULA")
    if tab.title != "Job List":
        raise RuntimeError("Unexpected ledger tab")
    targets = []
    for row, data in tab.rows:
        if (str(data.get("Apply?") or "").strip().casefold() != "yes"
                or str(data.get("Resume Created") or "").strip().casefold() != "x"):
            continue
        raw = str(data.get("Resume Link") or "").strip()
        try:
            uri = verified_resume_uri_target(target(raw))
            path = Path(unquote(urlsplit(uri).path.lstrip("/")))
        except (ValueError, OSError):
            continue
        if path.stat().st_ctime < CUTOFF:
            continue
        number = resume_naming.job_number(path)
        archives = list((ROOT / "input/job-descriptions").glob(f"*+{number}.md"))
        if len(archives) != 1:
            continue
        description = _archived_description(archives[0].read_text(
            encoding="utf-8-sig", errors="replace"))
        if description_is_sufficient(description):
            continue
        targets.append({"row": row, "id": str(data["Scout ID"]),
                        "company": str(data["Company"]), "title": str(data["Job Title"]),
                        "old_marker": str(data["Resume Created"]), "old_link": raw,
                        "uri": uri, "file": str(path), "archive": str(archives[0]),
                        "description_chars": len(description),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        "old_notes": str(data.get("Notes") or "")})
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({"status": "planned", "rows": targets}, indent=2), encoding="utf-8")
    if not targets:
        print("No task-created thin-description completions found")
        return 0
    proposed = {}
    notes = {}
    for item in targets:
        row = item["row"]
        prior = item["old_notes"].rstrip()
        message = "Resume not created: Full job description unavailable or insufficient; prior draft preserved in scratch."
        updated = f"{prior}\n{message}" if prior else message
        notes[row] = updated
        proposed[(row, "Resume Created")] = ""
        proposed[(row, "Resume Link")] = ""
        proposed[(row, "Notes")] = updated
    entries, expected = tracker._prepare_writes(tab, proposed)
    for item in targets:
        row = item["row"]
        if (row, "Resume Created") not in expected or (row, "Notes") not in expected:
            raise RuntimeError(f"Protected completion or Notes cell at row {row}; no batch sent")
        if (row, "Resume Link") not in expected:
            if not FORMULA.fullmatch(item["old_link"]):
                raise RuntimeError(f"Protected Resume Link at row {row}; no batch sent")
            # The only exception is a formula created by this run, proven to
            # point to this task-created file and saved in the prewrite audit.
            col = tab.headers["Resume Link"]
            entries.append({"range": _a1(tab.title, f"{_col(col)}{row}"),
                            "values": [[""]]})
    tracker.api.values().batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
                                     body={"valueInputOption": "RAW", "data": entries}).execute()
    verified = tracker.scout(value_render_option="FORMULA")
    current = dict(verified.rows)
    for item in targets:
        row = item["row"]
        data = current.get(row, {})
        if (str(data.get("Scout ID") or "") != item["id"]
                or str(data.get("Company") or "") != item["company"]
                or str(data.get("Job Title") or "") != item["title"]
                or str(data.get("Resume Created") or "")
                or str(data.get("Resume Link") or "")
                or str(data.get("Notes") or "") != notes[row]):
            raise RuntimeError(f"Repair readback failed at row {row}")
    referenced = set()
    for _, data in verified.rows:
        try:
            referenced.add(verified_resume_uri_target(target(str(data.get("Resume Link") or ""))))
        except (ValueError, OSError):
            pass
    for item in targets:
        path = Path(item["file"])
        if item["uri"] in referenced:
            item["archive_result"] = "Still referenced by another row; file preserved in output"
            continue
        company = path.name.split("+", 2)[1]
        number = resume_naming.job_number(path)
        destination = ROOT / "scratch" / f"{company}+{number}" / "insufficient-description" / path.name
        if destination.exists():
            item["archive_result"] = "Destination exists; file preserved in output"
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        path.replace(destination)
        item["archive_result"] = str(destination)
    REPORT.write_text(json.dumps({"status": "verified", "rows": targets}, indent=2), encoding="utf-8")
    print(json.dumps({"repaired_rows": [item["row"] for item in targets],
                      "report": str(REPORT)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
