"""Read retained historical evidence without re-fetching or spending credits."""
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT/'job-scout/preferences/retained-artifacts.json'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def entries():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))['artifacts'] if MANIFEST.exists() else {}


def archive_path(item):
    base=Path(os.environ.get('GECKO_ARCHIVE_ROOT','C:/gecko-backups')).resolve()
    path=(base/item['archive']).resolve()
    if not path.is_relative_to(base):raise ValueError('Archive path escapes recovery root')
    return path


def key(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def available(path):
    # A registered but missing archive MUST fail on read, never trigger a fetch.
    return Path(path).is_file() or key(path) in entries()


def restore(item, destination):
    """Restore exact bytes, refusing an existing target or a checksum mismatch."""
    archive=archive_path(item)
    if digest(archive)!=item['archive_sha256']:raise RuntimeError('Retained archive checksum mismatch')
    destination=Path(destination)
    try:
        with destination.open('xb') as dst, gzip.open(archive,'rb') as src:
            shutil.copyfileobj(src,dst)
        if destination.stat().st_size!=item['bytes'] or digest(destination)!=item['sha256']:
            raise RuntimeError('Restored evidence checksum mismatch')
    except Exception:
        # Never unlink a pre-existing destination on open failure.
        raise
    return destination


@contextmanager
def artifact_path(path):
    path=Path(path)
    if path.is_file():
        yield path
        return
    item=entries().get(key(path))
    if item is None:raise FileNotFoundError(path)
    with tempfile.TemporaryDirectory(prefix='gecko-retained-') as tmp:
        yield restore(item,Path(tmp)/path.name)


def read_json(path):
    with artifact_path(path) as retained:
        return json.loads(retained.read_text(encoding='utf-8-sig'))
