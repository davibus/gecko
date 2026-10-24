"""Google Sheet primary ledger with a durable local working copy.

Cell-level three-way reconciliation preserves edits on either side. Concurrent
edits to the same cell stop reconciliation instead of choosing a winner.
The local database also retains descriptions, attachments and application drafts.
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from tracker_backend import CONFIG, DATABASE, ROOT

STATE = ROOT / "reports/sheets-primary-cutover/sync-state.json"
STATUS = ROOT / "reports/sheets-primary-cutover/sync-status.json"


def enabled():
    return CONFIG.exists() and json.loads(CONFIG.read_text(encoding="utf-8")).get("authority") == "google_sheets"


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def text(value):
    return "" if value is None else str(value)


def ensure_frozen_headers(remote):
    """Keep row 1 visible on every tracker tab; preserve larger frozen regions."""
    properties = remote._sheet_properties()
    requests = [{"updateSheetProperties": {
        "properties": {"sheetId": p["sheetId"], "gridProperties": {"frozenRowCount": 1}},
        "fields": "gridProperties.frozenRowCount",
    }} for p in properties if p.get("gridProperties", {}).get("frozenRowCount", 0) < 1]
    if requests:
        remote.api.batchUpdate(spreadsheetId=remote.config.spreadsheet_id,
                               body={"requests": requests}).execute()
        if any(p.get("gridProperties", {}).get("frozenRowCount", 0) < 1
               for p in remote._sheet_properties()):
            raise RuntimeError("Could not verify that row 1 stays frozen.")


def sync_headers(remote, local):
    """Keep the Sheet's physical order, ignoring only trailing empty headings."""
    headers = list(remote)
    while headers and not text(headers[-1]).strip():
        headers.pop()
    if any(not text(h).strip() for h in headers):
        raise ValueError("Name each column between populated headers before synchronization.")
    return headers + [h for h in local if text(h).strip() and h not in headers]


def index_rows(rows):
    result = {}
    for row, data in rows:
        key = text(data.get("ID", data.get("Scout ID", ""))).strip()
        if not key and not any(data.get(h) for h in ("Company", "Job Title", "Job URL", "Source")):
            continue  # Preserve old note-only/formatting rows in place.
        if not key.isdigit() or int(key) <= 0 or key in result:
            raise ValueError(f"Job List row {row} needs a unique positive ID before synchronization.")
        result[key] = (row, data)
    return result


def merge_rows(base, local, remote, headers):
    """Never delete a job implicitly; removals require explicit reconciliation."""
    merged, conflicts = {}, []
    for key in sorted(local.keys() | remote.keys(), key=int):
        left, right, previous = local.get(key), remote.get(key), base.get(key)
        if left is None or right is None:
            if previous is not None:
                conflicts.append({"id": key, "field": "row", "reason": "Job removed on one side; preserved for review."})
            else:
                merged[key] = dict(left if left is not None else right)
            continue
        result = {}
        for field in headers:
            a, b, old = left.get(field, ""), right.get(field, ""), (previous or {}).get(field, "")
            if text(a) == text(b):
                result[field] = b
            elif text(a) == text(old):
                result[field] = b
            elif text(b) == text(old):
                result[field] = a
            else:
                conflicts.append({"id": key, "field": field, "local": a, "sheet": b, "previous": old})
        merged[key] = result
    if conflicts:
        raise SyncConflict(conflicts)
    return merged


class SyncConflict(ValueError):
    def __init__(self, conflicts):
        self.conflicts = conflicts
        super().__init__(f"{len(conflicts)} tracker conflicts need review. Both versions are preserved; no cells were overwritten.")


def sync(*, bootstrap=None):
    """Caller holds run_lock: one writer across dashboard, discovery and sync."""
    from google_tracker import GoogleTracker, Config, _col, load_environment
    load_environment()
    # Drain durable Firecrawl jobs/reports before reading the shared Sheet. This
    # runs on existing idle retries too and never calls a paid discovery API.
    from firecrawl_discovery import flush_pending
    flush_pending()
    remote = GoogleTracker(config=Config.from_environment())
    initial = bootstrap is not None
    state = bootstrap if initial else json.loads(STATE.read_text(encoding="utf-8"))
    if state["spreadsheet_id"] != remote.config.spreadsheet_id:
        raise ValueError("The configured Google spreadsheet changed; synchronization stopped.")
    ensure_frozen_headers(remote)
    sheet = remote.scout()
    formulas = remote.tab(sheet.title, value_render_option="FORMULA")
    if formulas.header_values != sheet.header_values:
        raise ValueError("Google Sheet columns moved while reading formulas; retrying on the next sync.")
    remote_index = index_rows(sheet.rows)
    remote_rows = {key: data for key, (_, data) in remote_index.items()}
    formula_index = index_rows(formulas.rows)
    # Array formulas can own blank spill cells. Never infer writable ranges.
    if any("ARRAYFORMULA(" in text(v).upper() for _, data in formulas.rows for v in data.values()):
        raise ValueError("An array formula requires range review before synchronization.")
    con = sqlite3.connect(DATABASE, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("BEGIN IMMEDIATE")
        records = con.execute("SELECT * FROM workspace_records WHERE dataset='Job List'").fetchall()
        records = [r for r in records if not r["archived"] or
                   text(json.loads(r["values_json"]).get("ID")) in remote_rows]
        local_index = index_rows([(r["slot"], json.loads(r["values_json"])) for r in records])
        local_rows = {key: data for key, (_, data) in local_index.items()}
        local_headers = json.loads(con.execute("SELECT headers_json FROM workspace_datasets WHERE name='Job List'").fetchone()[0])
        from description_columns import adopt_split_schema
        base_rows, local_rows, local_headers = adopt_split_schema(
            state['rows'], local_rows, remote_rows, local_headers, sheet.header_values)
        headers = sync_headers(sheet.header_values, local_headers)
        if any(text(data.get("")).strip() for data in local_rows.values()):
            raise ValueError("An unnamed local column contains data; give it a name before syncing.")
        physical_width = len(sync_headers(sheet.header_values, []))
        if any(any(text(v).strip() for v in raw[physical_width:])
               for raw in (sheet.raw_rows or {}).values()):
            raise ValueError("An unnamed Sheet column contains data; give it a name before syncing.")
        merged = merge_rows(base_rows, local_rows, remote_rows, headers)
        if 'Enough Data' in headers:
            from description_columns import description_value
            from description_readiness import assess
            new_records=[{'id':key,'company':data.get('Company',''),'title':data.get('Job Title',''),
                          'description':description_value(data)} for key,data in merged.items()
                         if key not in base_rows and not text(data.get('Enough Data')).strip()]
            for key,review in assess(new_records).items():
                merged[key]['Enough Data']=review['value']
                previous=text(merged[key].get('Notes'))
                merged[key]['Notes']=previous+ ('\n' if previous else '')+'Enough Data content review: '+review['value']+' — '+review['reason']
        # Normalize the display, retaining raw discovery pay for eligibility.
        salary_changes = []
        if 'Salary' in headers:
            from salary_format import normalize_salary_row
            for key, data in merged.items():
                protected = formula_index.get(key, (0, {}))[1]
                if text(protected.get('Salary')).startswith('='):
                    continue
                changes, evidence = normalize_salary_row(data)
                if ('Notes' in changes and ('Notes' not in headers
                        or text(protected.get('Notes')).startswith('='))):
                    continue
                if changes:
                    salary_changes.append({'id': key, 'before': {h:data.get(h,'') for h in changes},
                                           'changes': changes, 'evidence': evidence})
                    data.update(changes)
        salary_audit = None
        if salary_changes:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            salary_audit = ROOT / 'reports/salary-normalization' / (stamp + '.json')
            save_json(salary_audit, {'status':'planned','changes':salary_changes})
        updates, appended, appended_rows = [], 0, []
        next_row = max((r for r, _ in sheet.rows), default=1) + 1
        for key, data in merged.items():
            row = remote_index[key][0] if key in remote_index else next_row
            if key not in remote_index:
                appended_rows.append(row)
                next_row += 1
                appended += 1
            for col, field in enumerate(headers, 1):
                old = remote_rows.get(key, {}).get(field, "")
                value = data.get(field, "")
                formula = formula_index.get(key, (0, {}))[1].get(field, "")
                if text(formula).startswith("="):
                    if text(value) != text(old):
                        raise ValueError(f"Job {key}: {field} contains a protected formula.")
                    continue
                if text(old) != text(value):
                    updates.append({"range": f"'Job List'!{_col(col)}{row}", "values": [[value]]})
        for col, field in enumerate(headers, 1):
            if col > physical_width:
                updates.append({"range": f"'Job List'!{_col(col)}1", "values": [[field]]})
        # Detect edits during planning before publishing any cell changes.
        fresh = remote.scout()
        if fresh.header_values != sheet.header_values or fresh.rows != sheet.rows:
            raise ValueError("Google Sheet changed during synchronization; retrying preserves both versions.")
        if updates:
            properties = next(p for p in remote._sheet_properties() if p["title"] == "Job List")
            grid = properties.get("gridProperties", {})
            requests = []
            if len(headers) > grid.get("columnCount", 0):
                requests.append({"appendDimension": {"sheetId": sheet.sheet_id, "dimension": "COLUMNS", "length": len(headers) - grid.get("columnCount", 0)}})
            if next_row > grid.get("rowCount", sheet.grid_rows):
                requests.append({"appendDimension": {"sheetId": sheet.sheet_id, "dimension": "ROWS", "length": next_row - grid.get("rowCount", sheet.grid_rows)}})
            if requests:
                remote.api.batchUpdate(spreadsheetId=remote.config.spreadsheet_id, body={"requests": requests}).execute()
            remote.api.values().batchUpdate(spreadsheetId=remote.config.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": updates}).execute()
        from sheet_ranges import extend_job_list
        range_extension = extend_job_list(remote, remote.scout(), appended_rows)
        # Newly filled Sheet formulas own their recalculated outputs too.
        refreshed_formulas = remote.tab(sheet.title, value_render_option="FORMULA")
        formula_index = index_rows(refreshed_formulas.rows)
        verified = remote.scout()
        if list(verified.header_values[:len(headers)]) != headers:
            raise RuntimeError("Google Sheet columns changed during synchronization; local data and baseline are preserved for retry.")
        actual = {key: data for key, (_, data) in index_rows(verified.rows).items()}
        # Formula outputs may recalculate after a changed input was written.
        for key, data in merged.items():
            for field in headers:
                if text(formula_index.get(key, (0, {}))[1].get(field, "")).startswith("="):
                    data[field] = actual.get(key, {}).get(field, "")
        if set(actual) != set(merged) or any(text(actual[k].get(h, "")) != text(d.get(h, "")) for k, d in merged.items() for h in headers):
            raise RuntimeError("Sheet readback changed or did not match. Local data and previous sync baseline are preserved.")
        timestamp = datetime.now(timezone.utc).isoformat()
        for key, data in merged.items():
            cleaned = {h: data.get(h, "") for h in headers}
            saved_formulas = {h: formula_index.get(key, (0, {}))[1].get(h)
                              for h in headers
                              if text(formula_index.get(key, (0, {}))[1].get(h, "")).startswith("=")}
            if key in local_index:
                slot, before = local_index[key]
                old_formulas = json.loads(con.execute(
                    "SELECT formulas_json FROM workspace_records WHERE dataset='Job List' AND slot=?",
                    (slot,)).fetchone()[0])
                if (set(before) == set(cleaned) and old_formulas == saved_formulas
                        and all(text(before.get(h, "")) == text(cleaned[h]) for h in headers)):
                    continue
                con.execute("UPDATE workspace_records SET values_json=?,formulas_json=?,revision=revision+1 WHERE dataset='Job List' AND slot=?", (json.dumps(cleaned), json.dumps(saved_formulas), slot))
            else:
                archived = con.execute("SELECT slot FROM workspace_jobs WHERE id=?", (int(key),)).fetchone()
                if archived:
                    slot = archived[0]
                    con.execute("UPDATE workspace_records SET values_json=?,archived=0,revision=revision+1 WHERE dataset='Job List' AND slot=?", (json.dumps(cleaned), slot))
                else:
                    slot = con.execute("SELECT COALESCE(MAX(slot),1)+1 FROM workspace_records WHERE dataset='Job List'").fetchone()[0]
                    con.execute("INSERT INTO workspace_records(dataset,slot,values_json) VALUES('Job List',?,?)", (slot, json.dumps(cleaned)))
                con.execute("UPDATE workspace_records SET formulas_json=? WHERE dataset='Job List' AND slot=?", (json.dumps(saved_formulas), slot))
            con.execute("INSERT INTO workspace_events(at,dataset,slot,action,after_json) VALUES(?,'Job List',?,'sheet-sync',?)", (timestamp, slot, json.dumps(cleaned)))
        con.execute("UPDATE workspace_datasets SET headers_json=? WHERE name='Job List'", (json.dumps(headers),))
        con.commit()
        save_json(STATE, {"spreadsheet_id": remote.config.spreadsheet_id, "rows": merged, "synced_at": timestamp})
        if salary_audit:
            save_json(salary_audit, {'status':'verified','synced_at':timestamp,'changes':salary_changes})
        result = {"status": "synced", "synced_at": timestamp, "rows": len(merged), "cells_written": len(updates), "jobs_added_to_sheet": appended, "url": remote.url(), "range_extension": range_extension}
        result['salaries_normalized'] = len(salary_changes)
        if salary_audit:
            result['salary_audit'] = str(salary_audit)
        save_json(STATUS, result)
        return result
    finally:
        con.close()


def record_error(error):
    result = {"status": "needs_attention", "error": str(error), "at": datetime.now(timezone.utc).isoformat()}
    if isinstance(error, SyncConflict):
        result["conflicts"] = error.conflicts
    save_json(STATUS, result)
