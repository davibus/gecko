"""Fail staged commits containing runtime stores or blobs above GitHub's limit."""
import argparse
from pathlib import PurePosixPath
import subprocess
import sys

LIMIT=100*1024*1024


def disallowed(path):
    p=PurePosixPath(path)
    return (p.suffix in ('.sqlite','.sqlite3','.db','.bundle') or
            any(mark in p.name for mark in ('.sqlite3-','.sqlite-','.db-')) or
            path.startswith('reports/sqlite-backups/') or
            (path.startswith('reports/discovery/') and
             ((p.name.startswith('source-') and p.suffix=='.json') or p.name=='additional-source-rows.json')))


def check_staged():
    entries=subprocess.check_output(['git','ls-files','--stage','-z']).split(b'\0')
    errors=[]
    objects=[]
    for entry in entries:
        if not entry:continue
        metadata,path=entry.split(b'\t',1)
        mode,oid,stage=metadata.split()
        path=path.decode('utf-8')
        if stage!=b'0':errors.append(path+': unresolved merge');continue
        if disallowed(path):errors.append(path+': generated runtime artifact must remain outside Git')
        objects.append((oid.decode(),path))
    sizes=subprocess.check_output(['git','cat-file','--batch-check=%(objectsize)'],
        input=''.join(oid+'\n' for oid,_ in objects),text=True).splitlines()
    for (_,path),size in zip(objects,sizes):
        if not size.isdigit():errors.append(path+': cannot inspect staged object');continue
        if int(size)>LIMIT:errors.append(path+': exceeds GitHub 100 MiB blob limit')
    return errors


if __name__=='__main__':
    errors=check_staged()
    if errors:print('\n'.join(errors),file=sys.stderr)
    sys.exit(bool(errors))
