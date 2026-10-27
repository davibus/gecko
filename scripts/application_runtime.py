"""Batch-local sources, exclusive phase timings and durable application checkpoints.

No browser, model, tracker or resume-generation side effects on import.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from queue import Queue, Empty
from time import perf_counter
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
PHASES = ('preparation', 'inspection', 'filling', 'upload', 'waiting', 'confirmation', 'tracker')


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f'.{os.getpid()}.tmp')
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


class Timings:
    def __init__(self):
        self.seconds = dict.fromkeys(PHASES, 0.0)
        self.counts = dict.fromkeys(PHASES, 0)
        self.stack = []
        self.started = perf_counter()

    @contextmanager
    def phase(self, name):
        item = [perf_counter(), 0.0]
        self.stack.append(item)
        try:
            yield
        finally:
            elapsed = perf_counter() - item[0]
            self.stack.pop()
            self.seconds[name] += elapsed - item[1]
            self.counts[name] += 1
            if self.stack:
                self.stack[-1][1] += elapsed

    def report(self):
        return {'seconds': self.seconds, 'counts': self.counts,
                'wall_seconds': perf_counter() - self.started}


def meaning(value):
    return re.sub(r'[^a-z0-9]+', ' ', str(value).casefold()).strip()


class BatchSources:
    """Parse current master and reviewed saved-answer index once per content version.

    Each job hashes the actual source bytes. A changed source invalidates its
    parsed content; source quotes must still be present before an answer is used.
    The index is a lookup into the answer bank, never an alternate factual source.
    """
    def __init__(self, root=ROOT, records=None):
        self.root = Path(root)
        self.paths = {
            'master': self.root / 'input/master-resume/master-resume-v4.docx',
            'answers': self.root / 'openclaw/application-answers.md',
            'index': self.root / 'scripts/application_answer_index.json',
        }
        self.hashes = {}
        self.content = {}
        self.parse_counts = dict.fromkeys(self.paths, 0)
        self.records_override = records
        self.lookup_cache = {}

    def refresh(self):
        for name, path in self.paths.items():
            if name == 'index' and self.records_override is not None:
                self.content['index'] = self.records_override
                continue
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            if self.hashes.get(name) == digest:
                continue
            if name == 'master':
                with ZipFile(BytesIO(data)) as docx:
                    xml = ET.fromstring(docx.read('word/document.xml'))
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                # Includes body paragraphs, tables and list items in document order.
                parsed = '\n'.join(''.join(t.text or '' for t in p.findall('.//w:t', ns))
                                   for p in xml.findall('.//w:p', ns))
            elif name == 'index':
                parsed = json.loads(data.decode('utf-8-sig'))
            else:
                parsed = data.decode('utf-8-sig').replace('\r\n', '\n')
            self.hashes[name] = digest
            self.content[name] = parsed
            self.parse_counts[name] += 1
            self.lookup_cache.clear()
        return self

    def for_job(self, packet):
        key = (str(packet['id']), meaning(packet['company']))
        if key in self.lookup_cache:
            return self.lookup_cache[key]
        valid = []
        for record in self.content.get('index', []):
            if record.get('status') != 'confirmed' or not record.get('confirmed_on'):
                continue
            scope = record.get('scope', {})
            if scope.get('employer') and meaning(scope['employer']) != meaning(packet['company']):
                continue
            if scope.get('jobs') and str(packet['id']) not in map(str, scope['jobs']):
                continue
            if record.get('historical_only'):
                continue
            source = record.get('source', {})
            text = self.content.get(source.get('kind'), '')
            if source.get('sha256') and source['sha256'] != self.hashes.get(source.get('kind')):
                continue  # A changed answer bank needs its changed confirmations reviewed.
            if not source.get('quote') or source['quote'] not in text:
                continue
            value = record['answer']
            if source.get('kind') == 'master' and str(value) not in text:
                continue
            valid.append(record)
        self.lookup_cache[key] = valid
        return valid

    def resolve(self, question, packet, *, alias=None):
        q = meaning(question)
        hits = [record for record in self.for_job(packet)
                if q in [meaning(x) for x in record.get('questions', [])]
                or (alias is not None and alias == record['meaning'])
                or any(re.fullmatch(p, q) for p in record.get('patterns', []))]
        if not hits:
            return None
        # Specific scope wins; newest explicit confirmation wins within that scope.
        hits.sort(key=lambda r: (bool(r.get('scope', {}).get('jobs')),
                                 bool(r.get('scope', {}).get('employer')), r['confirmed_on']), reverse=True)
        best = hits[0]
        rank = lambda r: (bool(r.get('scope', {}).get('jobs')), bool(r.get('scope', {}).get('employer')), r['confirmed_on'])
        if any(rank(r) == rank(best) and r['answer'] != best['answer'] for r in hits):
            return None
        return dict(best)


def canonical_url(url):
    p = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith(('utm_', 'gh_src')) and k.lower() not in ('source', 'ref')]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), urlencode(sorted(query)), ''))


def ledger_root(out):
    audit = ROOT / 'reports/playwright-pilot'
    out = Path(out)
    return audit if out.is_relative_to(audit) else (out.parent if out.name.isdigit() else out)


def prior_attempt(packet, out):
    base = ledger_root(out)
    ident = str(packet['id'])
    for p in base.glob(f'*/{ident}/submission-attempt.json'):
        return p
    direct = Path(out) / 'submission-attempt.json'
    if direct.exists():
        return direct
    for key in submission_keys(packet):
        p = base / 'submission-ledger' / f'{key}.json'
        if p.exists():
            return p
    return None


def submission_keys(packet):
    identities = [f"id:{packet['id']}"]
    scout = str(ROOT / 'job-scout')
    if scout not in sys.path:
        sys.path.insert(0, scout)
    from normalize import posting_identity
    for url in (packet.get('url'), packet.get('row', {}).get('Job URL')):
        if url:
            identities.append('url:' + canonical_url(url))
            identities.append('posting:' + json.dumps(posting_identity(url)))
    return [hashlib.sha256(v.encode()).hexdigest() for v in sorted(set(identities))]


def claim_attempt(packet, out, attempt):
    """Exclusive claims survive process death and protect aliases/new batch folders."""
    if prior_attempt(packet, out):
        raise RuntimeError('Prior submission attempt exists; reconcile employer state instead of retrying')
    base = ledger_root(out) / 'submission-ledger'
    base.mkdir(parents=True, exist_ok=True)
    # Claims are deliberately retained even if a later claim or click fails.
    for key in submission_keys(packet):
        with (base / f'{key}.json').open('x', encoding='utf-8') as stream:
            json.dump(attempt, stream)
            stream.flush()
            os.fsync(stream.fileno())
    save(Path(out) / 'submission-attempt.json', attempt)


class TrackerClient:
    """One native dashboard-Python tracker process and API client per batch."""
    def __init__(self, root=ROOT, timeout=60):
        self.timeout = timeout
        self.process = subprocess.Popen(
            [str(Path(root)/'.tools/dashboard-python/Scripts/python.exe'), '-u',
             str(Path(root)/'scripts/playwright_tracker.py'), '--serve'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.responses = Queue()
        def read():
            for line in self.process.stdout:
                self.responses.put(line)
            self.responses.put(None)
        threading.Thread(target=read, daemon=True).start()

    def call(self, action, **args):
        if self.process.poll() is not None:
            raise RuntimeError('Tracker worker stopped; saved receipts require reconciliation')
        self.process.stdin.write(json.dumps(dict(action=action, **args)) + '\n')
        self.process.stdin.flush()
        try:
            line = self.responses.get(timeout=self.timeout)
        except Empty:
            self.process.kill()  # Never reuse a worker after an uncertain write.
            raise RuntimeError('Tracker timeout; preserve receipt and reconcile before continuing') from None
        if line is None:
            raise RuntimeError('Tracker worker stopped; receipt is preserved')
        result = json.loads(line)
        if not result.get('ok'):
            raise RuntimeError(result.get('error', 'Tracker operation failed'))
        return result['result']

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()


class Checkpoints:
    def __init__(self, base):
        self.base = Path(base)
        self.base.mkdir(parents=True, exist_ok=True)

    def read(self, packet):
        p = self.base / str(packet['id']) / 'state.json'
        if not p.exists():
            return {'id': packet['id'], 'company': packet['company'], 'title': packet['title'], 'status': 'pending'}
        state = json.loads(p.read_text(encoding='utf-8'))
        if (str(state['id']), state['company'], state['title']) != (str(packet['id']), packet['company'], packet['title']):
            raise RuntimeError('Checkpoint job identity changed')
        return state

    def write(self, packet, state, **changes):
        state.update(changes)
        state['checkpoint_at'] = datetime.now(timezone.utc).isoformat()
        save(self.base / str(packet['id']) / 'state.json', state)


@contextmanager
def batch_lock(path):
    """OS-owned lock releases on interruption; the diagnostic file can remain."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b' ')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise RuntimeError('This application batch is already running') from None
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            # Keep the locked byte intact while refreshing diagnostic metadata.
            stream.seek(1)
            stream.truncate()
            stream.write(json.dumps({'pid': os.getpid()}).encode())
            stream.flush()
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
