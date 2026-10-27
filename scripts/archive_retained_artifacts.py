"""Archive an explicit reviewed list of historical report files, then remove copies.

Never accepts live databases, sidecars, application directories, or broad globs.
The audit plan and deletion receipts belong outside Git.
"""
import argparse
from contextlib import closing
import gzip
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'job-scout'))
from database_maintenance import atomic_json,sha256
from retained_artifacts import restore


def archive_file(source, output, *, archive_root, purpose):
    source,output,archive_root=Path(source),Path(output),Path(archive_root)
    original_hash=sha256(source)
    output.mkdir(parents=True,exist_ok=True)
    archive=output/(original_hash+'.gz')
    if not archive.exists():
        temporary=archive.with_suffix('.gz.partial')
        with source.open('rb') as src,gzip.open(temporary,'wb',compresslevel=6) as dst:
            shutil.copyfileobj(src,dst)
        temporary.replace(archive)
    item=dict(archive=archive.relative_to(archive_root).as_posix(),archive_sha256=sha256(archive),
              sha256=original_hash,bytes=source.stat().st_size,purpose=purpose)
    # Restore to a separate file, including SQLite integrity on the restored copy.
    with tempfile.TemporaryDirectory(prefix='verify-artifact-',dir=output) as tmp:
        restored=restore(item,Path(tmp)/source.name)
        if source.suffix in ('.sqlite','.sqlite3','.db'):
            with closing(sqlite3.connect(restored.resolve().as_uri()+'?mode=ro',uri=True)) as con:
                if [r[0] for r in con.execute('PRAGMA integrity_check')]!=['ok']:
                    raise RuntimeError('Restored historical database integrity failed')
            item['sqlite_integrity']='ok'
        item['restored_sha256']=sha256(restored)
    if sha256(source)!=original_hash:raise RuntimeError('Source changed while archiving; preserve it')
    item['restoration_verified']=True
    return item


def execute(plan_path, *, delete=False):
    from retained_artifacts import MANIFEST
    from database_maintenance import BACKUPS
    plan_path=Path(plan_path).resolve()
    if not plan_path.is_relative_to(BACKUPS.resolve()):raise ValueError('Plan must be outside Git under C:/gecko-backups')
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    run=plan_path.parent
    receipt_path=run/'retained-artifact-receipts.json'
    if receipt_path.exists():raise RuntimeError('Receipts already exist; inspect them before resuming')
    registry=json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {'schema':1,'artifacts':{}}
    receipts=[]
    for proposed in plan:
        relative=Path(proposed['path'])
        original=ROOT/relative
        source=original.resolve()
        if not source.is_relative_to((ROOT/'reports').resolve()) or original.is_symlink():
            raise ValueError('Only exact historical report paths may be archived')
        if source.suffix not in ('.json','.sqlite','.sqlite3','.db'):
            raise ValueError('Unsupported historical report file')
        if source.suffix=='.json' and not (
            relative.as_posix().startswith('reports/discovery/') and
            (source.name=='additional-source-rows.json' or source.name.startswith('source-'))):
            raise ValueError('Only reviewed discovery feed snapshots may be removed as JSON artifacts')
        if relative.as_posix().startswith('reports/sqlite-migration/'):
            raise ValueError('Retain original migration activation inputs')
        if sha256(source)!=proposed['sha256']:raise RuntimeError('Source differs from reviewed plan: '+str(source))
        item=archive_file(source,run/'retained',archive_root=BACKUPS,purpose=proposed['purpose'])
        receipt={'path':relative.as_posix(),**item,'delete_authorized':delete,'deleted':False}
        receipts.append(receipt)
        # Publish and verify the durable reader manifest before removing any bytes.
        registry['artifacts'][relative.as_posix()]=item
        atomic_json(MANIFEST,registry)
        atomic_json(receipt_path,receipts)
        assert json.loads(MANIFEST.read_text())['artifacts'][relative.as_posix()]==item
        if delete:
            if sha256(source)!=item['sha256']:raise RuntimeError('Source changed before deletion')
            source.unlink()
            receipt['deleted']=True
            atomic_json(receipt_path,receipts)
        print(relative.as_posix()+': verified'+('; original removed' if delete else ''),flush=True)
    return receipts


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--delete-originals',action='store_true')
    args=parser.parse_args()
    execute(args.plan,delete=args.delete_originals)
