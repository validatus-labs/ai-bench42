#!/usr/bin/env python3
"""In-worker Kilo server and private Unix UI relay; no inference authorization.

native_gui_inner.py
|-- stdin         ephemeral GUI password; never argv/log/configuration
|-- native probe  same worker denials, privileges and namespace evidence
|-- Kilo serve    existing binary, private home/state, local provider only
`-- UI socket    private build/.kilo-ui/kilo.sock, owned-child cleanup
"""
import base64
import contextlib
import http.client
from http.server import BaseHTTPRequestHandler
import io
import json
import os
from pathlib import Path
import signal
import socketserver
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

sys.path.insert(0,'/opt/modelbench')
import worker_inner as worker


class Relay(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self,*args):pass
    def do_GET(self):self.forward()
    def do_POST(self):self.forward()
    def do_PATCH(self):self.forward()
    def do_DELETE(self):self.forward()
    def do_PUT(self):self.forward()
    def do_OPTIONS(self):self.forward()
    def forward(self):
        connection=None
        try:
            self.connection.settimeout(30)
            if self.path=='/__modelbench/qualification':
                data=json.dumps(self.server.qualification).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
            if not self.path.startswith('/') or self.path.startswith('//') or urlsplit(self.path).netloc:raise ValueError('Invalid UI route')
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Encoding'):raise ValueError('Encoded request denied')
            lengths=self.headers.get_all('Content-Length',[])
            if len(lengths)>1:raise ValueError('Duplicate request length')
            length=int(lengths[0]) if lengths else 0
            if not 0<=length<=2*1024*1024:raise ValueError('UI request bound exceeded')
            raw=self.rfile.read(length)
            if len(raw)!=length:raise ValueError('Truncated UI request')
            connection=http.client.HTTPConnection('127.0.0.1',47811,timeout=120)
            connection.request(self.command,self.path,raw,{'Content-Type':'application/json','Authorization':self.server.auth,'Connection':'close'})
            reply=connection.getresponse();self.send_response(reply.status)
            for key,value in reply.getheaders():
                if key.lower() in {'content-type','content-length','cache-control'}:self.send_header(key,value)
            self.end_headers();total=0
            while chunk:=reply.read1(16384):
                total+=len(chunk)
                if total>32*1024*1024:raise ValueError('UI response bound exceeded')
                self.wfile.write(chunk);self.wfile.flush()
        except (OSError,ValueError,http.client.HTTPException):
            with contextlib.suppress(OSError):self.send_error(502,'Private worker UI unavailable')
        finally:
            if connection:connection.close()
            self.close_connection=True


class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
    daemon_threads=True
    def server_bind(self):self.limit=threading.BoundedSemaphore(16);super().server_bind()
    idle_timeout=15
    def get_request(self):
        request,address=super().get_request();request.settimeout(self.idle_timeout);return request,address
    def process_request(self,request,address):
        if not self.limit.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.limit.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.limit.release()


def main():
    value=json.loads(sys.stdin.read(16384));password=value['password']
    if not isinstance(password,str) or not 24<=len(password)<=256:raise ValueError('Missing ephemeral UI credential')
    # Run actual denial checks in this persistent worker, not another namespace.
    old=sys.stdin;out=io.StringIO()
    try:
        sys.stdin=io.StringIO(json.dumps(value['probe']))
        with contextlib.redirect_stdout(out):code=worker.probe()
    finally:sys.stdin=old
    qualification=json.loads(out.getvalue())
    if code:raise RuntimeError('Persistent GUI worker isolation failed: '+json.dumps(qualification['checks']))
    home=Path('/home/worker');state=Path('/workspace/build/.kilo-ui');state.mkdir(mode=0o700,exist_ok=True)
    cache=Path('/tmp/cache/kilo/bin');cache.mkdir(parents=True,exist_ok=True)
    # Only an already sealed public executable enters this fresh cache.
    import shutil
    shutil.copyfile('/usr/bin/rg',cache/'rg');(cache/'rg').chmod(0o700)
    environment=dict(os.environ,KILO_CONFIG='/home/worker/.config/kilo/modelbench.json',KILO_SERVER_PASSWORD=password,
        KILO_TELEMETRY_LEVEL='off',KILO_DISABLE_MODELS_FETCH='1',OPENCODE_DISABLE_MODELS_FETCH='1',
        KILO_DISABLE_CHANNEL_DB='true',KILO_ENABLE_QUESTION_TOOL='false',KILO_EXPERIMENTAL_DISABLE_FILEWATCHER='true',
        XDG_DATA_HOME=str(state/'data'),XDG_STATE_HOME=str(state/'state'),KILO_CLIENT='vscode')
    auth='Basic '+base64.b64encode(('kilo:'+password).encode()).decode()
    listener=worker.inference();child=None
    def stop(*args):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:
        child=subprocess.Popen(['/opt/modelbench/kilo','serve','--hostname','127.0.0.1','--port','47811'],cwd='/workspace',env=environment,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=sys.stderr)
        ready=False
        for _ in range(150):
            if child.poll() is not None:raise RuntimeError('Existing Kilo server exited during startup')
            try:
                connection=http.client.HTTPConnection('127.0.0.1',47811,timeout=1);connection.request('GET','/global/health',headers={'Authorization':auth});reply=connection.getresponse();data=json.load(reply);connection.close()
                if reply.status==200 and data.get('healthy'):ready=True;break
            except (OSError,ValueError,http.client.HTTPException):pass
            time.sleep(.1)
        if not ready:raise RuntimeError('Private Kilo server health timeout')
        with Server(str(state/'kilo.sock'),Relay) as server:
            os.chmod(state/'kilo.sock',0o600);server.auth=auth;server.qualification=qualification;server.serve_forever()
    finally:
        listener.close()
        if child is not None and child.poll() is None:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait()


if __name__=='__main__':main()
