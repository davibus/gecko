"""Outbound-only remote actions. Does not publish or rebind the local server."""
import argparse
import base64
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit, parse_qs, unquote
from urllib.request import Request, urlopen
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from web.app import allowed_request

MAX_RESULT = 30_000_000


def load_config(path):
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    url = urlsplit(data.get('url', ''))
    if url.scheme != 'https' or not url.hostname or url.path or url.query or url.fragment or url.username:
        raise ValueError('The configured website must be an HTTPS origin without a path.')
    if not isinstance(data.get('secret'), str) or len(data['secret']) < 32:
        raise ValueError('The secure website connection key is missing.')
    return data


class Worker:
    def __init__(self, config, journal, port=8765):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('Invalid local dashboard port.')
        self.config, self.port = config, port
        self.local = f'http://127.0.0.1:{port}'
        self.token = None
        journal.parent.mkdir(parents=True, exist_ok=True)
        self.journal = journal
        with closing(sqlite3.connect(journal)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, state TEXT NOT NULL, result TEXT, created REAL NOT NULL)')
            db.commit()

    def cloud(self, path, payload):
        body = json.dumps(payload).encode()
        req = Request(self.config['url']+path, data=body, headers={
            'Authorization':'Bearer '+self.config['secret'], 'Content-Type':'application/json'})
        # Never follow redirects carrying a worker credential to another origin.
        from urllib.request import build_opener, HTTPRedirectHandler
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with build_opener(NoRedirect).open(req, timeout=25) as response:
            return None if response.status == 204 else json.load(response)

    def local_request(self, method, path, payload=None):
        if not allowed_request(method, path):
            raise ValueError('Remote action is outside the dashboard allowlist.')
        if method == 'POST' and self.token is None:
            self.read_token()
        headers = {'Origin':self.local}
        data = None
        if method == 'POST':
            headers.update({'Content-Type':'application/json', 'X-Gecko-Token':self.token})
            data = json.dumps(payload).encode()
            if len(data)>100000:
                raise ValueError('Remote action is too large.')
        req = Request(self.local+path, data=data, headers=headers, method=method)
        try:
            response = urlopen(req, timeout=115)
        except HTTPError as error:
            response = error
        with response:
            body = response.read(MAX_RESULT+1)
            if len(body)>MAX_RESULT:
                raise ValueError('This result is too large to display online.')
            if path == '/api/jobs' and response.status == 200:
                snapshot = json.loads(body)
                self.token = snapshot.pop('token', None)
                body = json.dumps(snapshot).encode()
            if response.status == 403:
                self.token = None  # A later explicit action can acquire the new token. Never replay this one.
            filename = ''
            disposition = response.headers.get('Content-Disposition','')
            match = re.search("filename\\*=UTF-8''([^;]+)", disposition, re.I)
            if match:
                filename = unquote(match[1])
            result = dict(status=response.status, body=base64.b64encode(zlib.compress(body)).decode(),
                          content_type=response.headers.get('Content-Type', 'application/json'), filename=filename)
            if len(result['body'])>15_360_000:
                raise ValueError('This result is too large to send online.')
            return result

    def read_token(self):
        self.local_request('GET', '/api/jobs')
        if not self.token:
            raise ValueError('The local workspace is not ready for changes.')

    def execute(self, item):
        if (not isinstance(item, dict) or not re.fullmatch('[0-9a-f]{32}', str(item.get('id','')))
                or not allowed_request(item.get('method'), item.get('path',''))):
            raise ValueError('Invalid remote request.')
        command_id = item['id']
        with closing(sqlite3.connect(self.journal)) as db:
            # Commit before execution. A crash is uncertain and cannot cause a second run/edit.
            cursor = db.execute('INSERT OR IGNORE INTO requests VALUES (?, ?, NULL, ?)', (command_id, 'started', time.time()))
            db.commit()
            if cursor.rowcount == 0:
                row = db.execute('SELECT result FROM requests WHERE id=?', (command_id,)).fetchone()
                if row[0]:
                    return json.loads(row[0])
                return self.error('The earlier result is unconfirmed. Refresh the dashboard before trying again.')
        try:
            if type(item.get('deadline')) is not int or item['deadline'] < time.time():
                result = self.error('This request expired before execution. No action was taken.')
            elif item['method'] == 'POST' and not isinstance(item.get('payload'), dict):
                result = self.error('Expected a JSON object. No action was taken.')
            else:
                result = self.local_request(item['method'], item['path'], item.get('payload'))
        except Exception:
            result = self.error('The local result is unconfirmed. Refresh to verify the current state before repeating this action.')
        with closing(sqlite3.connect(self.journal)) as db:
            db.execute('UPDATE requests SET state=?, result=? WHERE id=?', ('done',json.dumps(result),command_id))
            db.commit()
        return result

    @staticmethod
    def error(message):
        return dict(status=503, content_type='application/json', filename='',
                    body=base64.b64encode(zlib.compress(json.dumps({'error':message}).encode())).decode())

    def flush_results(self):
        with closing(sqlite3.connect(self.journal)) as db:
            rows = db.execute("SELECT id, result FROM requests WHERE state='done' ORDER BY created LIMIT 20").fetchall()
        for command_id, raw in rows:
            try:
                result = json.loads(raw)
                if len(result['body']) > 450000:
                    packed = result.pop('body')
                    parts = [packed[i:i+480000] for i in range(0,len(packed),480000)]
                    for index, part in enumerate(parts):
                        self.cloud('/bridge/chunk/'+command_id+'/'+str(index), {'body':part})
                    result['chunks'] = len(parts)
                self.cloud('/bridge/complete/'+command_id, result)
            except HTTPError as error:
                if error.code != 410:
                    raise
            with closing(sqlite3.connect(self.journal)) as db:
                db.execute("UPDATE requests SET state='acknowledged', result=NULL WHERE id=?",(command_id,))
                db.commit()

    def tick(self):
        # A verified local health response is required before publishing online availability.
        with urlopen(self.local+'/api/health', timeout=4) as response:
            if json.load(response).get('app') != 'gecko-dashboard':
                raise ValueError('The local service is not the Gecko dashboard.')
        self.flush_results()
        item = self.cloud('/bridge/next', {})
        if item:
            self.execute(item)
            self.flush_results()
        return bool(item)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT/'.secrets/gecko-web-worker.json')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config = load_config(args.config)
    journal = ROOT/'scratch/dashboard/remote-requests.sqlite3'
    # Share the existing Windows byte-range lock approach to prevent duplicate worker processes.
    import msvcrt
    lock = ROOT/'scratch/dashboard/remote-worker.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a+b') as handle:
        if handle.seek(0, 2) == 0:
            handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise SystemExit('The Gecko online connection is already running.')
        worker = Worker(config, journal, args.port)
        print('Gecko online connection started. No workflow runs until requested in the dashboard.', flush=True)
        while True:
            try:
                busy = worker.tick()
                if args.once:
                    return
                time.sleep(0.3 if busy else 4)
            except Exception as error:
                reason = 'HTTP '+str(error.code) if isinstance(error,HTTPError) else type(error).__name__
                print('Connection unavailable ('+reason+'). No action will be replayed.', flush=True)
                if args.once:
                    raise SystemExit(1)
                time.sleep(12)


if __name__ == '__main__':
    main()
