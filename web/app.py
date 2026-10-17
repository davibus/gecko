"""Private Vercel gateway for the existing Windows Gecko Main workspace."""
import base64
from datetime import timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from urllib.parse import urlsplit, parse_qs
import zlib

from flask import Flask, Response, jsonify, redirect, request, send_from_directory, session
from werkzeug.security import check_password_hash
from werkzeug.exceptions import HTTPException

try:
    from .broker import Redis, StoreError, PREFIX, ENQUEUE, CLAIM, COMPLETE, LIMIT
except ImportError:
    from broker import Redis, StoreError, PREFIX, ENQUEUE, CLAIM, COMPLETE, LIMIT

ASSETS = Path(__file__).parent / 'assets'
READS = {'/api/health', '/api/jobs', '/api/job', '/api/activity', '/api/resume', '/api/manual-import'}
WRITES = {'/api/stop', '/api/manual', '/api/manual-import', '/api/edit', '/api/run', '/api/columns', '/api/export'}
FILES = {'app.js', 'manual.js', 'filters.js', 'style.css'}
ID = re.compile(r'^[0-9a-f]{32}$')
MAX_RESULT = 3_000_000


def device_access_token(secret, origin):
    """Purpose- and origin-bound setup key; never include it in HTTP paths or queries."""
    return hmac.new(secret.encode(), ('gecko-device-connect-v1:'+origin).encode(), hashlib.sha256).hexdigest()


def allowed_request(method, path):
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment or '\\' in path:
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    if method == 'GET':
        if parsed.path not in READS:
            return False
        if parsed.path in {'/api/job', '/api/resume'}:
            return set(query) == {'id'} and len(query['id']) == 1 and 0 < len(query['id'][0]) <= 300
        return not parsed.query
    return method == 'POST' and parsed.path in WRITES and not parsed.query


def create_app(store=None, config=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=os.environ.get('GECKO_SESSION_SECRET', ''),
        GECKO_PASSWORD_HASH=os.environ.get('GECKO_PASSWORD_HASH', ''),
        GECKO_BRIDGE_SECRET=os.environ.get('GECKO_BRIDGE_SECRET', ''),
        GECKO_ACCESS_MODE=os.environ.get('GECKO_ACCESS_MODE', 'device'),
        GECKO_PUBLIC_URL=(os.environ.get('GECKO_PUBLIC_URL') or
            ('https://' + os.environ['VERCEL_PROJECT_PRODUCTION_URL'] if os.environ.get('VERCEL_PROJECT_PRODUCTION_URL') else '')).rstrip('/'),
        SESSION_COOKIE_NAME='__Host-gecko', SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True, SESSION_COOKIE_SAMESITE='Strict',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        SESSION_REFRESH_EACH_REQUEST=False, MAX_CONTENT_LENGTH=1_400_000)
    if config:
        app.config.update(config)
    if app.config['GECKO_ACCESS_MODE'] == 'device':
        app.config.update(PERMANENT_SESSION_LIFETIME=timedelta(days=365), SESSION_REFRESH_EACH_REQUEST=True)

    def db():
        return store if store is not None else Redis()

    def owner():
        return hmac.new(app.secret_key.encode(), session['sid'].encode(), hashlib.sha256).hexdigest()

    def same_origin():
        return (request.headers.get('Origin') == app.config['GECKO_PUBLIC_URL']
                and request.headers.get('Sec-Fetch-Site') != 'cross-site')

    def worker():
        expected = 'Bearer ' + app.config['GECKO_BRIDGE_SECRET']
        return hmac.compare_digest(request.headers.get('Authorization', ''), expected)

    @app.before_request
    def guard():
        public = urlsplit(app.config['GECKO_PUBLIC_URL'])
        if (public.scheme != 'https' or not public.hostname or public.path or public.query
                or public.fragment or public.username
                or len(app.config['SECRET_KEY']) < 32
                or len(app.config['GECKO_BRIDGE_SECRET']) < 32
                or app.config['GECKO_ACCESS_MODE'] not in {'device','password'}
                or (app.config['GECKO_ACCESS_MODE']=='password'
                    and not app.config['GECKO_PASSWORD_HASH'].startswith('scrypt:'))):
            return jsonify(error='Gecko online setup is incomplete. Configure the website environment variables.'), 503
        if request.host != public.netloc:
            return jsonify(error='Open your configured Gecko website address.'), 421
        if request.path.startswith('/bridge/'):
            if not worker():
                return jsonify(error='Worker authentication required.'), 401
            return None
        device = app.config['GECKO_ACCESS_MODE'] == 'device'
        if request.path in {'/login', '/login.js', '/login.css', '/connect', '/device.js', '/cloud/connect'}:
            return None
        if device and (request.path == '/' or request.path.lstrip('/') in FILES | {'cloud.js'}):
            return None
        if not device and session.get('access') == 'device':
            session.clear()
        if not session.get('sid'):
            if request.path == '/':
                return redirect('/login')
            return jsonify(error='Open your private Gecko setup link once on this device.' if device else 'Please sign in again.'), 401
        if request.method == 'POST':
            if not same_origin() or not hmac.compare_digest(
                    request.headers.get('X-Gecko-Token', ''), session.get('csrf', '')):
                return jsonify(error='Reload Gecko before making changes.'), 403

    @app.after_request
    def headers(response):
        response.headers.update({
            'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
            'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            'Strict-Transport-Security': 'max-age=31536000'})
        return response

    @app.errorhandler(Exception)
    def failure(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.description), error.code
        if isinstance(error, StoreError):
            app.logger.error('Temporary request store: %s', error)
        else:
            app.logger.error('Gateway request failed: %s',type(error).__name__)
        # Do not send provider URLs, tokens, request bodies, or local errors to logs/browser.
        return jsonify(error='Gecko could not reach its secure connection. Refresh to check the current state; do not repeat an uncertain edit or run.'), 503

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if app.config['GECKO_ACCESS_MODE'] == 'device':
            return redirect('/') if request.method=='GET' else (jsonify(error='Use your private Gecko setup link.'),404)
        if request.method == 'GET':
            return send_from_directory(ASSETS, 'login.html')
        if not same_origin() or not request.is_json:
            return jsonify(error='Open the sign-in page on your Gecko website.'), 403
        # Vercel supplies this trusted client address; do not use user-controlled X-Forwarded-For.
        address = request.headers.get('X-Vercel-Forwarded-For') or request.remote_addr or 'unknown'
        key = PREFIX + 'login:' + hashlib.sha256(address.encode()).hexdigest()
        if db().eval(LIMIT, [PREFIX+'login:global'], 900) > 100:
            return jsonify(error='Too many sign-in attempts. Try again in 15 minutes.'), 429
        if db().eval(LIMIT, [key], 900) > 10:
            return jsonify(error='Too many sign-in attempts. Try again in 15 minutes.'), 429
        payload = request.get_json()
        password = payload.get('password', '') if isinstance(payload, dict) else ''
        if not isinstance(password, str) or len(password) > 1024 or not check_password_hash(app.config['GECKO_PASSWORD_HASH'], password):
            return jsonify(error='The password did not match.'), 401
        session.clear()
        session.update(sid=secrets.token_hex(32), csrf=secrets.token_urlsafe(32), access='password')
        session.permanent = True
        return jsonify(ok=True)

    @app.get('/connect')
    def connect_page():
        if app.config['GECKO_ACCESS_MODE'] != 'device' or session.get('sid'):
            return redirect('/')
        return send_from_directory(ASSETS, 'device.html')

    @app.post('/cloud/connect')
    def connect_device():
        if app.config['GECKO_ACCESS_MODE'] != 'device':
            return jsonify(error='Device setup is not enabled.'),404
        if not same_origin() or not request.is_json or (request.content_length or 0)>1000:
            return jsonify(error='Open the private setup link on your Gecko website.'),403
        payload = request.get_json()
        token = payload.get('token','') if isinstance(payload,dict) else ''
        if (not isinstance(token,str) or not re.fullmatch('[0-9a-f]{64}',token)
                or not hmac.compare_digest(token, device_access_token(app.secret_key, app.config['GECKO_PUBLIC_URL']))):
            return jsonify(error='This device setup link is invalid. Use the link saved on your Gecko computer.'),401
        session.clear()
        session.update(sid=secrets.token_hex(32),csrf=secrets.token_urlsafe(32),access='device')
        session.permanent = True
        return jsonify(ok=True)

    @app.post('/cloud/logout')
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get('/cloud/connection')
    def connection():
        return jsonify(online=bool(db().command('GET', PREFIX + 'heartbeat')), csrf=session['csrf'])

    @app.route('/api/<path:unused>', methods=['GET', 'POST'])
    def submit(unused):
        path = request.full_path.rstrip('?')
        if not allowed_request(request.method, path):
            return jsonify(error='This action is not available online.'), 404
        payload = None
        if request.method == 'POST':
            if not request.is_json or request.content_length is None or request.content_length > 100000:
                return jsonify(error='Expected a bounded JSON request.'), 400
            payload = request.get_json()
            if not isinstance(payload, dict):
                return jsonify(error='Expected a JSON object.'), 400
        command_id = secrets.token_hex(16)
        item = dict(id=command_id, owner=owner(), state='queued', deadline=int(time.time()) + 45,
                    method=request.method, path=path, payload=payload)
        accepted = db().eval(ENQUEUE, [PREFIX+'queue', PREFIX+'request:'+command_id, PREFIX+'heartbeat'],
                             command_id, json.dumps(item))
        if accepted == 0:
            return jsonify(error='Your Gecko computer is offline. Wake it and start the Gecko online connection, then refresh.'), 503
        if accepted == -1:
            return jsonify(error='Gecko is handling too many requests. Please wait and refresh.'), 429
        return jsonify(ticket=command_id), 202

    @app.get('/cloud/result/<command_id>')
    def result(command_id):
        if not ID.fullmatch(command_id):
            return jsonify(error='Request not found.'), 404
        raw = db().command('GET', PREFIX+'request:'+command_id)
        if not raw:
            return jsonify(error='The request expired. Refresh to verify the current state before trying again.'), 410
        item = json.loads(raw)
        if not hmac.compare_digest(item['owner'], owner()):
            return jsonify(error='Request not found.'), 404
        if item['state'] != 'done':
            if time.time() > item['deadline'] + (120 if item['state'] == 'claimed' else 0):
                return jsonify(error='The result is unconfirmed. Refresh to check whether the change or run started before trying again.'), 409
            return jsonify(state=item['state']), 202
        data = item['result']
        if data.get('chunks'):
            return jsonify(packed=True, chunks=data['chunks'], status=data['status'],
                           content_type=data['content_type'], filename=data.get('filename',''),
                           csrf=session['csrf'] if item['path']=='/api/jobs' else '')
        decompressor = zlib.decompressobj()
        body = decompressor.decompress(base64.b64decode(data['body'], validate=True), MAX_RESULT + 1)
        if len(body) > MAX_RESULT or not decompressor.eof:
            return jsonify(error='This result is too large to display online.'), 413
        if item['path'] == '/api/jobs' and data['status'] == 200:
            snapshot = json.loads(body)
            snapshot['token'] = session['csrf']
            body = json.dumps(snapshot).encode()
        response = Response(body, status=data['status'], content_type=data.get('content_type', 'application/json'))
        if data.get('filename'):
            from urllib.parse import quote
            response.headers['Content-Disposition'] = "attachment; filename*=UTF-8''" + quote(data['filename'])
        return response

    @app.get('/cloud/chunk/<command_id>/<int:index>')
    def read_chunk(command_id, index):
        if not ID.fullmatch(command_id) or not 0 <= index < 32:
            return jsonify(error='Request not found.'), 404
        raw = db().command('GET', PREFIX+'request:'+command_id)
        if not raw:
            return jsonify(error='The response expired. Refresh to check the current state.'), 410
        item = json.loads(raw)
        if not hmac.compare_digest(item['owner'], owner()):
            return jsonify(error='Request not found.'), 404
        if item['state'] != 'done' or index >= item['result'].get('chunks',0):
            return jsonify(error='Request not found.'), 404
        chunk = db().command('GET', PREFIX+'request:'+command_id+':chunk:'+str(index))
        if not chunk:
            return jsonify(error='The response expired. Refresh to check the current state.'), 410
        return Response(base64.b64decode(chunk,validate=True),content_type='application/octet-stream')

    @app.post('/bridge/next')
    def next_command():
        raw = db().eval(CLAIM, [PREFIX+'queue', PREFIX+'heartbeat'],
                        str(int(time.time())), PREFIX+'request:', int(time.time()))
        if not raw:
            return Response(status=204)
        item = json.loads(raw)
        return jsonify({k:item[k] for k in ('id','deadline','method','path','payload')})

    @app.post('/bridge/complete/<command_id>')
    def complete(command_id):
        if not ID.fullmatch(command_id) or not request.is_json:
            return jsonify(error='Invalid result.'), 400
        data = request.get_json()
        if (not isinstance(data, dict) or type(data.get('status')) is not int
                or not 200 <= data['status'] <= 599
                or data.get('content_type') not in {'application/json; charset=utf-8', 'application/json',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}):
            return jsonify(error='Invalid result.'), 400
        if 'chunks' in data:
            if type(data['chunks']) is not int or not 1 <= data['chunks'] <= 32 or 'body' in data:
                return jsonify(error='Invalid chunk count.'), 400
        elif not isinstance(data.get('body'), str) or len(data['body']) > 1_300_000:
            return jsonify(error='Invalid result body.'), 400
        filename = data.get('filename', '')
        if not isinstance(filename, str) or len(filename) > 200 or any(c in filename for c in '\r\n/\\'):
            return jsonify(error='Invalid download filename.'), 400
        completed = db().eval(COMPLETE, [PREFIX+'request:'+command_id], json.dumps(data))
        if completed == -1:
            return jsonify(error='Upload all response parts before completing the request.'), 409
        if not completed:
            return jsonify(error='Request expired; it will not be repeated.'), 410
        return jsonify(ok=True)

    @app.post('/bridge/chunk/<command_id>/<int:index>')
    def write_chunk(command_id, index):
        if not ID.fullmatch(command_id) or not 0 <= index < 32 or not request.is_json:
            return jsonify(error='Invalid response part.'), 400
        payload = request.get_json()
        part = payload.get('body') if isinstance(payload,dict) else None
        if not isinstance(part,str) or not 0 < len(part) <= 480000:
            return jsonify(error='Invalid response part.'), 400
        try:
            base64.b64decode(part, validate=True)
        except ValueError:
            return jsonify(error='Invalid response part.'), 400
        raw = db().command('GET', PREFIX+'request:'+command_id)
        if not raw:
            return jsonify(error='Request expired; it will not be repeated.'), 410
        item = json.loads(raw)
        if item['state'] == 'done':
            return jsonify(ok=True)
        if item['state'] != 'claimed':
            return jsonify(error='Request was not claimed.'), 409
        db().command('SET', PREFIX+'request:'+command_id+':chunk:'+str(index), part, 'EX', 300)
        return jsonify(ok=True)

    @app.get('/')
    def home():
        markup = (ASSETS/'index.html').read_text(encoding='utf-8')
        markup = markup.replace('<html lang="en">', '<html lang="en" data-access-mode="'+app.config['GECKO_ACCESS_MODE']+'">',1)
        return Response(markup,content_type='text/html; charset=utf-8')

    @app.get('/<name>')
    def assets(name):
        if name not in FILES | {'cloud.js', 'login.js', 'login.css', 'device.js'}:
            return jsonify(error='Not found.'), 404
        return send_from_directory(ASSETS, name)

    return app


app = create_app()
