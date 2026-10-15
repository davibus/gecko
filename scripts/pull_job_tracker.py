"""Import a verified Google Job List snapshot into local Gecko state only.

The Sheet remains authoritative. All cells, custom headers, manual markers,
and formulas are retained in JSON and a separate SQLite mirror. Only existing
discovery jobs with matching ID and Source receive compatible field updates.
No resumes, applications, Sheet writes, or discovery operations run here.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "job-scout"))
from models import VALID_STATUSES
from tracker_schema import STATUS_LABELS

FIELDS = {
    "Company": "company", "Job Title": "title", "Location": "location",
    "Work Arrangement": "work_arrangement", "Employment Type": "employment_type",
    "Salary": "salary", "Job URL": "url", "Date Posted": "date_posted",
    "Date Found": "date_discovered", "Last Seen": "last_seen",
    "Apply or on Company Website (If Indeed)": "indeed_application_method",
}


def rows_from_snapshot(snapshot):
    if snapshot.get("sheet_title") != "Job List":
        raise ValueError("Snapshot must identify the Job List tab")
    values = snapshot["values"]
    formulas = snapshot["formula_values"]
    headers = values[0]
    if not headers or any(not str(h).strip() for h in headers):
        raise ValueError("Blank headers cannot be mapped")
    if len(headers) != len(set(str(h).strip().casefold() for h in headers)):
        raise ValueError("Duplicate headers cannot be mapped")
    if formulas[0] != headers or len(formulas) != len(values):
        raise ValueError("Value/formula snapshots have different structure")
    for required in ("ID", "Source", "Company", "Job Title", "Job URL"):
        if required not in headers:
            raise ValueError(f"Missing required header: {required}")
    records = []
    seen = set()
    for physical_row, cells in enumerate(values[1:], 2):
        record = {h: cells[i] if i < len(cells) and cells[i] is not None else ""
                  for i, h in enumerate(headers)}
        if not str(record["ID"]).strip():
            continue
        raw_id = record["ID"]
        job_id = int(str(raw_id))
        if job_id <= 0 or job_id in seen:
            raise ValueError(f"Invalid/duplicate ID {raw_id!r} at row {physical_row}")
        seen.add(job_id)
        records.append((job_id, physical_row, record, formulas[physical_row - 1]))
    return records


def plan(connection, records):
    updates, conflicts, unmatched = [], [], []
    connection.row_factory = sqlite3.Row
    statuses = {v.casefold(): k for k, v in STATUS_LABELS.items()}
    for job_id, physical_row, record, _ in records:
        old = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if old is None:
            unmatched.append(job_id)
            continue
        if str(old["source"]).strip().casefold() != str(record["Source"]).strip().casefold():
            conflicts.append({"id": job_id, "row": physical_row, "reason": "Source differs"})
            continue
        changes = {}
        for header, column in FIELDS.items():
            if header not in record:
                continue
            if column == "indeed_application_method" and str(record["Source"]).casefold() != "indeed":
                continue
            value = str(record[header])
            if value != str(old[column] or ""):
                changes[column] = value
        if "url" in changes:
            changes["canonical_url"] = changes["url"]
        raw_status = str(record.get("Gecko Status", "")).strip()
        status = statuses.get(raw_status.casefold(), raw_status.casefold())
        if status in VALID_STATUSES and status != old["status"]:
            changes["status"] = status
        if changes:
            updates.append((job_id, changes))
    return updates, conflicts, unmatched


def import_snapshot(snapshot_path, db_path, *, apply=False):
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    records = rows_from_snapshot(snapshot)
    if not db_path.is_file():
        raise ValueError("Existing discovery database is required")
    uri = db_path.resolve().as_uri() + ("?mode=rw" if apply else "?mode=ro")
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as connection:
        updates, conflicts, unmatched = plan(connection, records)
        summary = {"snapshot": str(snapshot_path.resolve()), "sheet_jobs": len(records),
                   "discovery_jobs_changed": len(updates), "source_conflicts": conflicts,
                   "sheet_only_ids": unmatched, "applied": False}
        if not apply:
            return summary
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = snapshot_path.parent / ("jobs-before-pull-" + stamp + ".sqlite3")
        with closing(sqlite3.connect(backup)) as destination:
            connection.backup(destination)
        connection.execute("BEGIN IMMEDIATE")
        # Replan under the write lock in case another local job changed.
        updates, conflicts, unmatched = plan(connection, records)
        # Preserve conflicting discovery identities, but mirror their Sheet
        # records exactly alongside the other current rows.
        connection.execute("CREATE TABLE IF NOT EXISTS google_tracker_rows ("
                           "spreadsheet_id TEXT, sheet_id INTEGER, job_id INTEGER, "
                           "physical_row INTEGER, cells_json TEXT NOT NULL, "
                           "formulas_json TEXT NOT NULL, fetched_at_utc TEXT, "
                           "PRIMARY KEY(spreadsheet_id,sheet_id,job_id))")
        connection.execute("DELETE FROM google_tracker_rows WHERE spreadsheet_id=? AND sheet_id=?",
                           (snapshot["spreadsheet_id"], snapshot["sheet_id"]))
        for job_id, row_number, record, formulas in records:
            connection.execute("INSERT INTO google_tracker_rows VALUES (?,?,?,?,?,?,?)",
                (snapshot["spreadsheet_id"], snapshot["sheet_id"], job_id, row_number,
                 json.dumps(record, ensure_ascii=False), json.dumps(formulas, ensure_ascii=False),
                 snapshot["fetched_at_utc"]))
        for job_id, changes in updates:
            assignments = ", ".join(f"{column}=?" for column in changes)
            connection.execute(f"UPDATE jobs SET {assignments} WHERE id=?",
                               (*changes.values(), job_id))
            actual = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if any(actual[column] != value for column, value in changes.items()):
                raise RuntimeError(f"Discovery record readback failed for ID {job_id}")
        mirrored = connection.execute("SELECT job_id,cells_json,formulas_json FROM google_tracker_rows "
            "WHERE spreadsheet_id=? AND sheet_id=?", (snapshot["spreadsheet_id"], snapshot["sheet_id"])).fetchall()
        expected = {job_id: (record, formulas) for job_id, _, record, formulas in records}
        if {r[0]: (json.loads(r[1]), json.loads(r[2])) for r in mirrored} != expected:
            raise RuntimeError("Full-cell mirror readback failed")
        connection.commit()
        summary.update(applied=True, verified=True, database_backup=str(backup.resolve()),
                       discovery_jobs_changed=len(updates), source_conflicts=conflicts,
                       sheet_only_ids=unmatched,
                       snapshot_sha256=hashlib.sha256(snapshot_path.read_bytes()).hexdigest())
    report = snapshot_path.parent / ("pull-result-" + stamp + ".json")
    report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=ROOT / "job-scout/data/jobs.sqlite3")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(import_snapshot(args.snapshot, args.db, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
