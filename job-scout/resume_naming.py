"""Short resume identifiers with lossless source-job identity mapping."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET

REGISTRY = '.resume-identities.json'
MAX_FILENAME = 150


def _load(folder):
    path = Path(folder) / REGISTRY
    if not path.exists():
        return {'version': 1, 'entries': {}}
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if data.get('version') != 1 or not isinstance(data.get('entries'), dict):
        raise ValueError('Invalid resume identity registry; naming stopped')
    return data


def _safe(value):
    value = re.sub(r'[\\/:*?"<>|+\s]+', '-', str(value).strip())
    return re.sub('-{2,}', '-', value).strip(' .-')


def _key(company, title, number):
    return hashlib.sha256(json.dumps([str(company).strip().casefold(), str(title).strip().casefold(), str(number).strip()], ensure_ascii=False).encode()).hexdigest()


@contextmanager
def _lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / (REGISTRY + '.lock')
    start = time.monotonic()
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() - start > 10:
                raise RuntimeError('Resume naming registry is locked; no identifier was reused')
            time.sleep(.1)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        lock.unlink()


def _build(company, title, identifier):
    company, title = _safe(company), _safe(title)
    if not company or not title:
        raise ValueError('Resume filename needs company and job title')
    available = MAX_FILENAME - len(f'Dave-Call+{company}++{identifier}.docx')
    if available < 20:
        raise ValueError('Company name leaves too little room for a readable job title')
    if len(title) > available:
        shortened = title[:available].rstrip(' .-')
        title = shortened.rsplit('-', 1)[0] if '-' in shortened else shortened
    return f'Dave-Call+{company}+{title}+{identifier}.docx'


def filename(company, title, job_number, folder, *, reserve=False, revision=False):
    """Preview without writes; actual generation reserves a globally unique ID."""
    if not str(job_number).strip():
        raise ValueError('Full source job number is required')
    folder = Path(folder)
    key = _key(company, title, job_number)
    def allocate():
        data = _load(folder)
        if not revision:
            for name, entry in data['entries'].items():
                if entry['key'] == key and entry['primary']:
                    return name
        used = {int(entry['id']) for entry in data['entries'].values()}
        for path in folder.glob('*.docx'):
            suffix = path.stem.rsplit('+', 1)[-1]
            if re.fullmatch(r'\d{1,5}', suffix):
                used.add(int(suffix))
        identifier = next((f'{number:05d}' for number in range(1, 100000) if number not in used), None)
        if identifier is None:
            raise ValueError('Five-digit resume identifier space exhausted; no ID was reused')
        name = _build(company, title, identifier)
        if reserve:
            data['entries'][name] = {'id': identifier, 'key': key, 'primary': not revision,
                                     'company': company, 'title': title, 'job_number': str(job_number)}
            temp = folder / (REGISTRY + '.' + uuid.uuid4().hex + '.tmp')
            try:
                temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
                os.replace(temp, folder / REGISTRY)
            finally:
                if temp.exists(): temp.unlink()
        return name
    if reserve:
        with _lock(folder):
            return allocate()
    return allocate()


def identity(path):
    """Resolve exact mapped filenames, including moved/archived files."""
    path = Path(path)
    embedded = ''
    if path.is_file():
        try:
            with ZipFile(path) as archive:
                root = ET.fromstring(archive.read('docProps/core.xml'))
            value = root.findtext('{http://purl.org/dc/elements/1.1/}identifier') or ''
            if value.startswith('gecko-job:'):
                embedded = value.removeprefix('gecko-job:')
        except (BadZipFile, KeyError, ET.ParseError):
            pass
    for folder in [path.parent, *path.parent.parents]:
        if (folder / REGISTRY).exists():
            entry = _load(folder)['entries'].get(path.name)
            if entry is not None:
                if embedded and embedded != entry['job_number']:
                    raise ValueError('Resume metadata conflicts with identity registry')
                return entry
    if embedded:
        return {'job_number': embedded}
    return None


def job_number(path):
    entry = identity(path)
    return entry['job_number'] if entry else Path(path).stem.rsplit('+', 1)[-1]


def related_files(folder, company, title, number):
    key = _key(company, title, number)
    return [Path(folder) / name for name, entry in _load(folder)['entries'].items() if entry['key'] == key]
