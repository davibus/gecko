"""Explicit offline cleanup. Does not run discovery, resumes, or applications."""
import argparse
from contextlib import closing
from datetime import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'job-scout'))
import database_maintenance as m
from run_gecko import run_lock


def archive_history(database, folder):
    """Exclusive connection remains locked through archive, deletion, and VACUUM."""
    with closing(sqlite3.connect(database, timeout=1)) as con:
        con.execute('PRAGMA locking_mode=EXCLUSIVE')
        con.execute('BEGIN EXCLUSIVE')
        before=m.table_manifest(con,exclude=('workspace_events',))
        preserved=con.execute('SELECT count(*) FROM workspace_events WHERE action NOT IN ('+','.join('?' for _ in m.DISPOSABLE)+')',m.DISPOSABLE).fetchone()[0]
        maximum=con.execute('SELECT COALESCE(MAX(id),0) FROM workspace_events').fetchone()[0]
        archive=folder/('workspace-events-through-'+str(maximum)+'.jsonl.gz')
        marks=','.join('?' for _ in m.DISPOSABLE)
        digest=hashlib.sha256(); count=0
        if archive.exists():
            raise RuntimeError('History archive exists; inspect receipt before resuming')
        with gzip.open(archive.with_suffix('.gz.partial'),'wb') as dst:
            for row in con.execute(f'SELECT * FROM workspace_events WHERE action IN ({marks}) ORDER BY id',m.DISPOSABLE):
                raw=(json.dumps(tuple(row),ensure_ascii=False)+'\n').encode()
                dst.write(raw);digest.update(raw);count+=1
        archive.with_suffix('.gz.partial').replace(archive)
        verified=hashlib.sha256(); restored_count=0
        with gzip.open(archive,'rb') as src:
            for raw in src:
                json.loads(raw);verified.update(raw);restored_count+=1
        if verified.digest()!=digest.digest() or restored_count!=count:
            raise RuntimeError('History archive verification failed; database unchanged')
        receipt=dict(archive=str(archive),rows=count,sha256=digest.hexdigest(),gzip_sha256=m.sha256(archive),verified=True)
        m.atomic_json(folder/'history-archive-receipt.json',receipt)
        con.execute(f'DELETE FROM workspace_events WHERE id<=? AND action IN ({marks})',(maximum,*m.DISPOSABLE))
        if m.table_manifest(con,exclude=('workspace_events',))!=before:
            con.rollback();raise RuntimeError('Protected records changed during cleanup')
        if con.execute('SELECT count(*) FROM workspace_events').fetchone()[0]!=preserved:
            con.rollback();raise RuntimeError('Durable event evidence changed')
        con.commit()
        # EXCLUSIVE locking mode keeps the lock after commit, including VACUUM.
        con.execute('VACUUM')
        if [r[0] for r in con.execute('PRAGMA integrity_check')]!=['ok'] or m.table_manifest(con,exclude=('workspace_events',))!=before:
            raise RuntimeError('Post-compaction verification failed; retain recovery point')
        m.atomic_json(folder/'protected-tables.json',before)
        return dict(receipt,remaining_events=preserved,protected_tables_unchanged=True)


def clean_old_backups(folder):
    if (folder/'backup-deletion-log.json').exists():
        raise RuntimeError('Backup cleanup already has a deletion receipt; preserve it and review before another cleanup')
    source=(ROOT/'reports/sqlite-backups').resolve()
    paths=sorted(source.iterdir())
    inventory=[]
    for path in paths:
        if not path.is_file() or path.is_symlink() or not re.fullmatch(r'\d{8}T\d{12}\.sqlite3',path.name):
            raise RuntimeError('Unexpected backup entry; preserve for review: '+str(path))
        with path.open('rb') as stream:
            if stream.read(16)!=b'SQLite format 3\x00':raise RuntimeError('Not a SQLite backup: '+str(path))
        inventory.append(dict(path=str(path),bytes=path.stat().st_size,sha256=m.sha256(path)))
    m.atomic_json(folder/'old-backup-inventory.json',inventory)
    latest={}
    for path in paths:latest[path.name[:8]]=path
    points=m.load_catalog(folder)
    # Include all historical days in policy selection before compressing selected ones.
    candidates=[]
    for day,path in latest.items():
        when=datetime.strptime(path.stem,'%Y%m%dT%H%M%S%f').replace(tzinfo=ZoneInfo('America/Denver'))
        candidates.append(dict(file=str(path),at=when.isoformat(),day=when.date().isoformat(),week=when.strftime('%G-W%V'),kind='daily'))
    selected={p['file'] for p in m.select_retained(points+candidates)}
    retained=[]
    for candidate in candidates:
        path=Path(candidate['file'])
        if str(path) in selected:
            when=datetime.fromisoformat(candidate['at'])
            point=m.store_snapshot(path,folder,now=when,kind='daily',reason='retained-historical-daily',points=points)
            retained.append(dict(original=str(path),retained=str(folder/point['file']),verified=True))
    m.rotate(folder,points)  # all selected compressed copies restore before deletion
    deleted=[]
    for item in inventory:
        path=Path(item['path'])
        if path.parent.resolve()!=source or path.stat().st_size!=item['bytes'] or m.sha256(path)!=item['sha256']:
            raise RuntimeError('Backup changed since inventory; deletion stopped')
        item['reason']='superseded backup; latest daily/weekly points compressed and restore verified'
        deleted.append(item)
        # Write intent before each exact file deletion, then record completion.
        m.atomic_json(folder/'backup-deletion-log.json',deleted)
        path.unlink()
        item['deleted']=True
        m.atomic_json(folder/'backup-deletion-log.json',deleted)
    return dict(deleted=deleted,retained=retained,bytes_recovered=sum(d['bytes'] for d in deleted))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['backup','pre-maintenance','cleanup-history','cleanup-backups'])
    args=parser.parse_args()
    database=ROOT/'job-scout/data/jobs.sqlite3'
    if args.action in ('backup','pre-maintenance'):
        result=m.backup_database(database,force=args.action=='pre-maintenance',reason=args.action)
    else:
        with run_lock():
            # Every destructive invocation creates/reuses a verified recovery point.
            recovery=m.backup_database(database,force=True,reason=args.action)
            with m.backup_lock(m.BACKUPS):
                if args.action=='cleanup-history':result=archive_history(database,m.BACKUPS)
                else:result=clean_old_backups(m.BACKUPS)
            result['recovery']=recovery
    m.atomic_json(m.BACKUPS/(args.action+'-result.json'),result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
