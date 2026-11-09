import http.client
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ['QINGPAO_DATA'] = tempfile.mkdtemp(prefix='qingpao-test-')
spec = importlib.util.spec_from_file_location('app', Path(__file__).resolve().parents[1] / 'server' / 'app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
app.init_db()
server = ThreadingHTTPServer(('127.0.0.1', 0), app.App)
threading.Thread(target=server.serve_forever, daemon=True).start()

def request(method, path, payload=None, cookie=None, headers=None):
    conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
    h = dict(headers or {})
    if cookie: h['Cookie'] = cookie
    if isinstance(payload, dict): payload=json.dumps(payload).encode(); h['Content-Type']='application/json'
    conn.request(method,path,payload,h)
    response=conn.getresponse(); raw=response.read(); result=(response.status,dict(response.getheaders()),json.loads(raw) if response.getheader('Content-Type','').startswith('application/json') else raw)
    conn.close(); return result

class Flow(unittest.TestCase):
    def test_pair_message_and_attachment(self):
        _,ha,a=request('POST','/api/register',{'username':'alice','password':'test-password'})
        _,hb,b=request('POST','/api/register',{'username':'bob','password':'test-password'})
        ca=ha['Set-Cookie'].split(';')[0]; cb=hb['Set-Cookie'].split(';')[0]
        self.assertEqual(request('GET','/api/me',cookie=ca)[2]['user']['id'],a['user']['id'])
        code=request('POST','/api/pair-code',cookie=ca)[2]['code']
        self.assertEqual(request('POST','/api/pair',{'code':code},cb)[0],200)
        mid=request('POST','/api/messages',{'to':b['user']['id'],'body':'secret','burn':True},ca)[2]['id']
        self.assertEqual(request('GET','/api/messages?with='+str(a['user']['id']),cookie=cb)[2]['messages'][0]['body'],'')
        self.assertEqual(request('POST','/api/messages/read',{'id':mid},ca)[0],404)
        self.assertEqual(request('POST','/api/messages/read',{'id':mid},cb)[2]['body'],'secret')
        self.assertEqual(request('POST','/api/messages/read',{'id':mid},cb)[0],404)
        self.assertEqual(request('POST','/api/attachments',b'example',ca,{'X-Recipient-Id':str(b['user']['id']),'X-File-Name':'test.txt'})[0],200)
        msg=request('GET','/api/messages?with='+str(a['user']['id']),cookie=cb)[2]['messages'][0]
        self.assertEqual(request('GET','/api/attachments/'+msg['attachment'],cookie=cb)[2],b'example')
        self.assertEqual(request('GET','/api/attachments/'+msg['attachment'])[0],401)

if __name__=='__main__': unittest.main()
