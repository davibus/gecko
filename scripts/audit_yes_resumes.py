"""Read-only final audit of every live Apply?=Yes Job List row."""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))

from google_tracker import GoogleTracker, _a1, _col, verified_resume_uri_target
from normalize import canonicalize_url
from sources.indeed import extract_indeed_job_key

LINK = re.compile(r'^=HYPERLINK\("((?:[^"]|"")*)","((?:[^"]|"")*)"\)$', re.I)


def main() -> int:
    tracker = GoogleTracker()
    title = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
                            fields="properties(title)").execute()["properties"]["title"]
    if title != "Gecko Job Tracker":
        raise RuntimeError(f"Wrong workbook: {title!r}")
    formulas = tracker.scout(value_render_option="FORMULA")
    displayed = tracker.scout()
    if formulas.sheet_id != displayed.sheet_id or formulas.headers != displayed.headers:
        raise RuntimeError("Job List schema changed during audit")
    yes = [(row, data) for row, data in formulas.rows
           if str(data.get("Apply?") or "").strip().casefold() == "yes"]
    column = formulas.headers["Resume Link"]
    grid = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
        ranges=[_a1(formulas.title, f"{_col(column)}2:{_col(column)}{max(row for row, _ in yes)}")],
        includeGridData=True,
        fields="sheets(data(startRow,rowData(values(hyperlink))))").execute()
    hyperlinks = {}
    for sheet in grid.get("sheets", []):
        for block in sheet.get("data", []):
            for offset, row_data in enumerate(block.get("rowData", [])):
                cells = row_data.get("values", [])
                if cells:
                    hyperlinks[block["startRow"] + offset + 1] = cells[0].get("hyperlink")
    effective = dict(displayed.rows)
    rejected = tracker.rejected_jobs_index()
    seen = set()
    outcomes = []
    for row, data in yes:
        live = effective.get(row, {})
        source = str(data.get("Source") or "")
        url = str(data.get("Job URL") or "")
        job_id = extract_indeed_job_key(url) if source.casefold() == "indeed" else ""
        entry = {"row": row, "id": data.get("Scout ID"), "company": data.get("Company"),
                 "title": data.get("Job Title"), "outcome": "pending", "reason": ""}
        identity = (source.casefold(), canonicalize_url(url))
        if str(live.get("Cost") or "").strip().casefold() == "x":
            entry.update(outcome="skipped", reason="Cost = x")
        elif str(data.get("Applied") or "").strip():
            entry.update(outcome="skipped", reason="Already applied")
        elif str(data.get("Apply or on Company Website (If Indeed)") or "").strip().casefold() in (
                "expired", "this job has expired on indeed"):
            entry.update(outcome="skipped", reason="Expired Indeed posting")
        elif rejected.match(source=source, job_id=job_id, url=url):
            entry.update(outcome="skipped", reason="Permanent rejection history")
        elif identity in seen and identity[1]:
            entry.update(outcome="skipped", reason="Duplicate source and canonical URL")
        else:
            seen.add(identity)
            marker = str(data.get("Resume Created") or "").strip().casefold()
            raw = str(data.get("Resume Link") or "").strip()
            match = LINK.fullmatch(raw)
            if marker == "x" and match:
                uri = match.group(1).replace('""', '"')
                label = match.group(2).replace('""', '"')
                desired_label = f"{data['Company']} + {data['Job Title']}"
                try:
                    normalized = verified_resume_uri_target(uri)
                    path = Path(unquote(urlsplit(normalized).path.lstrip("/")))
                    with zipfile.ZipFile(path) as docx:
                        if "word/document.xml" not in docx.namelist():
                            raise ValueError("DOCX has no Word document")
                    if (label == desired_label and str(live.get("Resume Link") or "") == label
                            and hyperlinks.get(row) == normalized):
                        entry.update(outcome="verified", reason="X, two-part display label, exact file hyperlink, usable DOCX")
                        entry["resume"] = str(path)
                    else:
                        entry.update(outcome="blocker", reason="Display label or hyperlink target failed readback")
                except Exception as error:
                    entry.update(outcome="blocker", reason=f"Resume file or URI invalid: {error}")
            elif marker == "x":
                entry.update(outcome="blocker", reason="X marker lacks verified company/title file hyperlink")
            elif raw:
                entry.update(outcome="blocker", reason="Resume Link exists without X marker")
            else:
                note = str(data.get("Notes") or "")
                reason = next((line for line in note.splitlines()
                               if line.casefold().startswith("resume not created:")), "")
                entry.update(outcome="blocker" if reason else "pending",
                             reason=reason or "No completed resume recorded")
        outcomes.append(entry)
    report = {"workbook": title, "tab": formulas.title, "yes_rows": len(yes),
              "counts": dict(Counter(item["outcome"] for item in outcomes)),
              "rows": outcomes}
    destination = ROOT / "reports" / "apply-yes-resumes-audit.json"
    destination.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
    return 0 if report["counts"].get("blocker", 0) == report["counts"].get("pending", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
