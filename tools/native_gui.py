#!/usr/bin/env python3
"""Persistent native Kilo inspection backend and separately attachable VS Code UI.

native_gui.py
|-- backend    owned systemd process -> sealed native namespace -> Kilo serve
|-- attach     actual VS Code extension -> authenticated loopback view only
`-- reuse      immutable inputs/unit/Unix socket; never restart uncertain work

Inspection authorizes no model request. GATED_NATIVE_TRIAL preserves the exact
prepared assignment/budgets; the inference gateway permits only its bounded
qualification until an independent current readiness receipt is supplied.
Closing a view must not restart its backend or consume another model trial.
"""
import argparse
import base64
import contextlib
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
from urllib.parse import parse_qsl,urlencode,urlsplit,urlunsplit

import worker as w


def inputs(path):
    value=w.read(w.private(path));root=w.safe(value['root']);config=w.read(w.checked_artifact(value['toolchain']))
    w.require(value['schema_version']==1 and value['mode'] in {'INSPECTION_NO_INFERENCE','C00_SCHEMA_CAPTURE','C00_TOOL_CANARY','GATED_NATIVE_TRIAL'},'Unsupported native GUI mode')
    record=w.read(w.checked_artifact(value['record']))
    if value['mode']=='INSPECTION_NO_INFERENCE':inspection_only(config)
    else:
        w.require(set(config.get('channels',{}))=={'inference','browser'},'Two scoped C00 channels required')
        policy=w.read(w.checked_artifact(value['inference_policy']))
        w.require(policy['mode']==('INSPECTION' if value['mode']=='C00_SCHEMA_CAPTURE' else 'GATED_TRIAL' if value['mode']=='GATED_NATIVE_TRIAL' else 'TRIAL'),'Gateway mode differs')
        allowed={'playwright_browser_navigate','playwright_browser_snapshot','playwright_browser_tabs'}
        if value['mode']=='GATED_NATIVE_TRIAL':
            import inference_transport as transport
            transport.check_policy(policy);w.validate_config(w.checked_artifact(value['toolchain']))
            w.require(all(policy['execution'][name]==value[name] for name in ['record','toolchain']),'Gateway and GUI execution pins differ')
            run=run_directory(value,root);w.require(value.get('run_directory')==value['run_id'],'Real trial directory identity differs')
            w.require(record['identity']['toolchain_sha256']==w.digest(w.checked_artifact(value['toolchain'])),'Prepared toolchain differs')
            w.require(record['fingerprint']==w.sha(w.encoded(record['identity'])),'Prepared run fingerprint differs')
            w.verify_frozen(run,record)
            for key in ['seed','max_output_tokens_per_turn','max_total_generated_tokens','max_agent_turns','max_tool_calls']:
                expected=record['identity']['seed'] if key=='seed' else record['budget'][key]
                w.require(policy[key]==expected,'Trial budget differs: '+key)
            w.require(policy['wall_seconds']==record['execution_wall_seconds'],'Trial timing differs')
            w.require(allowed<=set(policy['tools'])<=transport.ALLOWED_TOOLS,'Trial tools differ')
            w.require(value.get('coordinator_unit')=='ai-bench42-session-'+value['run_id']+'.service','Trial coordinator identity differs')
        else:
            w.require(set(policy['tools'])<=allowed and (value['mode']=='C00_SCHEMA_CAPTURE' or set(policy['tools'])==allowed),'Only three browser tools allowed for C00')
            w.require(policy['max_agent_turns']<=6 and policy['max_tool_calls']<=6,'C00 budgets differ')
        w.require(policy['run_id']==value['run_id'],'Gateway Run-ID differs')
        for channel in config['channels'].values():w.peer(channel)
    w.require(w.tree(config['rootfs']['path'])==value['rootfs_tree_sha256'],'Native rootfs changed')
    for pin in value['sources'].values():w.checked_artifact(pin)
    if 'extension_tree_sha256' in value:w.require(w.tree(root/'extension')==value['extension_tree_sha256'],'Derived UI extension changed')
    for row in config['agent']['config_files']:w.checked_artifact(row)
    w.require(record['identity']['run_id']==value['run_id'],'GUI/run identity differs')
    return value,root,config,record


def inspection_only(config):
    w.require(config.get('channels')=={},'Inspection forbids inference/browser channels')


def run_directory(value,root):
    name=value.get('run_directory','run')
    w.require(isinstance(name,str) and re.fullmatch('[a-z0-9-]{1,60}',name),'Invalid worker run directory')
    return root/name


def lifetime(value):
    if value.get('mode')!='GATED_NATIVE_TRIAL':return 900
    record=w.read(w.checked_artifact(value['record']));seconds=record['execution_wall_seconds']
    w.require(seconds is None or type(seconds) is int and seconds>0,'Invalid execution lifetime')
    return seconds


def unit(value):
    w.require(re.fullmatch('[a-z0-9-]{1,60}',value['run_id']),'Invalid GUI run identifier')
    return 'ai-bench42-native-'+value['run_id']+'.service'


def state(value):
    result=subprocess.run(['systemctl','--user','show',unit(value),'-p','LoadState','-p','ActiveState','-p','MainPID','-p','InvocationID','-p','ExecStart','-p','Restart','-p','MemoryMax','-p','MemorySwapMax','-p','TasksMax','-p','RuntimeMaxUSec','-p','BindsTo'],capture_output=True,text=True,timeout=5)
    w.require(result.returncode in (0,4),'Native GUI service state unavailable')
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def ensure(path,value,root):
    with w.locked(root):
        receipt=root/'backend-receipt.json';intent=root/'backend-intent.json';actual=state(value)
        if receipt.exists():
            previous=w.read(receipt)
            w.require(previous['configuration_sha256']==w.digest(path) and previous['ready_sha256']==w.digest(root/'backend-ready.json')
                      and previous['unit_state']==actual
                      and actual.get('ActiveState')=='active','Stopped/changed GUI backend retained; no automatic restart')
            return
        w.require(not intent.exists() and actual.get('LoadState')=='not-found','Uncertain/previous backend retained; inspect it')
        w.write(intent,{'configuration_sha256':w.digest(path),'unit':unit(value),'created_unix':time.time()})
        seconds=lifetime(value)
        argv=['systemd-run','--user','--unit='+unit(value),'--property=Restart=no','--property=RuntimeMaxSec='+('infinity' if seconds is None else str(seconds)),
              '--property=MemoryMax=4G','--property=MemorySwapMax=0','--property=TasksMax=256','--property=CPUQuota=200%',
              '--property=UMask=0077','/usr/bin/python3','-B',str(Path(__file__)),'backend','--configuration',str(path)]
        if value.get('mode')=='GATED_NATIVE_TRIAL':
            coordinator=value.get('coordinator_unit')
            w.require(coordinator=='ai-bench42-session-'+value['run_id']+'.service','Trial coordinator identity differs')
            parent=subprocess.run(['systemctl','--user','is-active','--quiet',coordinator],capture_output=True,timeout=5)
            w.require(parent.returncode==0,'Owned coordinator must be active before the backend')
            argv[2:2]=['--property=BindsTo='+coordinator,'--property=After='+coordinator]
        result=subprocess.run(argv,capture_output=True,text=True,timeout=10)
        w.require(result.returncode==0,'Native GUI service launch failed; preserve intent')
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            actual=state(value)
            w.require(actual.get('ActiveState') not in ('failed','inactive'),'Native GUI backend startup failed')
            if (root/'backend-ready.json').exists():
                w.require(actual.get('ActiveState')=='active' and actual.get('Restart')=='no','Unexpected native service policy')
                if value.get('mode')=='GATED_NATIVE_TRIAL':w.require(value['coordinator_unit'] in actual.get('BindsTo','').split(),'Backend is not bound to its coordinator')
                w.write(receipt,{'configuration_sha256':w.digest(path),'unit_state':actual,'ready_sha256':w.digest(root/'backend-ready.json')});return
            time.sleep(.2)
        raise w.Blocked('Native GUI startup outcome uncertain; no retry')


class Unix(http.client.HTTPConnection):
    def __init__(self,directory_fd,timeout=120):super().__init__('private-kilo',timeout=timeout);self.directory_fd=directory_fd
    def connect(self):
        import socket
        self.sock=socket.socket(socket.AF_UNIX);self.sock.settimeout(self.timeout)
        self.sock.connect('/proc/self/fd/'+str(self.directory_fd)+'/kilo.sock')


def backend(path):
    value,root,config,record=inputs(path);run=run_directory(value,root);folder=run/'workspace/build/.kilo-ui'
    w.require(not (root/'backend-started.json').exists(),'Native GUI backend already started; no replay')
    w.write(root/'backend-started.json',{'configuration_sha256':w.digest(path),'pid':os.getpid(),'created_unix':time.time()})
    challenge=secrets.token_hex(16);host=Path.home()
    probe={'challenge':challenge,'host_marker':str(root/'host-only-marker'),'host_home':str(host),'host_home_identity':[host.stat().st_dev,host.stat().st_ino],
        'host_pid_namespace':os.readlink('/proc/self/ns/pid'),'host_net_namespace':os.readlink('/proc/self/ns/net'),
        'host_namespaces':{name:os.readlink('/proc/self/ns/'+name) for name in ('user','pid','net','mnt','ipc','uts','cgroup')},
        'expected_train_sha256':record['identity']['train_sha256'],'frozen_path':'/workspace/AGENTS.md'}
    w.write(root/'host-only-marker',{'synthetic':challenge})
    argv=w.native_command(run,record,config,'gui')
    log=(root/'native-worker.stderr').open('xb');os.chmod(root/'native-worker.stderr',0o600)
    child=None
    def stop(*args):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop)
    try:
        child=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log,start_new_session=True,
                               preexec_fn=w.restrictions(config,lifetime(value)))
        child.stdin.write(w.encoded({'password':secrets.token_hex(32),'probe':probe}));child.stdin.close()
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            w.require(child.poll() is None,'Native Kilo server failed; inspect private stderr')
            if (folder/'kilo.sock').is_socket():break
            time.sleep(.1)
        else:raise w.Blocked('Native Kilo UI socket timeout')
        fd=os.open(folder,os.O_PATH|os.O_DIRECTORY)
        try:
            connection=Unix(fd);connection.request('GET','/__modelbench/qualification');reply=connection.getresponse();qualification=json.load(reply);connection.close()
            w.require(reply.status==200 and qualification.get('status')=='PASS' and qualification['challenge']==challenge,'Persistent native worker boundary failed')
        finally:os.close(fd)
        w.write(root/'backend-ready.json',{'status':'NATIVE_GUI_BACKEND_ONLY_NOT_C00' if value['mode']=='INSPECTION_NO_INFERENCE' else 'C00_TRANSPORT_UI_ONLY_NOT_READY','qualification':qualification,'model_requests':0 if value['mode']=='INSPECTION_NO_INFERENCE' else None,'constructor_pid':child.pid,'created_unix':time.time()})
        child.wait()
    finally:
        if child is not None and child.poll() is None:
            with contextlib.suppress(ProcessLookupError):os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):os.killpg(child.pid,signal.SIGKILL)
                child.wait()
        log.close()


class ViewServer(ThreadingHTTPServer):
    daemon_threads=True
    idle_timeout=15
    maximum_connections=16
    def server_bind(self):
        import threading
        self.limit=threading.BoundedSemaphore(self.maximum_connections);super().server_bind()
    def get_request(self):
        request,address=super().get_request();request.settimeout(self.idle_timeout);return request,address
    def process_request(self,request,address):
        if not self.limit.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.limit.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.limit.release()


class View(BaseHTTPRequestHandler):
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
            if self.headers.get('Authorization')!=self.server.auth:self.send_error(401);return
            parsed=urlsplit(self.path)
            if parsed.scheme or parsed.netloc or not parsed.path.startswith('/') or parsed.path.startswith('/__modelbench'):self.send_error(403);return
            pairs=[]
            for key,val in parse_qsl(parsed.query,keep_blank_values=True):
                if key=='directory':
                    if val not in (self.server.workspace,'/workspace'):raise ValueError('Different project denied')
                    val='/workspace'
                pairs.append((key,val))
            path=urlunsplit(('','',parsed.path,urlencode(pairs),''))
            if self.headers.get('Transfer-Encoding') or self.headers.get('Content-Encoding'):raise ValueError('Encoded UI request denied')
            lengths=self.headers.get_all('Content-Length',[])
            if len(lengths)>1:raise ValueError('Duplicate length')
            length=int(lengths[0]) if lengths else 0
            if not 0<=length<=2*1024*1024:raise ValueError('Oversized UI request')
            raw=self.rfile.read(length)
            if len(raw)!=length:raise ValueError('Truncated UI request')
            connection=Unix(self.server.fd);connection.request(self.command,path,raw,{'Content-Type':'application/json'})
            reply=connection.getresponse();self.send_response(reply.status)
            for key,val in reply.getheaders():
                if key.lower() in {'content-type','content-length','cache-control'}:self.send_header(key,val)
            self.end_headers();total=0
            while chunk:=reply.read1(16384):
                total+=len(chunk)
                if total>32*1024*1024:raise ValueError('Oversized UI response')
                self.wfile.write(chunk);self.wfile.flush()
        except (OSError,ValueError,http.client.HTTPException):
            with contextlib.suppress(OSError):self.send_error(502,'Native private UI unavailable')
        finally:
            if connection:connection.close()
            self.close_connection=True


def attach(path):
    value,root,config,record=inputs(path)
    w.require(os.environ.get('KILO_CLIENT')=='vscode','Actual VS Code extension attachment required')
    ensure(path,value,root)
    password=os.environ.get('KILO_SERVER_PASSWORD')
    w.require(isinstance(password,str) and 24<=len(password)<=256,'Missing ephemeral extension UI credential')
    run=run_directory(value,root)
    fd=os.open(run/'workspace/build/.kilo-ui',os.O_PATH|os.O_DIRECTORY)
    try:
        with ViewServer(('127.0.0.1',0),View) as server:
            server.auth='Basic '+base64.b64encode(('kilo:'+password).encode()).decode();server.fd=fd;server.workspace=str(run/'workspace')
            print('kilo server listening on http://127.0.0.1:'+str(server.server_address[1]),flush=True)
            server.serve_forever()
    finally:os.close(fd)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['backend','attach']);parser.add_argument('--configuration',required=True,type=Path);args=parser.parse_args()
    try:
        if args.action=='backend':backend(args.configuration)
        else:attach(args.configuration)
        return 0
    except (OSError,ValueError,RuntimeError,KeyError,subprocess.SubprocessError) as exc:print('Native GUI BLOCKED: '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
