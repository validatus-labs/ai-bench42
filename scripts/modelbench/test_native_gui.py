"""Native UI transport checks; synthetic local HTTP only, never a model request."""
import http.client
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_gui as gui
import worker


class Reply:
    status=200
    def __init__(self):self.stream=io.BytesIO(b'{"synthetic":true}')
    def getheaders(self):return [('Content-Type','application/json')]
    def read1(self,size):return self.stream.read(size)


class NativeGuiTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];calls=self.calls
        class Unix:
            def __init__(self,*args):pass
            def request(self,*args):calls.append(args)
            def getresponse(self):return Reply()
            def close(self):pass
        self.patch=patch.object(gui,'Unix',Unix);self.patch.start();self.addCleanup(self.patch.stop)
        self.server=gui.ViewServer(('127.0.0.1',0),gui.View);self.server.auth='Basic synthetic';self.server.fd=42;self.server.workspace='/private/own/workspace'
        thread=threading.Thread(target=self.server.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def request(self,path,auth='Basic synthetic'):
        client=http.client.HTTPConnection(*self.server.server_address,timeout=3)
        try:client.request('GET',path,headers={'Authorization':auth});reply=client.getresponse();return reply.status,reply.read()
        finally:client.close()

    def test_connection_deadline_and_admission_are_bounded(self):
        import socket,time
        self.assertEqual(self.server.maximum_connections,16)
        self.server.idle_timeout=.1
        client=socket.create_connection(self.server.server_address,timeout=1)
        try:
            client.sendall(b'GET /global/health HTTP/1.1\r\n')
            self.assertEqual(client.recv(1),b'')
        finally:client.close()
        held=[]
        try:
            while self.server.limit.acquire(False):held.append(1)
            client=socket.create_connection(self.server.server_address,timeout=1)
            try:client.sendall(b'GET /global/health HTTP/1.0\r\n\r\n');self.assertEqual(client.recv(1),b'')
            except ConnectionResetError:pass
            finally:client.close()
        finally:
            for _ in held:self.server.limit.release()
        self.assertEqual(self.calls,[])

    def test_wrong_ui_auth_never_reaches_worker(self):
        self.assertEqual(self.request('/global/health','Basic wrong')[0],401);self.assertEqual(self.calls,[])

    def test_absolute_http_proxy_request_denied(self):
        self.assertEqual(self.request('http://example.invalid/')[0],403);self.assertEqual(self.calls,[])

    def test_coordinator_control_route_is_not_exposed_to_gui(self):
        gui.inspection_only({'channels':{}})
        for channels in [None,{'inference':{'socket':'/private/inference.sock'}},{'browser':{'socket':'/private/browser.sock'}}]:
            with self.assertRaisesRegex(worker.Blocked,'Inspection forbids'):gui.inspection_only({'channels':channels})
        self.assertEqual(self.request('/__modelbench/qualification')[0],403);self.assertEqual(self.calls,[])

    def test_only_own_directory_is_mapped_into_worker(self):
        status,body=self.request('/session?directory=%2Fprivate%2Fown%2Fworkspace');self.assertEqual(status,200)
        self.assertEqual(self.calls[0][1],'/session?directory=%2Fworkspace')
        self.assertEqual(json.loads(body),{'synthetic':True})
        self.calls.clear();self.assertEqual(self.request('/session?directory=%2Fother%2Frun')[0],502);self.assertEqual(self.calls,[])

    def test_completed_backend_reattaches_without_service_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'config.json';path.write_text('{}')
            actual={'ActiveState':'active','MainPID':'123','InvocationID':'same'}
            worker.write(root/'backend-ready.json',{'status':'synthetic'})
            worker.write(root/'backend-receipt.json',{'configuration_sha256':worker.digest(path),'unit_state':actual,'ready_sha256':worker.digest(root/'backend-ready.json')})
            with patch.object(gui,'state',return_value=actual),patch.object(gui.subprocess,'run') as command:
                gui.ensure(path,{'run_id':'synthetic'},root);command.assert_not_called()
            with patch.object(gui,'state',return_value=dict(actual,ActiveState='failed')),patch.object(gui.subprocess,'run') as command:
                with self.assertRaisesRegex(worker.Blocked,'no automatic restart'):gui.ensure(path,{'run_id':'synthetic'},root)
                command.assert_not_called()
            with patch.object(gui,'state',return_value=actual),patch.object(gui.subprocess,'run') as command:
                (root/'backend-ready.json').write_text('{"status":"tampered"}')
                with self.assertRaisesRegex(worker.Blocked,'no automatic restart'):gui.ensure(path,{'run_id':'synthetic'},root)
                command.assert_not_called()

    def test_trial_lifetime_is_pinned_and_inspection_stays_bounded(self):
        self.assertEqual(gui.lifetime({'mode':'C00_TOOL_CANARY'}),900)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'run.json';worker.write(p,{'execution_wall_seconds':None})
            value={'mode':'GATED_NATIVE_TRIAL','record':{'path':str(p),'sha256':worker.digest(p)}}
            self.assertIsNone(gui.lifetime(value))
            p.write_bytes(worker.encoded({'execution_wall_seconds':True}));value['record']['sha256']=worker.digest(p)
            with self.assertRaises(worker.Blocked):gui.lifetime(value)
        self.assertEqual(gui.run_directory({'run_directory':'seed-1'},Path('/synthetic')),Path('/synthetic/seed-1'))
        for name in ['../another-run','/private','seed/other','']:
            with self.assertRaises(worker.Blocked):gui.run_directory({'run_directory':name},Path('/synthetic'))


if __name__=='__main__':unittest.main()
