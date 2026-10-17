import base64
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import random
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zlib

import fakeredis
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from web.app import create_app, allowed_request
from web.broker import PREFIX, ENQUEUE, CLAIM, COMPLETE, Redis
from dashboard.remote_worker import Worker

ORIGIN = 'https://gecko.example'
PASSWORD = 'isolated-test-password-with-enough-length'
SECRET = 'test-worker-key-' + 'x'*40
HASH = generate_password_hash(PASSWORD, method='scrypt')


class Store:
    def __init__(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)

    def command(self, *args):
        return self.redis.execute_command(*args)

    def eval(self, script, keys, *args):
        return self.redis.eval(script, len(keys), *keys, *args)


class OnlineTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.app = create_app(self.store, dict(TESTING=True, SECRET_KEY='s'*48,
            GECKO_PASSWORD_HASH=HASH, GECKO_BRIDGE_SECRET=SECRET, GECKO_PUBLIC_URL=ORIGIN))
        self.client = self.app.test_client()
        self.login()

    def call(self, method, path, client=None, **kwargs):
        return (client or self.client).open(path, method=method, base_url=ORIGIN, **kwargs)

    def login(self, client=None):
        response = self.call('POST','/login',client=client, json={'password':PASSWORD},headers={'Origin':ORIGIN})
        self.assertEqual(response.status_code,200)
        return response

    def csrf(self, client=None):
        return self.call('GET','/cloud/connection',client=client).json['csrf']

    def worker_call(self, path, payload):
        return self.call('POST',path,json=payload,headers={'Authorization':'Bearer '+SECRET})

    def enqueue(self, path='/api/jobs', payload=None):
        self.worker_call('/bridge/next', {})
        method = 'POST' if payload is not None else 'GET'
        options = dict(json=payload,headers={'Origin':ORIGIN,'X-Gecko-Token':self.csrf()}) if payload is not None else {}
        response = self.call(method,path,**options)
        self.assertEqual(response.status_code,202,response.json)
        return response.json['ticket']

    def result(self, ticket):
        return self.call('GET','/cloud/result/'+ticket)

    def test_private_routes_and_secure_cookie(self):
        anonymous = self.app.test_client()
        self.assertEqual(self.call('GET','/',client=anonymous).status_code,302)
        self.assertEqual(self.call('GET','/api/jobs',client=anonymous).status_code,401)
        self.assertEqual(self.call('GET','/app.js',client=anonymous).status_code,401)
        response = self.call('GET','/login',client=anonymous)
        self.assertEqual(response.status_code,200)
        response.close()
        cookie = self.login(anonymous).headers['Set-Cookie']
        for attribute in ('Secure','HttpOnly','SameSite=Strict','__Host-gecko='):
            self.assertIn(attribute,cookie)

    def test_missing_configuration_and_wrong_host_fail_closed(self):
        self.assertEqual(self.client.get('/',base_url='https://evil.example').status_code,421)
        broken = create_app(self.store,dict(GECKO_PUBLIC_URL=ORIGIN, SECRET_KEY='',GECKO_BRIDGE_SECRET=SECRET,GECKO_PASSWORD_HASH=HASH))
        self.assertEqual(broken.test_client().get('/',base_url=ORIGIN).status_code,503)

    def test_signin_csrf_and_persistent_rate_limit(self):
        anonymous=self.app.test_client()
        self.assertEqual(self.call('POST','/login',client=anonymous,json={'password':PASSWORD},headers={'Origin':'https://evil.example'}).status_code,403)
        for _ in range(10):
            self.call('POST','/login',client=anonymous,json={'password':'wrong'},headers={'Origin':ORIGIN})
        self.assertEqual(self.call('POST','/login',client=anonymous,json={'password':PASSWORD},headers={'Origin':ORIGIN}).status_code,429)

    def test_mutation_requires_origin_and_session_token(self):
        self.assertEqual(self.call('POST','/api/edit',json={}).status_code,403)
        self.assertEqual(self.call('POST','/api/edit',json={},headers={'Origin':'https://evil.example','X-Gecko-Token':self.csrf()}).status_code,403)
        self.assertEqual(self.call('POST','/api/edit',json={},headers={'Origin':ORIGIN,'X-Gecko-Token':'incorrect'}).status_code,403)

    def test_offline_writes_are_not_queued(self):
        response=self.call('POST','/api/run',json={'action':'full'},headers={'Origin':ORIGIN,'X-Gecko-Token':self.csrf()})
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.store.command('LLEN',PREFIX+'queue'),0)

    def test_worker_authentication_is_separate(self):
        self.assertEqual(self.call('POST','/bridge/next',json={}).status_code,401)
        self.assertEqual(self.worker_call('/bridge/next',{}).status_code,204)
        self.assertTrue(self.call('GET','/cloud/connection').json['online'])

    def test_route_allowlist_and_payload_bounds(self):
        for path in ('https://evil.example/api/jobs','//evil.example/api/jobs','/api/resume?id=x&path=C:/secret','/api/jobs?x=1','/api/open-resume','/api/../../.env'):
            self.assertFalse(allowed_request('GET',path),path)
        self.assertFalse(allowed_request('POST','/api/run?command=anything'))
        self.assertTrue(allowed_request('GET','/api/job?id=test-job'))
        self.assertTrue(allowed_request('POST','/api/edit'))
        response=self.call('POST','/api/edit',json=['bad'],headers={'Origin':ORIGIN,'X-Gecko-Token':self.csrf()})
        self.assertEqual(response.status_code,400)

    def test_lua_claim_consumes_request_and_expired_commands_never_run(self):
        expired=self.enqueue('/api/run',{'action':'full'})
        raw=json.loads(self.store.command('GET',PREFIX+'request:'+expired));raw['deadline']=int(time.time())-1
        self.store.command('SET',PREFIX+'request:'+expired,json.dumps(raw),'EX',300)
        ticket=self.enqueue()
        claimed=self.worker_call('/bridge/next',{}).json
        self.assertEqual(claimed['id'],ticket)
        self.assertEqual(self.worker_call('/bridge/next',{}).status_code,204)
        self.assertEqual(self.result(ticket).status_code,202)

    def test_results_belong_to_requesting_session_and_are_not_exposed(self):
        ticket=self.enqueue()
        second=self.app.test_client();self.login(second)
        self.assertEqual(self.call('GET','/cloud/result/'+ticket,client=second).status_code,404)
        self.assertEqual(self.result('invalid').status_code,404)

    def test_job_token_is_replaced_and_completion_is_idempotent(self):
        ticket=self.enqueue();self.worker_call('/bridge/next',{})
        payload=Worker.error('unused');payload.update(status=200,body=base64.b64encode(zlib.compress(json.dumps({'jobs':[],'token':'local-secret'}).encode())).decode())
        self.assertEqual(self.worker_call('/bridge/complete/'+ticket,payload).status_code,200)
        self.assertEqual(self.worker_call('/bridge/complete/'+ticket,payload).status_code,200)
        response=self.result(ticket)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['token'],self.csrf())
        self.assertNotIn('local-secret',response.text)
        self.assertLessEqual(self.store.command('TTL',PREFIX+'request:'+ticket),120)

    def test_unclaimed_requests_cannot_be_completed(self):
        ticket=self.enqueue()
        self.assertEqual(self.worker_call('/bridge/complete/'+ticket,Worker.error('test')).status_code,410)

    def test_large_notes_are_transferred_completely_in_authorized_parts(self):
        ticket=self.enqueue();self.worker_call('/bridge/next',{})
        notes=random.Random(0).randbytes(1_000_000).hex()
        snapshot={'jobs':[{'id':'test-job','fields':{'Notes':notes}}]}
        result=dict(status=200,content_type='application/json',filename='',
                    body=base64.b64encode(zlib.compress(json.dumps(snapshot).encode())).decode())
        with tempfile.TemporaryDirectory() as folder:
            worker=Worker({'url':ORIGIN,'secret':SECRET},Path(folder)/'requests.sqlite3')
            with closing(sqlite3.connect(worker.journal)) as db:
                db.execute('INSERT INTO requests VALUES (?, ?, ?, ?)',(ticket,'done',json.dumps(result),time.time()));db.commit()
            def cloud(path,payload):
                response=self.worker_call(path,payload)
                self.assertEqual(response.status_code,200,response.json)
                return response.json
            worker.cloud=cloud
            worker.flush_results()
        metadata=self.result(ticket).json
        self.assertTrue(metadata['packed'])
        self.assertGreater(metadata['chunks'],1)
        self.assertEqual(metadata['csrf'],self.csrf())
        body=b''.join(self.call('GET',f'/cloud/chunk/{ticket}/{index}').data for index in range(metadata['chunks']))
        self.assertEqual(json.loads(zlib.decompress(body))['jobs'][0]['fields']['Notes'],notes)
        second=self.app.test_client();self.login(second)
        self.assertEqual(self.call('GET',f'/cloud/chunk/{ticket}/0',client=second).status_code,404)
        self.assertLessEqual(self.store.command('TTL',PREFIX+'request:'+ticket+':chunk:0'),120)

    def test_missing_parts_cannot_be_marked_complete(self):
        ticket=self.enqueue();self.worker_call('/bridge/next',{})
        result=dict(status=200,content_type='application/json',filename='',chunks=1)
        self.assertEqual(self.worker_call('/bridge/complete/'+ticket,result).status_code,409)
        self.assertEqual(self.result(ticket).status_code,202)

    def test_downloads_and_oversized_results(self):
        ticket=self.enqueue('/api/resume?id=test-job');self.worker_call('/bridge/next',{})
        payload=dict(status=200,content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',filename='Dave-Call+Test+00001.docx',body=base64.b64encode(zlib.compress(b'test-docx-bytes')).decode())
        self.worker_call('/bridge/complete/'+ticket,payload)
        response=self.result(ticket)
        self.assertEqual(response.data,b'test-docx-bytes')
        self.assertIn('attachment;',response.headers['Content-Disposition'])
        oversized=self.enqueue();self.worker_call('/bridge/next',{})
        payload.update(content_type='application/json',filename='',body=base64.b64encode(zlib.compress(b'x'*3_000_001)).decode())
        self.worker_call('/bridge/complete/'+oversized,payload)
        self.assertEqual(self.result(oversized).status_code,413)

    def test_logout_revokes_browser_session(self):
        response=self.call('POST','/cloud/logout',json={},headers={'Origin':ORIGIN,'X-Gecko-Token':self.csrf()})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.call('GET','/api/jobs').status_code,401)

    def test_worker_journal_prevents_replay_and_records_uncertain_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=Worker({'url':ORIGIN,'secret':SECRET},Path(folder)/'requests.sqlite3')
            item=dict(id='a'*32,method='POST',path='/api/run',payload={'action':'full'},deadline=int(time.time())+45)
            with patch.object(worker,'local_request',return_value=Worker.error('test')) as execute:
                self.assertEqual(worker.execute(item),worker.execute(item));execute.assert_called_once()
            with closing(sqlite3.connect(worker.journal)) as db:
                db.execute('INSERT INTO requests VALUES (?, ?, NULL, ?)',('b'*32,'started',time.time()));db.commit()
            item['id']='b'*32
            with patch.object(worker,'local_request') as execute:
                result=worker.execute(item);execute.assert_not_called()
                self.assertIn('unconfirmed',zlib.decompress(base64.b64decode(result['body'])).decode())

    def test_worker_rejects_expired_or_arbitrary_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            worker=Worker({'url':ORIGIN,'secret':SECRET},Path(folder)/'requests.sqlite3')
            item=dict(id='a'*32,method='POST',path='/api/run',payload={},deadline=int(time.time())-1)
            with patch.object(worker,'local_request') as execute:
                worker.execute(item);execute.assert_not_called()
            item['path']='https://evil.example/'
            with self.assertRaises(ValueError):
                worker.execute(item)

    def test_full_gateway_worker_local_api_roundtrip_without_live_tracker(self):
        calls=[]
        class Local(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def reply(self,data):
                encoded=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(encoded)));self.end_headers();self.wfile.write(encoded)
            def do_GET(self):
                if self.path=='/api/health':return self.reply({'app':'gecko-dashboard'})
                return self.reply({'jobs':[{'id':'test-job','notes':'before'}],'token':'local-token'})
            def do_POST(self):
                calls.append(dict(path=self.path,origin=self.headers.get('Origin'),token=self.headers.get('X-Gecko-Token'),payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.reply({'saved':True})
        server=ThreadingHTTPServer(('127.0.0.1',0),Local)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                worker=Worker({'url':ORIGIN,'secret':SECRET},Path(folder)/'requests.sqlite3',server.server_port)
                def cloud(path,payload):
                    response=self.worker_call(path,payload)
                    self.assertIn(response.status_code,(200,204))
                    return response.json if response.status_code!=204 else None
                worker.cloud=cloud
                worker.tick()
                ticket=self.enqueue()
                worker.tick()
                snapshot=self.result(ticket).json
                self.assertEqual(snapshot['jobs'][0]['id'],'test-job')
                self.assertNotIn('local-token',json.dumps(snapshot))
                ticket=self.enqueue('/api/edit',{'id':'test-job','action':'details','notes':'after'})
                worker.tick()
                self.assertTrue(self.result(ticket).json['saved'])
                self.assertEqual(len(calls),1)
                self.assertEqual(calls[0]['origin'],f'http://127.0.0.1:{server.server_port}')
                self.assertEqual(calls[0]['token'],'local-token')
                self.assertEqual(calls[0]['payload']['notes'],'after')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)


if __name__=='__main__':
    unittest.main()
