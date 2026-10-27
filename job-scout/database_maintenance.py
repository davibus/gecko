"""Verified, compressed SQLite recovery points outside the source checkout.

No restore operation in this module targets the live database. Rotation only
removes catalogued recovery files after ALL retained points restore successfully.
"""
from contextlib import contextmanager, closing
from datetime import datetime
import gzip
import base64
import hashlib
import json
import re
from pathlib import Path
import shutil
import sqlite3
import tempfile
from zoneinfo import ZoneInfo

BACKUPS = Path('C:/gecko-backups')
DISPOSABLE = ('update', 'sheet-sync', 'add-column', 'rename-column', 'manual-edit', 'manual-intake')
LOG_LIMIT = 1000
ROOT = Path(__file__).resolve().parents[1]
STATE_PATHS = ('reports/sheets-primary-cutover/sync-state.json',
               'reports/resume-delivery/manifest.json',
               'job-scout/preferences/tracker-backend.json',
               'job-scout/preferences/resume-delivery.json')


def capture_state(database):
    if Path(database).resolve() != (ROOT/'job-scout/data/jobs.sqlite3').resolve():
        return {}
    result={}
    for name in STATE_PATHS:
        path=ROOT/name
        if path.is_file():
            data=path.read_bytes()
            result[name]={'sha256':hashlib.sha256(data).hexdigest(), 'base64':base64.b64encode(data).decode()}
    return result


def attach_state(folder, point, state):
    if not state:return
    raw=json.dumps(state,sort_keys=True).encode()
    content_digest=hashlib.sha256(raw).hexdigest()
    path=folder/('state-'+content_digest+'.json.gz')
    if path.exists():
        with gzip.open(path,'rb') as src:
            if src.read()!=raw:raise RuntimeError('Existing recovery state differs')
        point.update(state_file=path.name,state_sha256=sha256(path),state_content_sha256=content_digest)
        return
    with gzip.open(path.with_suffix('.gz.partial'),'wb') as out:out.write(raw)
    with gzip.open(path.with_suffix('.gz.partial'),'rb') as src:
        if src.read()!=raw:raise RuntimeError('Recovery state verification failed')
    path.with_suffix('.gz.partial').replace(path)
    point.update(state_file=path.name,state_sha256=sha256(path),state_content_sha256=content_digest)


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


@contextmanager
def backup_lock(folder):
    """OS releases this byte lock even when a worker dies; no stale PID lock."""
    import msvcrt
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'backup.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('Another database backup/maintenance worker is active') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def table_manifest(con, *, exclude=()):
    """Counts and deterministic content hashes cover every record, including BLOBs."""
    result = {}
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        if name in exclude:
            continue
        quoted = '"' + name.replace('"', '""') + '"'
        # Row hashes sorted in Python also support WITHOUT ROWID/unordered tables.
        rows = []
        for row in con.execute('SELECT * FROM ' + quoted):
            h = hashlib.sha256()
            for value in row:
                data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode('utf-8')
                h.update(type(value).__name__.encode() + b':' + str(len(data)).encode() + b':' + data)
            rows.append(h.digest())
        result[name] = {'count': len(rows), 'sha256': hashlib.sha256(b''.join(sorted(rows))).hexdigest()}
    return result


def inspect_database(path, *, exclude=()):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as con:
        con.execute('BEGIN')
        checks = [r[0] for r in con.execute('PRAGMA integrity_check')]
        if checks != ['ok']:
            raise RuntimeError('Database integrity failed: ' + repr(checks))
        return table_manifest(con, exclude=exclude)


def verify_point(folder, point):
    path = folder/point['file']
    if path.parent.resolve() != folder.resolve():
        raise RuntimeError('Recovery path outside backup directory')
    if sha256(path) != point['compressed_sha256']:
        raise RuntimeError('Compressed recovery checksum mismatch: '+str(path))
    if point.get('state_file'):
        state_path=folder/point['state_file']
        if state_path.parent.resolve()!=folder.resolve() or sha256(state_path)!=point['state_sha256']:
            raise RuntimeError('Recovery sync/delivery state checksum mismatch')
        with gzip.open(state_path,'rb') as src:state=json.load(src)
        for item in state.values():
            if hashlib.sha256(base64.b64decode(item['base64'])).hexdigest()!=item['sha256']:
                raise RuntimeError('Recovery state record checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='restore-test-', dir=folder) as tmp:
        restored = Path(tmp)/'restored.sqlite3'
        with gzip.open(path, 'rb') as src, restored.open('wb') as dst:
            shutil.copyfileobj(src, dst)
        if sha256(restored) != point['sha256']:
            raise RuntimeError('Restored recovery checksum mismatch')
        if inspect_database(restored) != point['tables']:
            raise RuntimeError('Restored database records differ')
    return True


def load_catalog(folder):
    path = folder/'catalog.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []


def select_retained(points):
    ordered = sorted(points, key=lambda p: p['at'], reverse=True)
    daily, weekly = {}, {}
    for point in ordered:
        if point['kind'] == 'maintenance':
            continue
        daily.setdefault(point['day'], point['file'])
        weekly.setdefault(point['week'], point['file'])
    keep = set(list(daily.values())[:7]) | set(list(weekly.values())[:4])
    # Two additional pre-maintenance points, never rotated before replacement.
    keep.update(p['file'] for p in [p for p in ordered if p['kind']=='maintenance'][:2])
    return [p for p in points if p['file'] in keep]


def rotate(folder, points):
    retained = select_retained(points)
    if not retained:
        raise RuntimeError('Refusing to remove the last recovery point')
    for point in retained:
        verify_point(folder, point)
    # Commit the catalog first: interruptions can leave only excess copies.
    atomic_json(folder/'catalog.json', retained)
    keep = {p['file'] for p in retained}
    state_keep={p.get('state_file') for p in retained}
    def remove_generated(path):
        entry={'path':str(path),'bytes':path.stat().st_size,'sha256':sha256(path),'reason':'verified retention rotation'}
        log_path=folder/'rotation-deletions.json'
        previous=json.loads(log_path.read_text()) if log_path.exists() else []
        atomic_json(log_path,(previous+[entry])[-1000:])
        path.unlink()
    for point in points:
        if point['file'] not in keep:
            remove_generated(folder/point['file'])
            if point.get('state_file') and point['state_file'] not in state_keep:
                state_path=folder/point['state_file']
                if state_path.exists():remove_generated(state_path)
    # Shared content-addressed state blobs must not accumulate after updates.
    for state_path in folder.glob('state-*.json.gz'):
        if re.fullmatch(r'state-[0-9a-f]{64}\.json\.gz',state_path.name) and state_path.name not in state_keep:
            remove_generated(state_path)
    return retained


def store_snapshot(snapshot, folder, *, now, kind, reason, points, state=None):
    digest = sha256(snapshot)
    state_digest=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest() if state else None
    existing = next((p for p in points if p['sha256']==digest), None)
    if existing:
        verify_point(folder, existing)
        if state and existing.get('state_content_sha256')!=state_digest:
            attach_state(folder,existing,state)
            verify_point(folder,existing)
        if kind=='daily':existing['kind']='daily'
        return existing
    tables = inspect_database(snapshot)
    filename = now.strftime('%Y%m%dT%H%M%S%f')+'-'+digest[:12]+'.sqlite3.gz'
    path = folder/filename
    temporary = path.with_suffix('.gz.partial')
    with snapshot.open('rb') as src, gzip.open(temporary, 'wb', compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)
    temporary.replace(path)
    point = dict(file=filename, at=now.isoformat(), day=now.date().isoformat(),
                 week=now.strftime('%G-W%V'), kind=kind, reason=reason,
                 sha256=digest, compressed_sha256=sha256(path), tables=tables,
                 bytes=path.stat().st_size, original_bytes=snapshot.stat().st_size)
    attach_state(folder,point,state)
    verify_point(folder, point)
    points.append(point)
    atomic_json(folder/'catalog.json', points)
    return point


def backup_database(database, *, folder=BACKUPS, force=False, reason='daily', now=None):
    database, folder = Path(database), Path(folder)
    now = now or datetime.now(ZoneInfo('America/Denver'))
    with backup_lock(folder):
        points = load_catalog(folder)
        daily = [p for p in points if p['kind'] != 'maintenance']
        if not force and daily and max(p['day'] for p in daily) >= now.date().isoformat():
            latest = max(daily, key=lambda p:p['at'])
            verify_point(folder, latest)
            return {'status':'already-backed-up-today', 'backup':str(folder/latest['file']), 'integrity':'ok'}
        with tempfile.TemporaryDirectory(prefix='backup-work-', dir=folder) as tmp:
            state=capture_state(database)
            snapshot = Path(tmp)/'snapshot.sqlite3'
            with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as src, closing(sqlite3.connect(snapshot)) as dst:
                src.backup(dst)
            tables = inspect_database(snapshot)
            if capture_state(database)!=state:
                raise RuntimeError('Sync/delivery state changed during backup; retry in an idle window')
            # Operational timestamps/log churn alone do not require another backup.
            substantive = {k:v for k,v in tables.items() if k not in ('workspace_events','workspace_runs')}
            if not force and daily:
                latest = max(daily, key=lambda p:p['at'])
                old = {k:v for k,v in latest['tables'].items() if k not in ('workspace_events','workspace_runs')}
                state_digest=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest() if state else None
                if substantive == old and state_digest==latest.get('state_content_sha256'):
                    verify_point(folder, latest)
                    return {'status':'unchanged','backup':str(folder/latest['file']), 'integrity':'ok'}
            point = store_snapshot(snapshot, folder, now=now, kind='maintenance' if force else 'daily', reason=reason, points=points,state=state)
        retained = rotate(folder, points)
        return {'status':'verified','backup':str(folder/point['file']), 'integrity':'ok', 'restore_test':True, 'retained':len(retained)}


def log_event(con, at, dataset, slot, action, *, before=None, after=None):
    """Metadata only; durable business evidence remains in its original records."""
    payload = {'fields': sorted(k for k in set(before or {}) | set(after or {})
                                if (before or {}).get(k) != (after or {}).get(k))}
    # Manual upload rebase needs an old version and field fingerprints, not rows.
    recovery = None
    if before and dataset == 'Job List':
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='workspace_manual_jobs'").fetchone()
        if exists and con.execute('SELECT 1 FROM workspace_manual_jobs WHERE job_id=?',(str(before.get('ID','')),)).fetchone():
            from tracker_revisions import version, notes_parts, MANUAL_FIELDS
            from tracker_schema import resolve_headers
            headers=json.loads(con.execute('SELECT headers_json FROM workspace_datasets WHERE name=?',(dataset,)).fetchone()[0])
            normalized=dict(before)
            for alias,col in resolve_headers(headers).items():
                normalized[alias]=before.get(headers[col-1],'')
            recovery={'version':version(normalized), 'hashes':{
                k:hashlib.sha256(str(notes_parts(normalized.get(k))[0] if k=='Notes' else normalized.get(k) or '').encode()).hexdigest()
                for k in set(MANUAL_FIELDS)|{'Job URL','Notes'}}}
    con.execute('INSERT INTO workspace_events(at,dataset,slot,action,before_json,after_json) VALUES(?,?,?,?,?,?)',
                (at,dataset,slot,action,json.dumps(recovery) if recovery else None,json.dumps(payload)))
    marks=','.join('?' for _ in DISPOSABLE)
    con.execute(f'DELETE FROM workspace_events WHERE action IN ({marks}) AND id NOT IN '
                f'(SELECT id FROM workspace_events WHERE action IN ({marks}) ORDER BY id DESC LIMIT ?)',
                (*DISPOSABLE,*DISPOSABLE,LOG_LIMIT))
