"""Transactional SQLite authority, retaining Gecko's existing queue safety checks.

The small values adapter translates legacy managed-field batches into one SQL
transaction. It contains no Google client and performs no network operations.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

from google_tracker import GoogleTracker, Tab
from tracker_schema import resolve_headers, SCOUT_TAB, REJECTED_TAB
from tracker_backend import DATABASE


SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_datasets (
 name TEXT PRIMARY KEY, headers_json TEXT NOT NULL, source_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_records (
 dataset TEXT NOT NULL REFERENCES workspace_datasets(name), slot INTEGER NOT NULL,
 values_json TEXT NOT NULL CHECK(json_valid(values_json)),
 formulas_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(formulas_json)),
 archived INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(dataset,slot));
CREATE UNIQUE INDEX IF NOT EXISTS workspace_job_identity ON workspace_records
 (CAST(json_extract(values_json,'$.ID') AS INTEGER))
 WHERE dataset='Job List' AND json_extract(values_json,'$.ID') NOT IN ('',0);
CREATE INDEX IF NOT EXISTS workspace_active ON workspace_records(dataset,archived,slot);
CREATE TABLE IF NOT EXISTS workspace_events (
 id INTEGER PRIMARY KEY, at TEXT NOT NULL, dataset TEXT NOT NULL, slot INTEGER,
 action TEXT NOT NULL, before_json TEXT, after_json TEXT);
CREATE TABLE IF NOT EXISTS workspace_runs (
 run_id TEXT PRIMARY KEY, at TEXT NOT NULL, status TEXT NOT NULL, report_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_archive (
 name TEXT PRIMARY KEY, imported_at TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE VIEW IF NOT EXISTS workspace_jobs AS SELECT slot, revision, archived,
 CAST(json_extract(values_json,'$.ID') AS INTEGER) AS id,
 json_extract(values_json,'$.Company') AS company,
 json_extract(values_json,'$."Job Title"') AS title,
 json_extract(values_json,'$.Source') AS source,
 json_extract(values_json,'$."Apply?"') AS approval,
 json_extract(values_json,'$.Applied') AS applied,
 json_extract(values_json,'$."Resume Created"') AS resume_created,
 json_extract(values_json,'$."Resume Link"') AS resume_link,
 json_extract(values_json,'$.Notes') AS notes,
 json_extract(values_json,'$.Response') AS response,
 values_json FROM workspace_records WHERE dataset='Job List';
"""


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Result:
    def __init__(self, operation):
        self.operation = operation
    def execute(self, **_):
        return self.operation()


class LocalValues:
    def __init__(self, tracker):
        self.tracker = tracker
    def batchUpdate(self, *, body, **_):
        return Result(lambda: self.tracker.apply_entries(body['data']))


class LocalAPI:
    def __init__(self, tracker):
        self.tracker = tracker
    def values(self):
        return LocalValues(self.tracker)
    def batchUpdate(self, *, body, **_):
        # SQL has no grid dimensions or checkbox formatting. These requests
        # carry no data; all other legacy structural mutations fail closed.
        allowed = {'appendDimension', 'updateDimensionProperties', 'setDataValidation'}
        if any(set(request) - allowed for request in body.get('requests', [])):
            raise RuntimeError('Unsupported legacy structural operation on SQLite')
        return Result(lambda: {})


class SQLiteTracker(GoogleTracker):
    backend = 'sqlite'
    def __init__(self, config=None, service=None, *, db=None):
        from google_tracker import load_environment
        load_environment()
        self.path = Path(db or DATABASE)
        if not self.path.is_file():
            raise RuntimeError('SQLite tracker has not been migrated')
        self.config = SimpleNamespace(scout_tab=SCOUT_TAB, application_tab='Job Tracker',
                                      spreadsheet_id='sqlite:' + str(self.path))
        self.api = LocalAPI(self)
        self.skipped_writes = []
        self.discovery_writes = False
        self.before_writes = None
        with self.connection() as con:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_records'").fetchone():
                raise RuntimeError('SQLite tracker migration is missing; refusing Sheets fallback')

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        try:
            yield con
        finally:
            con.close()

    def tab(self, title, *, value_render_option='UNFORMATTED_VALUE'):
        with self.connection() as con:
            dataset = con.execute('SELECT * FROM workspace_datasets WHERE name=?', (title,)).fetchone()
            if dataset is None:
                raise RuntimeError(f'Local dataset {title!r} not found')
            headers = json.loads(dataset['headers_json'])
            records = con.execute('SELECT * FROM workspace_records WHERE dataset=? AND archived=0 ORDER BY slot', (title,)).fetchall()
            maximum = con.execute('SELECT COALESCE(MAX(slot),1) FROM workspace_records WHERE dataset=?', (title,)).fetchone()[0]
        resolved = resolve_headers(headers)
        rows, raw = [], {1: tuple(headers)}
        for record in records:
            data = json.loads(record['values_json'])
            if value_render_option == 'FORMULA':
                data.update(json.loads(record['formulas_json']))
            raw[record['slot']] = tuple(data.get(field, '') for field in headers)
            for alias,column in resolved.items():
                data[alias] = raw[record['slot']][column-1]
            rows.append((record['slot'], data))
        return Tab(title, dataset['source_id'], resolved, rows,
                   max(maximum + 1000, 10000), tuple(headers), raw)

    def _sheet_properties(self):
        with self.connection() as con:
            return [{'title': r['name'], 'sheetId': r['source_id'],
                     'gridProperties': {'rowCount':10000, 'columnCount':len(json.loads(r['headers_json']))}}
                    for r in con.execute('SELECT * FROM workspace_datasets')]

    def _next_row(self, tab):
        with self.connection() as con:
            persisted = con.execute('SELECT COALESCE(MAX(slot),1)+1 FROM workspace_records WHERE dataset=?', (tab.title,)).fetchone()[0]
        return max(persisted, max((r for r,_ in tab.rows), default=1)+1)

    def apply_entries(self, entries):
        grouped = {}
        for entry in entries:
            match = re.fullmatch(r"'((?:[^']|'')+)'!([A-Z]+)(\d+)", entry['range'])
            if not match or len(entry.get('values', [])) != 1 or len(entry['values'][0]) != 1:
                raise ValueError('Only exact managed-field writes are supported')
            dataset, letters, row = match.groups()
            dataset = dataset.replace("''", "'")
            tab = self.tab(dataset)
            col = 0
            for letter in letters:
                col = col * 26 + ord(letter) - 64
            if not 1 <= col <= len(tab.header_values):
                raise ValueError('Unknown tracker field')
            grouped.setdefault((dataset,int(row)), {})[tab.header_values[col-1]] = entry['values'][0][0]
        expected = self.before_writes
        return self.update_records(grouped, expected=expected)

    def update_records(self, grouped, *, expected=None):
        originals = dict(expected.rows) if expected else {}
        with self.connection() as con, con:
            con.execute('BEGIN IMMEDIATE')
            for (dataset, slot), changes in grouped.items():
                record = con.execute('SELECT * FROM workspace_records WHERE dataset=? AND slot=?', (dataset,slot)).fetchone()
                before = json.loads(record['values_json']) if record else {}
                scope = os.getenv('GECKO_ALLOWED_JOB_IDS')
                if scope:
                    allowed = {int(i) for i in scope.split(',')}
                    if dataset != SCOUT_TAB or not record or int(before.get('ID') or before.get('Scout ID') or 0) not in allowed:
                        raise RuntimeError('Write outside selected job IDs blocked')
                    if 'ID' in changes or 'Scout ID' in changes:
                        raise RuntimeError('Identity changes are forbidden during selected-job runs')
                formulas = json.loads(record['formulas_json']) if record else {}
                if record and record['archived']:
                    raise RuntimeError('Job was archived; update stopped')
                if expected and expected.title == dataset:
                    original = originals.get(slot, {})
                    # Canonical aliases are added by scout(), not persisted.
                    for field in expected.header_values:
                        old = original.get(field,'')
                        current = formulas.get(field,before.get(field,'')) if isinstance(old,str) and old.startswith('=') else before.get(field,'')
                        if current != old:
                            raise RuntimeError('Job changed before the transaction; refresh before saving')
                if set(changes) & set(formulas):
                    raise RuntimeError('Imported formula field is protected')
                if any('ARRAYFORMULA' in str(value).upper() for value in formulas.values()):
                    raise RuntimeError('Imported array formula requires review before editing')
                after = {**before, **changes}
                con.execute('INSERT INTO workspace_records(dataset,slot,values_json) VALUES(?,?,?) '
                            'ON CONFLICT(dataset,slot) DO UPDATE SET values_json=excluded.values_json,revision=revision+1',
                            (dataset,slot,json.dumps(after,ensure_ascii=False)))
                con.execute('INSERT INTO workspace_events(at,dataset,slot,action,before_json,after_json) VALUES(?,?,?,?,?,?)',
                            (stamp(),dataset,slot,'update',json.dumps(before),json.dumps(after)))
        self.before_writes = None
        return {'updatedRecords':len(grouped)}

    def dashboard_edit(self, original, changes):
        tab = self.scout()
        matches = [(row,data) for row,data in tab.rows if str(data.get('Scout ID')) == str(original['Scout ID'])]
        if len(matches) != 1 or any(matches[0][1].get(k,'') != v for k,v in original.items()):
            raise RuntimeError('This job changed; refresh before saving')
        self.update_records({(tab.title,matches[0][0]):changes}, expected=tab)
        return matches[0][0]

    def highlight_scout_found_on(self, day):
        return sum(data.get('Date Found') == day for _,data in self.scout().rows)

    def _checkboxes(self, tab, row):
        pass

    def delete_scout_rows(self, rows, *, expected_fingerprints=None):
        if os.getenv('GECKO_ALLOWED_JOB_IDS'):
            raise RuntimeError('Row archival is disabled during selected-job runs')
        tab = self.scout()
        current = dict(tab.rows)
        for row in rows:
            data = current.get(row)
            if data is None:
                raise RuntimeError('Job is no longer active')
            fingerprint = tuple(str(data.get(k) or '').strip() for k in
                ('Scout ID','Source','Company','Job Title','Apply?','Job URL'))
            if expected_fingerprints and fingerprint != expected_fingerprints.get(row):
                raise RuntimeError('Rejected job identity changed')
        with self.connection() as con, con:
            con.execute('BEGIN IMMEDIATE')
            for row in rows:
                stored = con.execute('SELECT values_json FROM workspace_records WHERE dataset=? AND slot=? AND archived=0', (SCOUT_TAB,row)).fetchone()
                if not stored or any(json.loads(stored[0]).get(k,'') != current[row].get(k,'') for k in tab.header_values):
                    raise RuntimeError('Job changed before archive')
                con.execute('UPDATE workspace_records SET archived=1,revision=revision+1 WHERE dataset=? AND slot=?',(SCOUT_TAB,row))
                con.execute('INSERT INTO workspace_events(at,dataset,slot,action,before_json) VALUES(?,?,?,?,?)',
                            (stamp(),SCOUT_TAB,row,'archive',stored[0]))
        return sorted(set(rows),reverse=True)

    def remove_dead_scout(self, scout_ids):
        tab = self.scout()
        rows = [r for r,d in tab.rows if str(d.get('Scout ID')) in {str(i) for i in scout_ids}
                and not str(d.get('Resume Created') or '').strip() and not str(d.get('Applied') or '').strip()]
        self.delete_scout_rows(rows)
        return set(scout_ids)

    def url(self):
        return ''
