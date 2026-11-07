#!/usr/bin/env python3
"""Separate offline native Brave/MCP broker using existing pinned installations.

native_browser.py
|-- validate  sealed rootfs/assets/public snapshots; no downloads or candidate data
|-- docs      fixed offline catalog -> private Unix socket; no network transport
|-- MCP       per-connection native browser namespace, fixed three tool methods
`-- evidence  private hashed traces, scoped socket, owned-child cleanup

Run as normal target user: python3 -B tools/native_browser.py --profile FILE.
Root is used only by the reviewed ephemeral namespace constructor. No install,
AppArmor/sysctl modification, model access or candidate execution.
"""
import argparse
import base64
import contextlib
import json
import os
from pathlib import Path
import select
import re
import stat
import signal
import shutil
import tempfile
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

import worker as w
from public_snapshots import Snapshots

TOOLS={'browser_tabs','browser_navigate','browser_snapshot'}

def asset_tree(path):
    path=w.safe(path);rows=[]
    for item in sorted(path.rglob('*')):
        name=str(item.relative_to(path));mode=item.lstat().st_mode&0o7777
        if item.is_symlink():
            item.resolve(strict=True).relative_to(path.resolve());rows.append([name,'link',os.readlink(item)])
        elif item.is_file():rows.append([name,'file',mode,w.digest(item)])
        elif item.is_dir():rows.append([name,'dir',mode])
        else:raise ValueError('Unexpected public tool asset')
    return w.sha(w.encoded(rows))

def seal_assets(source,destination,expected):
    source=w.safe(source);destination=w.safe(destination)
    w.require(asset_tree(source)==expected,'Native tool assets changed before sealing')
    if destination.exists():
        receipt=w.read(destination/'receipt.json')
        w.require(receipt=={'source':str(source),'tree_sha256':expected} and asset_tree(destination/'files')==expected,'Sealed assets changed')
        return destination/'files'
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    stage=Path(tempfile.mkdtemp(prefix='.asset-stage-',dir=destination.parent))
    shutil.copytree(source,stage/'files',symlinks=True)
    w.require(asset_tree(stage/'files')==expected and asset_tree(source)==expected,'Assets changed during sealing')
    w.write(stage/'receipt.json',{'source':str(source),'tree_sha256':expected})
    w.publish(stage,destination);return destination/'files'

MAX_FRAME=2*1024*1024


def wire(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()


def forwarded_request(value):
    # This virtual MCP server exposes tools only. The isolated browser has its
    # fixed private scratch directory; it must never ask Kilo for worker roots.
    if value.get('method')=='initialize':
        value=dict(value);params=value.get('params')
        w.require(isinstance(params,dict),'Initialize parameters required')
        value['params']=dict(params,capabilities={})
    return value

def emit(folder,row):
    raw=wire(row)
    with (folder/'events.jsonl').open('ab') as out:os.fchmod(out.fileno(),0o600);out.write(raw)


def json_frame(raw):
    w.require(len(raw)<=MAX_FRAME and raw.endswith(b'\n'),'Oversized/incomplete MCP frame')
    def unique(pairs):
        result={}
        for k,v in pairs:
            w.require(k not in result,'Duplicate MCP key');result[k]=v
        return result
    value=json.loads(raw,object_pairs_hook=unique)
    w.require(isinstance(value,dict) and value.get('jsonrpc')=='2.0','MCP2.0 object required')
    return value


def allowed_call(row,catalog):
    method=row.get('method');p=row.get('params',{})
    w.require(method in {'initialize','notifications/initialized','notifications/cancelled','ping','tools/list','tools/call'},'MCP method denied')
    if method=='notifications/cancelled':
        w.require('id' not in row and isinstance(p,dict) and set(p)<={'requestId','reason'} and type(p.get('requestId')) in {int,str}
                  and (type(p['requestId']) is int or len(p['requestId'])<=128) and ('reason' not in p or isinstance(p['reason'],str) and len(p['reason'])<=1024),'Invalid MCP cancellation')
        return
    if method!='tools/call':return
    w.require(isinstance(p,dict) and set(p)<={'name','arguments','_meta'} and p.get('name') in TOOLS,'MCP tool denied')
    a=p.get('arguments',{});w.require(isinstance(a,dict),'MCP arguments required')
    if p['name']=='browser_navigate':
        w.require(set(a)=={'url'} and isinstance(a['url'],str) and len(a['url'])<=8192,'Navigation shape/size denied')
        url=a['url'];parsed=urlsplit(url)
        w.require(url.startswith('data:text/html,') or url in catalog,'Navigation outside exact offline catalog')
        w.require(not parsed.username and not parsed.password,'Authenticated URL denied')
    elif p['name']=='browser_snapshot':w.require(not a,'Snapshot file output denied')
    else:w.require(set(a)<={'action','index'} and a.get('action') in {'list','close'} and ('index' not in a or type(a['index']) is int and a['index']>=0),'Tab operation denied')


class Bounded(socketserver.ThreadingMixIn):
    daemon_threads=True
    def server_bind(self):self.limit=threading.BoundedSemaphore(4);super().server_bind()
    def process_request(self,request,address):
        if not self.limit.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.limit.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.limit.release()


class Server(Bounded,socketserver.UnixStreamServer):pass


class Docs(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(10);result={'status':403,'headers':{'content-type':'text/plain'},'body':base64.b64encode(b'OFFLINE_CATALOG_DENIED').decode()}
        try:
            raw=self.rfile.readline(16385);row=json.loads(raw)
            with self.server.budget_lock:
                self.server.requests+=1;w.require(self.server.requests<=512,'Docs request budget')
            if len(raw)>16384 or set(row)!={'method','url'} or row['method']!='GET':raise ValueError('Catalog request denied')
            result,_=self.server.snapshots.response(row['url'])
            event={'kind':'docs','request_sha256':w.sha(raw),'response_sha256':w.sha(w.encoded(result)),'status':result['status']}
        except Exception as exc:event={'kind':'docs','status':403,'reason':type(exc).__name__}
        emit(self.server.root,event);self.wfile.write(wire(result))


def inline_snapshots(response,scratch):
    """Only MCP-created auto-named YAML snapshots; never a general file reader."""
    for item in response.get('result',{}).get('content',[]):
        if item.get('type')!='text':continue
        def replace(match):
            name=match.group(1);directory=scratch/'browser'
            fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
            try:
                source=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                try:
                    info=os.fstat(source);w.require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_uid==os.getuid() and info.st_size<=MAX_FRAME//2,'Unsafe browser snapshot artifact')
                    with os.fdopen(source,'rb',closefd=False) as stream:data=stream.read(MAX_FRAME//2+1)
                    after=os.fstat(source);w.require(len(data)==info.st_size and (info.st_ino,info.st_size,info.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns),'Browser snapshot changed during read')
                finally:os.close(source)
            finally:os.close(fd)
            return '```yaml\n'+data.decode('utf-8')+'\n```'
        item['text']=re.sub(r'(?m)^- \[Snapshot\]\(browser/(page-[A-Za-z0-9_.:-]+\.yml)\)$',replace,item['text'])
    return response


def send_child(child,data,seconds=10):
    fd=child.stdin.fileno();os.set_blocking(fd,False);deadline=time.monotonic()+seconds;offset=0
    while offset<len(data):
        left=deadline-time.monotonic();w.require(left>0 and child.poll() is None,'Browser input deadline/exit')
        _,ready,_=select.select([],[fd],[],left);w.require(ready,'Browser input timeout')
        try:offset+=os.write(fd,data[offset:offset+65536])
        except BlockingIOError:continue


def browser_manifest(root,profile,scratch):
    cfg=root/'browser-config.json';catalog=root/'research-catalog.json'
    mounts=[]
    def bind(source,target,writable=False):mounts.append({'source':str(source),'target':target,'writable':writable})
    bind(scratch,'/workspace',True)
    bind(w.safe(profile['brave_resources']['path']),'/opt/brave.com/brave')
    bind(w.safe(profile['mcp_modules']['path']),'/opt/modelbench/node_modules')
    bind(Path('/sys/devices/system/cpu'),'/sys/devices/system/cpu')
    for source,target in [(Path(__file__).with_name('browser_inner.py'),'/run/browser_inner.py'),(cfg,'/run/browser-config.json'),(root/'playwright-config.json','/run/playwright-config.json'),(catalog,'/run/research-catalog.json'),(Path(__file__).with_name('browser_route.cjs'),'/run/route.cjs'),(root/'docs.sock','/run/modelbench/docs.sock')]:bind(source,target)
    return {'schema_version':1,'role':'browser','uid':os.getuid(),'gid':os.getgid(),'rootfs':profile['rootfs']['path'],'mounts':mounts,
        'environment':{'HOME':'/home/worker','USER':'worker','LOGNAME':'worker','PATH':'/usr/bin:/bin','LANG':'C.UTF-8','TMPDIR':'/tmp','XDG_CACHE_HOME':'/tmp/cache','PYTHONDONTWRITEBYTECODE':'1'},
        'argv':['/usr/bin/python3','-B','/run/browser_inner.py'],'cwd':'/workspace'}


class MCP(socketserver.StreamRequestHandler):
    def handle(self):
        pid,uid,_=struct.unpack('3i',self.connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if uid!=os.getuid():return
        # A peer-identity probe must not launch a browser or consume a trial.
        self.connection.settimeout(30)
        try:first=self.rfile.readline(MAX_FRAME+1)
        except OSError:return
        if not first:return
        # Model prefill/reasoning leaves MCP idle. Qualification service lifetime
        # bounds this established channel; per-tool response timeout stays 120s.
        self.connection.settimeout(None if self.server.profile.get('mode')=='TRIAL' else 900)
        child=None;error=None
        serial=os.urandom(8).hex();folder=self.server.root/('mcp-'+serial);folder.mkdir(mode=0o700)
        try:
            row=json_frame(first);allowed_call(row,self.server.snapshots.rows)
            for name in ['brave_resources','mcp_modules']:w.require(asset_tree(self.server.profile[name]['path'])==self.server.profile[name]['tree_sha256'],'Sealed browser assets drifted')
            scratch=folder/'scratch';scratch.mkdir(mode=0o700)
            manifest=browser_manifest(self.server.root,self.server.profile,scratch);path=folder/'manifest.json';w.write(path,manifest)
            log=(folder/'browser.stderr').open('xb');log.close();log=(folder/'browser.stderr').open('ab')
            argv=['sudo','-n',self.server.profile['python']['path'],'-I','-B',self.server.profile['constructor']['path'],'--manifest',str(path),'--sha256',w.digest(path)]
            child=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,start_new_session=True,bufsize=0)
            pending=bytearray()
            def reply():
                deadline=time.monotonic()+120
                while b'\n' not in pending:
                    ready,_,_=select.select([child.stdout],[],[],max(0,deadline-time.monotonic()))
                    w.require(ready and child.poll() is None,'Browser reply timeout/exit')
                    chunk=os.read(child.stdout.fileno(),65536);w.require(chunk,'Browser stream ended');pending.extend(chunk)
                    w.require(len(pending)<=MAX_FRAME,'Browser frame limit')
                end=pending.index(10)+1;raw=bytes(pending[:end]);del pending[:end];return json_frame(raw)
            frames=0;raw=first
            while raw:
                frames+=1;w.require(frames<=512,'MCP frame budget')
                with self.server.budget_lock:
                    self.server.requests+=1;w.require(self.server.requests<=512,'Global MCP frame budget')
                request=json_frame(raw);allowed_call(request,self.server.snapshots.rows)
                upstream_request=wire(forwarded_request(request));send_child(child,upstream_request)
                event={'kind':'mcp','connection':serial,'method':request['method'],'id':request.get('id'),'request_sha256':w.sha(raw),'upstream_request_sha256':w.sha(upstream_request),'tool':request.get('params',{}).get('name')}
                if 'id' in request:
                    for _ in range(32):
                        response=reply()
                        if response.get('id')==request['id']:break
                        w.require('id' not in response,'Unexpected MCP response')
                    else:raise ValueError('MCP notification budget')
                    if request['method']=='tools/list':
                        w.require('error' not in response,'MCP tools unavailable')
                        response['result']['tools']=[t for t in response['result']['tools'] if t['name'] in TOOLS]
                        w.require({t['name'] for t in response['result']['tools']}==TOOLS,'Required MCP tools absent')
                        target=folder/'tool-schema.json'
                        if target.exists():w.require(target.read_bytes()==w.encoded(response['result']),'MCP schema drift')
                        else:w.write(target,response['result'])
                    event['upstream_response_sha256']=w.sha(wire(response))
                    response=inline_snapshots(response,scratch)
                    encoded=wire(response);w.require(len(encoded)<=MAX_FRAME,'Adapted MCP response too large');event['response_sha256']=w.sha(encoded)
                    # Private canary transcript stays outside candidate mounts.
                    with (folder/'trace.jsonl').open('ab') as out:os.fchmod(out.fileno(),0o600);out.write(wire({'request':request,'response':response}))
                    self.wfile.write(encoded);self.wfile.flush()
                emit(self.server.root,event)
                raw=self.rfile.readline(MAX_FRAME+1)
        except Exception as exc:
            error=type(exc).__name__
            detail={'kind':'mcp-denied','connection':serial,'reason':error,'policy_reason':str(exc) if isinstance(exc,w.Blocked) else error}
            with contextlib.suppress(Exception):
                denied=json_frame(raw);params=denied.get('params',{});args=params.get('arguments',{}) if isinstance(params,dict) else {}
                detail.update(method=denied.get('method'),frame_keys=sorted(denied),param_keys=sorted(params) if isinstance(params,dict) else [],argument_keys=sorted(args) if isinstance(args,dict) else [],request_sha256=w.sha(raw))
            emit(self.server.root,detail)
            with contextlib.suppress(OSError):self.wfile.write(wire({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Restricted browser request denied/unavailable'}}))
        finally:
            if child is not None and child.poll() is None:
                with contextlib.suppress(ProcessLookupError):os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):os.killpg(child.pid,signal.SIGKILL)
                    child.wait()
            if child is not None:log.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',required=True,type=Path);args=parser.parse_args()
    profile=w.read(w.private(args.profile));root=w.safe(profile['root']);root.mkdir(mode=0o700,parents=True,exist_ok=True)
    w.require(profile.get('mode','QUALIFICATION') in {'QUALIFICATION','TRIAL'},'Invalid browser session mode')
    w.require(os.getuid()!=0,'Use normal coordinator')
    for name in ['python','constructor']:w.checked_artifact(profile[name])
    for pin in profile['sources'].values():w.checked_artifact(pin)
    for name in ['brave_resources','mcp_modules']:
        asset=w.safe(profile[name]['path']);receipt=w.read(w.private(asset.parent/'receipt.json'))
        w.require(asset.name=='files' and receipt['tree_sha256']==profile[name]['tree_sha256'],'Use sealed private browser assets')
    for name in ['rootfs','brave_resources','mcp_modules']:w.require((w.tree(profile[name]['path']) if name=='rootfs' else asset_tree(profile[name]['path']))==profile[name]['tree_sha256'],'Browser asset tree changed: '+name)
    snapshots=Snapshots(profile['snapshots']['path'],profile['snapshots']['sha256'])
    w.write(root/'research-catalog.json',list(snapshots.rows));w.write(root/'browser-config.json',{'origins':sorted({'https://'+urlsplit(u).netloc for u in snapshots.rows}),'host_namespaces':{n:os.readlink('/proc/self/ns/'+n) for n in ['pid','mnt','net','user','ipc','uts','cgroup']}})
    w.write(root/'playwright-config.json',{'browser':{'launchOptions':{'args':['--disable-setuid-sandbox']},'contextOptions':{'acceptDownloads':False,'serviceWorkers':'block'}}})
    w.write(root/'started.json',{'pid':os.getpid(),'profile_sha256':w.digest(args.profile),'created_unix':time.time()})
    fd=os.open(root,os.O_PATH|os.O_DIRECTORY)
    docs=Server('/proc/self/fd/'+str(fd)+'/docs.sock',Docs);docs.snapshots=snapshots;docs.root=root;docs.budget_lock=threading.Lock();docs.requests=0;os.chmod(root/'docs.sock',0o600)
    threading.Thread(target=docs.serve_forever,daemon=True).start()
    try:
        with Server('/proc/self/fd/'+str(fd)+'/browser.sock',MCP) as server:
            server.root=root;server.profile=profile;server.snapshots=snapshots;server.limit=threading.BoundedSemaphore(1);server.budget_lock=threading.Lock();server.requests=0;os.chmod(root/'browser.sock',0o600);server.serve_forever()
    finally:docs.shutdown();docs.server_close();os.close(fd)


if __name__=='__main__':main()
