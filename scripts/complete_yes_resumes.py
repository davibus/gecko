"""Complete live Apply?=Yes resumes and give verified local links job-specific labels."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
sys.path.insert(0, str(ROOT / "scripts"))

from google_tracker import GoogleTracker, _a1, _col, verified_resume_file_uri, verified_resume_uri_target
from storage import DEFAULT_DB
from generate_apply_queue import run_queue, record_success, recover_existing, generate


def label_link(tracker: GoogleTracker, scout_id: int, resume: Path) -> bool:
    """Replace an owned raw URI with a formula, verifying its actual hyperlink target."""
    uri = verified_resume_file_uri(resume)
    tab = tracker.scout(value_render_option="FORMULA")
    matches = [(row, data) for row, data in tab.rows
               if str(data.get("Scout ID") or "").strip() == str(scout_id)]
    if len(matches) != 1:
        raise RuntimeError(f"Scout ID {scout_id} is missing or ambiguous")
    row, data = matches[0]
    if str(data.get("Apply?") or "").strip().casefold() != "yes":
        raise RuntimeError(f"Scout ID {scout_id} is no longer approved")
    if str(data.get("Resume Created") or "").strip().casefold() != "x":
        raise RuntimeError(f"Scout ID {scout_id} lacks the X completion marker")
    label = f"{data['Company']} + {data['Job Title']}"
    formula = '=HYPERLINK("{}","{}")'.format(uri.replace('"', '""'), label.replace('"', '""'))
    old = str(data.get("Resume Link") or "").strip()
    if old == formula:
        return False
    if old.startswith("="):
        raise RuntimeError(f"Formula-protected Resume Link at row {row}")
    if old and verified_resume_uri_target(old) != uri:
        raise RuntimeError(f"Resume Link at row {row} points to a different file")
    entries, expected = tracker._prepare_writes(tab, {(row, "Resume Link"): formula})
    if (row, "Resume Link") not in expected:
        raise RuntimeError(f"Formula or ARRAYFORMULA protection blocked Resume Link at row {row}")
    tracker.api.values().batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
                                     body={"valueInputOption": "USER_ENTERED", "data": entries}).execute()
    col = tab.headers["Resume Link"]
    cell = _a1(tab.title, f"{_col(col)}{row}")
    actual = tracker.api.values().get(spreadsheetId=tracker.config.spreadsheet_id,
                                      range=cell, valueRenderOption="FORMULA").execute().get("values", [[]])
    shown = tracker.api.values().get(spreadsheetId=tracker.config.spreadsheet_id,
                                     range=cell, valueRenderOption="UNFORMATTED_VALUE").execute().get("values", [[]])
    grid = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
                           ranges=[cell], includeGridData=True,
                           fields="sheets(data(rowData(values(hyperlink))))").execute()
    target = grid["sheets"][0]["data"][0]["rowData"][0]["values"][0].get("hyperlink")
    verified = tracker.scout()
    rebound = dict(verified.rows).get(row, {})
    if (actual[0][0] != formula or shown[0][0] != label or target != uri
            or str(rebound.get("Scout ID") or "").strip() != str(scout_id)
            or str(rebound.get("Resume Created") or "").strip().casefold() != "x"):
        if old:
            tracker.api.values().update(spreadsheetId=tracker.config.spreadsheet_id,
                                        range=cell, valueInputOption="RAW",
                                        body={"values": [[old]]}).execute()
        raise RuntimeError(f"Resume hyperlink readback failed at row {row}")
    return True


def main() -> int:
    sys.stdout.reconfigure(errors="backslashreplace")
    sys.stderr.reconfigure(errors="backslashreplace")
    tracker = GoogleTracker()
    title = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
                            fields="properties(title)").execute()["properties"]["title"]
    if title != "Gecko Job Tracker":
        raise RuntimeError(f"Unexpected workbook title: {title!r}")
    tracker.discover_workbook(required=("Job List", "Rejected Jobs"))
    initial = tracker.scout()
    yes = [(row, data) for row, data in initial.rows
           if str(data.get("Apply?") or "").strip().casefold() == "yes"]
    ids = [int(data["Scout ID"]) for _, data in yes]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Apply?=Yes rows have a missing or duplicate stable ID")
    print(f"Live Apply?=Yes rows: {len(yes)}", flush=True)
    labeled = []
    label_failures = []

    def recorder(item, artifacts, service):
        record_success(item, artifacts, service)

    def paced_generator(item, db):
        # A row uses multiple live safety/readback requests. The service account
        # is limited to 60 reads per minute; pace all outcomes before work starts.
        time.sleep(10)
        return generate(item, db, tracker=tracker)

    result = run_queue(tracker, DEFAULT_DB.resolve(), eligible_scout_ids=set(ids),
                       recorder=recorder, generator=paced_generator, logger=None)
    for item in result.snapshot.already_created:
        if item.scout_id is None or str((item.fields or {}).get("Apply?") or "").strip().casefold() != "yes":
            continue
        try:
            old = str((item.fields or {}).get("Resume Link") or "").strip()
            if old.startswith("file:///"):
                path = Path(unquote(urlsplit(old).path.lstrip("/")))
                if verified_resume_file_uri(path) != verified_resume_uri_target(old):
                    raise RuntimeError("Existing link target does not match its file")
            else:
                path = recover_existing(item, DEFAULT_DB.resolve()).resume
        except Exception as error:
            label_failures.append((item.scout_id, str(error)))
            print(f"EXISTING LINK BLOCKER ID {item.scout_id}: {error}", flush=True)
    verified_files = {item.scout_id: artifacts.resume for item, artifacts in result.successes}
    for item in result.snapshot.already_created:
        if item.scout_id is None or any(item.scout_id == failed[0] for failed in label_failures):
            continue
        old = str((item.fields or {}).get("Resume Link") or "").strip()
        if old.startswith("file:///"):
            verified_files[item.scout_id] = Path(unquote(urlsplit(old).path.lstrip("/")))
    # Include earlier successful rows when resuming an interrupted run.
    final_tab = tracker.scout(value_render_option="FORMULA")
    proposals = {}
    identity = {}
    for row, data in final_tab.rows:
        if str(data.get("Apply?") or "").strip().casefold() != "yes":
            continue
        if str(data.get("Resume Created") or "").strip().casefold() != "x":
            continue
        scout_id = int(data["Scout ID"])
        old = str(data.get("Resume Link") or "").strip()
        if old.startswith("="):
            continue
        try:
            path = verified_files.get(scout_id)
            if path is None and old.startswith("file:///"):
                path = Path(unquote(urlsplit(old).path.lstrip("/")))
            if path is None:
                raise RuntimeError("No exact existing resume file found")
            uri = verified_resume_file_uri(path)
            if old and verified_resume_uri_target(old) != uri:
                raise RuntimeError("Existing link points to a different file")
            label = f"{data['Company']} + {data['Job Title']}"
            formula = '=HYPERLINK("{}","{}")'.format(uri.replace('"', '""'), label.replace('"', '""'))
            proposals[(row, "Resume Link")] = formula
            identity[row] = (scout_id, label, uri)
        except Exception as error:
            label_failures.append((scout_id, str(error)))
    if proposals:
        entries, expected = tracker._prepare_writes(final_tab, proposals)
        for (row, _), formula in proposals.items():
            if (row, "Resume Link") not in expected:
                label_failures.append((identity[row][0], "Formula protection blocked Resume Link"))
        if entries:
            tracker.api.values().batchUpdate(spreadsheetId=tracker.config.spreadsheet_id,
                body={"valueInputOption": "USER_ENTERED", "data": entries}).execute()
            readback = tracker.scout(value_render_option="FORMULA")
            shown = tracker.scout()
            formula_rows = dict(readback.rows)
            shown_rows = dict(shown.rows)
            col = readback.headers["Resume Link"]
            grid = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id,
                ranges=[_a1(readback.title, f"{_col(col)}2:{_col(col)}{max(identity)}")],
                includeGridData=True,
                fields="sheets(data(startRow,rowData(values(hyperlink))))").execute()
            hyperlinks = {}
            for sheet in grid.get("sheets", []):
                for block in sheet.get("data", []):
                    for offset, row_data in enumerate(block.get("rowData", [])):
                        values = row_data.get("values", [])
                        if values:
                            hyperlinks[block["startRow"] + offset + 1] = values[0].get("hyperlink")
            for (row, _), formula in expected.items():
                scout_id, label, uri = identity[row]
                if (formula_rows.get(row, {}).get("Resume Link") == formula
                        and shown_rows.get(row, {}).get("Resume Link") == label
                        and hyperlinks.get(row) == uri
                        and str(shown_rows.get(row, {}).get("Resume Created") or "").strip().casefold() == "x"):
                    labeled.append(scout_id)
                else:
                    label_failures.append((scout_id, "Formula/display/target readback failed"))
    summary = {"yes_rows": len(yes), "created": result.created,
               "reused": result.recovered, "links_labeled": len(labeled),
               "labeled_ids": labeled,
               "failures": [{"id": failure.item.scout_id, "row": failure.item.row,
                             "reason": failure.reason} for failure in result.failures],
               "label_failures": label_failures,
               "remaining": len(result.unexpected)}
    report = ROOT / "reports" / "apply-yes-resumes.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return 1 if result.exit_code or label_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
