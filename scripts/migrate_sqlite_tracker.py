"""Import a verified Sheet snapshot into SQLite without changing Google Sheets."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'job-scout'))
from google_tracker import GoogleTracker, Config
from sqlite_tracker import SCHEMA
from tracker_backend import DATABASE, CONFIG


def capture(folder):
    tracker = GoogleTracker(config=Config.from_environment())
    metadata = tracker.api.get(spreadsheetId=tracker.config.spreadsheet_id).execute()
    titles = [sheet['properties']['title'] for sheet in metadata['sheets']]
    ranges = ["'"+title.replace("'", "''")+"'!A:ZZ" for title in titles]
    args = dict(spreadsheetId=tracker.config.spreadsheet_id, ranges=ranges)
    values = tracker.api.values().batchGet(**args, valueRenderOption='UNFORMATTED_VALUE').execute()['valueRanges']
    formulas = tracker.api.values().batchGet(**args, valueRenderOption='FORMULA').execute()['valueRanges']
    check = tracker.api.values().batchGet(**args, valueRenderOption='UNFORMATTED_VALUE').execute()['valueRanges']
    if values != check:
        raise RuntimeError('Sheet changed during snapshot; migration stopped')
    snapshot = {'metadata':metadata, 'datasets':[
        {'name':title,'source_id':sheet['properties']['sheetId'],
         'values':value.get('values',[]),'formulas':formula.get('values',[])}
        for title,sheet,value,formula in zip(titles,metadata['sheets'],values,formulas)]}
    (folder/'sheet-snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False),encoding='utf-8')
    return snapshot


def import_snapshot(snapshot, database):
    datasets = {item['name']:item for item in snapshot['datasets']}
    if not {'Job List','Rejected Jobs'} <= datasets.keys():
        raise RuntimeError('Required job and rejection history datasets are missing')
    identifiers = []
    ledger = datasets['Job List']['values']
    if not ledger or ledger[0].count('ID') != 1:
        raise RuntimeError('Job List needs an unambiguous ID header')
    id_col = ledger[0].index('ID')
    for row in ledger[1:]:
        value = row[id_col] if len(row)>id_col else ''
        if value != '':
            if not str(value).isdigit() or int(value) <= 0:
                raise RuntimeError('Invalid stable job ID; migration stopped')
            identifiers.append(int(value))
    if len(identifiers) != len(set(identifiers)):
        raise RuntimeError('Duplicate stable job IDs; migration stopped')
    con = sqlite3.connect(database)
    try:
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_records'").fetchone():
            raise RuntimeError('An existing SQLite workspace must never be overwritten by migration')
        con.executescript(SCHEMA)
        with con:
            for dataset in snapshot['datasets']:
                values = dataset['values']
                # All original tabs remain in the immutable archive. Only actual
                # header-based job/rejection datasets become active records.
                con.execute('INSERT INTO workspace_archive VALUES(?,?,?)',
                            (dataset['name'],datetime.now(timezone.utc).isoformat(),json.dumps(dataset,ensure_ascii=False)))
                if dataset['name'] not in {'Job List','Rejected Jobs'}:
                    continue
                if not values:
                    raise RuntimeError('Required dataset has no headers')
                headers = values[0]
                if len(headers) != len(set(headers)):
                    raise RuntimeError('Duplicate headers; migration stopped')
                con.execute('INSERT INTO workspace_datasets VALUES(?,?,?)',
                            (dataset['name'],json.dumps(headers),dataset['source_id']))
                for index,row in enumerate(values[1:],2):
                    if not any(v not in ('',None) for v in row):
                        continue
                    data = {name:row[c] if c<len(row) else '' for c,name in enumerate(headers)}
                    formula_row = dataset['formulas'][index-1] if len(dataset['formulas'])>=index else []
                    protected = {headers[c]:v for c,v in enumerate(formula_row[:len(headers)])
                                 if isinstance(v,str) and v.startswith('=')}
                    con.execute('INSERT INTO workspace_records(dataset,slot,values_json,formulas_json) VALUES(?,?,?,?)',
                                (dataset['name'],index,json.dumps(data,ensure_ascii=False),json.dumps(protected)))
            con.execute('CREATE TABLE IF NOT EXISTS scout_state (key TEXT PRIMARY KEY,value INTEGER NOT NULL)')
            con.execute("INSERT INTO scout_state VALUES('id_high_water',?) ON CONFLICT(key) DO UPDATE SET value=MAX(value,excluded.value)",
                        (max(identifiers,default=0),))
        if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('SQLite integrity check failed')
        for dataset in snapshot['datasets']:
            if dataset['name'] not in {'Job List','Rejected Jobs'}:
                continue
            headers = dataset['values'][0]
            for index,row in enumerate(dataset['values'][1:],2):
                if not any(v not in ('',None) for v in row):
                    continue
                expected = {name:row[c] if c<len(row) else '' for c,name in enumerate(headers)}
                actual = json.loads(con.execute('SELECT values_json FROM workspace_records WHERE dataset=? AND slot=?',
                                               (dataset['name'],index)).fetchone()[0])
                if actual != expected:
                    raise RuntimeError('Migration readback mismatch')
        return {'jobs':len(identifiers),'records':con.execute('SELECT count(*) FROM workspace_records').fetchone()[0],
                'archived_datasets':len(datasets),'integrity':'ok','exact_values_verified':True}
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--activate', type=Path)
    args = parser.parse_args()
    if args.activate:
        from run_gecko import run_lock
        folder = args.activate.resolve()
        if not folder.is_relative_to((ROOT/'reports/sqlite-migration').resolve()):
            raise RuntimeError('Activation requires a verified Gecko migration folder')
        report = json.loads((folder/'verification.json').read_text())
        if report.get('exact_values_verified') is not True:
            raise RuntimeError('Migration has not passed verification')
        with run_lock():
            from database_maintenance import backup_database, load_catalog, BACKUPS, verify_point, inspect_database
            check_folder = folder/'activation-readback'
            check_folder.mkdir(exist_ok=True)
            fresh = capture(check_folder)
            previous = json.loads((folder/'sheet-snapshot.json').read_text(encoding='utf-8'))
            if fresh['datasets'] != previous['datasets']:
                raise RuntimeError('Sheet changed since the migration snapshot; cutover stopped')
            if report.get('recovery'):
                point=next(p for p in load_catalog(BACKUPS) if str(BACKUPS/p['file'])==report['recovery']['backup'])
                verify_point(BACKUPS,point)
                if inspect_database(DATABASE)!=point['tables']:
                    raise RuntimeError('Discovery database changed since backup; cutover stopped')
            else:
                # Historical migration candidates retain their original proof.
                with sqlite3.connect(DATABASE) as live, sqlite3.connect(folder/'before.sqlite3') as backup:
                    if list(live.iterdump()) != list(backup.iterdump()):
                        raise RuntimeError('Discovery database changed since backup; cutover stopped')
            backup_database(DATABASE,force=True,reason='before-migration-activation')
            with sqlite3.connect(folder/'candidate.sqlite3') as candidate, sqlite3.connect(DATABASE) as live:
                candidate.backup(live)
                if live.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Activated database failed integrity check')
            config = {'backend':'sqlite','database':str(DATABASE),'migration':str(folder),
                      'activated_at':datetime.now(timezone.utc).isoformat()}
            temporary = CONFIG.with_suffix('.tmp')
            temporary.write_text(json.dumps(config,indent=2))
            temporary.replace(CONFIG)
            report['activation'] = config
            (folder/'verification.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2))
        return
    folder = ROOT/'reports/sqlite-migration'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder.mkdir(parents=True)
    snapshot = capture(folder)
    if not args.apply:
        print('Read-only snapshot: '+str(folder))
        return
    from database_maintenance import backup_database
    recovery=backup_database(DATABASE,force=True,reason='before-tracker-migration')
    # Build in a separate file. The live discovery database stays untouched until
    # all records, identities and the integrity check have passed.
    candidate = folder/'candidate.sqlite3'
    with sqlite3.connect(DATABASE) as source, sqlite3.connect(candidate) as target:
        source.backup(target)
    report = import_snapshot(snapshot,candidate)
    report['snapshot_sha256'] = hashlib.sha256((folder/'sheet-snapshot.json').read_bytes()).hexdigest()
    report['backup'] = recovery['backup']
    report['recovery'] = recovery
    (folder/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({**report,'candidate':str(candidate),'activation':'pending'},indent=2))


if __name__ == '__main__':
    main()
