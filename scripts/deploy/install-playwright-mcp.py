#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Purpose: provide the existing sandboxed Brave/Playwright MCP as one stdio tool.
# Identity: validatus on Spark, without sudo. Inputs: config/playwright-mcp.json.
# Reuses installed pinned npm packages and native Brave; no downloads/upgrades.
# Effects: atomically publish an owned launcher/Kilo fragment; private verify runs.
# No desktop, shared browser, personal profile, policy, systemd or client edits.
#
# install-playwright-mcp.py
# |-- [J01] load_profile()  strict single-host JSON / execution identity
# |-- [J02] inventory()     installed versions, bounded module seal, browser/node
# |-- [J03] desired()       fixed sandboxed stdio launcher + Kilo client fragment
# |-- [J04] install()       lock -> stage -> recheck -> atomic publish / NOOP
# |-- [J05] Mcp            bounded JSON-line protocol; owned-process cleanup
# |-- [J06] browser_probe() loopback fixture + actual sandbox/process checks
# |-- [J07] verify()        drift checks -> real tool/browser run -> indexed receipt
# `-- [J08] main()          inspect | install | verify; fail closed on conflicts
#
# VS Code: Ctrl+Shift+O -> function; Ctrl+F -> [J01]...[J08]; regions fold.
# Example on Spark: python3 -B scripts/deploy/install-playwright-mcp.py inspect
#                   python3 -B scripts/deploy/install-playwright-mcp.py install
#                   python3 -B scripts/deploy/install-playwright-mcp.py verify
# Missing packages/Brave fail with prerequisites; this is not a fresh-host bootstrap.
import argparse
import contextlib
import ctypes
import datetime
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import platform
import pwd
import re
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
SPARK = Path('/home/validatus/workspace/AI-Model')
OWNER = 'AI-Model/playwright-tool/v1'
RPC_TIMEOUT=45
# Exact manifest of our rejected long-TMPDIR pilot; no generic upgrade/adoption.
REJECTED_MANIFEST_SHA256='f7d094d23fdf5c2107669b18ea5b693f35d100baaec83e67a8844036bbc88bf5'


def encoded(data):
    return (json.dumps(data, indent=2, sort_keys=True) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def safe_path(path):
    for p in (path,) + tuple(path.parents):
        if p.is_symlink():
            raise RuntimeError('Managed path contains symlink: ' + str(p))
    return path


def write_new(path, data, mode=0o600):
    with path.open('xb') as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def clean_env(base):
    return {'HOME': pwd.getpwuid(os.geteuid()).pw_dir, 'USER': pwd.getpwuid(os.geteuid()).pw_name, 'LOGNAME': pwd.getpwuid(os.geteuid()).pw_name,
            'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TMPDIR': str(base/'tmp'),
            'XDG_CACHE_HOME': str(base/'cache'), 'PYTHONDONTWRITEBYTECODE': '1'}


#region [J01] Profile and identity

def load_profile(root=ROOT):
    profile=json.loads((root/'config/playwright-mcp.json').read_text())
    expected={'version':1,'hostname':'spark-a922','user':'validatus','node':'/usr/bin/node',
        'minimum_node_major':22,'module_root':str(SPARK/'runtime/spark-a922/tools/playwright/node_modules'),
        'packages':{'@playwright/mcp':'0.0.83','playwright':'1.64.0-alpha-1790635538000','playwright-core':'1.64.0-alpha-1790635538000'},
        'browser':'/opt/brave.com/brave/brave','runtime':str(SPARK/'runtime/spark-a922/tools/playwright-tool'),
        'temporary_root':str(SPARK/'runtime/spark-a922/tmp')}
    if profile!=expected or type(profile.get('version')) is not int:
        raise ValueError('Expected the reviewed existing Spark/Brave/MCP profile, without overrides')
    return profile


def identity(profile):
    user=pwd.getpwuid(os.geteuid())
    if (os.geteuid()==0 or user.pw_name!=profile['user'] or platform.node()!=profile['hostname']
            or platform.machine()!='aarch64' or os.environ.get('HOME')!=user.pw_dir or not (ROOT==SPARK or ROOT.is_relative_to(SPARK/'runtime/spark-a922/build'))):
        raise RuntimeError('Run on spark-a922 as validatus without sudo, from the mirrored project')

#endregion
#region [J02] Read-only installed dependency observations

def seal_modules(modules):
    safe_path(modules)
    records=[];total=0
    for base,dirs,files in os.walk(modules,followlinks=False):
        for name in sorted(dirs+files):
            p=Path(base)/name;st=p.lstat();relative=str(p.relative_to(modules))
            if p.is_symlink():
                p.resolve(strict=True).relative_to(modules.resolve())
                row=[relative,'link',os.readlink(p)]
            elif stat.S_ISREG(st.st_mode):
                total+=st.st_size
                if total>256*1024*1024 or st.st_size>64*1024*1024:
                    raise RuntimeError('Installed module tree exceeds bounded seal limit')
                row=[relative,'file',stat.S_IMODE(st.st_mode),sha(p.read_bytes())]
            elif stat.S_ISDIR(st.st_mode):
                row=[relative,'dir',stat.S_IMODE(st.st_mode)]
            else:
                raise RuntimeError('Unsupported npm module entry')
            records.append(row)
            if len(records)>20000:raise RuntimeError('Too many module entries')
        dirs.sort()
    if not records:raise RuntimeError('Existing pinned MCP modules are missing')
    return {'sha256':sha(encoded(sorted(records))), 'entries':len(records),'file_bytes':total,
            'qualification':'Drift seal of existing installed bytes; not fresh npm acquisition/authentication.'}


def inventory(profile):
    modules=Path(profile['module_root']);base=Path(profile['runtime'])
    temporary=safe_path(Path(profile['temporary_root']));ts=temporary.stat()
    if not temporary.is_dir() or ts.st_uid!=os.geteuid() or ts.st_mode&0o022:
        raise RuntimeError('Expected existing owned, non-writable short runtime temporary directory')
    if len(os.fsencode(str(temporary)+'/org.chromium.Chromium.XXXXXX/SingletonSocket'))>107:
        raise RuntimeError('Chromium Unix socket path exceeds Linux limit')
    versions={name:json.loads((modules/name/'package.json').read_text())['version'] for name in profile['packages']}
    if versions!=profile['packages']:raise RuntimeError('Installed npm versions differ; preserve environment and review pins')
    result=subprocess.run([profile['node'],'--version'],capture_output=True,text=True,timeout=10,
                          env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
    if result.returncode or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+\n?',result.stdout):
        raise RuntimeError('Native Node version unavailable')
    if int(result.stdout.strip()[1:].split('.')[0])<profile['minimum_node_major']:
        raise RuntimeError('Native Node22+ is required; no automatic update')
    cli=modules/'@playwright/mcp/cli.js';safe_path(cli)
    browser=Path(profile['browser']);safe_path(browser)
    bs=browser.stat()
    if not stat.S_ISREG(bs.st_mode) or bs.st_uid!=0 or bs.st_mode&0o022 or not os.access(browser,os.X_OK):
        raise RuntimeError('Expected root-owned executable native Brave')
    return {'packages':versions,'node_version':result.stdout.strip(),'node_sha256':file_sha(Path(profile['node'])),
        'browser_sha256':file_sha(browser),'module_seal':seal_modules(modules)}

#endregion
#region [J03] One fixed sandboxed stdio launcher and client fragment

def desired(profile, observations):
    base=Path(profile['runtime']);cli=Path(profile['module_root'])/'@playwright/mcp/cli.js'
    # A new private output directory per client avoids output collisions. The
    # owning sessions component retains metadata; isolated profiles are ephemeral.
    launcher='''#!/usr/bin/env bash
# managed-by: AI-Model/playwright-tool/v1
set -Eeuo pipefail
umask 077
(( $# == 0 )) || { printf 'This managed MCP launcher accepts no overrides.\\n' >&2; exit 2; }
'''
    launcher+='session=$(/usr/bin/mktemp -d '+shlex.quote(str(base/'sessions/session-XXXXXXXX'))+')\n'
    launcher+='printf \'{"owner":"'+OWNER+'","component":"playwright-output"}\\n\' > "$session/index.json"\n'
    command=['/usr/bin/env','-i','HOME='+pwd.getpwnam(profile['user']).pw_dir,'USER='+profile['user'],'LOGNAME='+profile['user'],'PATH=/usr/bin:/bin','LANG=C.UTF-8',
             'TMPDIR='+profile['temporary_root'],'XDG_CACHE_HOME='+str(base/'cache'),profile['node'],str(cli),'--headless','--isolated','--sandbox','--block-service-workers',
             '--executable-path',profile['browser'],'--output-dir']
    launcher+='exec '+shlex.join(command)+' "$session"\n'
    client={'mcp':{'playwright':{'type':'local','command':[str(base/'playwright-mcp')],'enabled':True,'timeout':60000}}}
    files={'playwright-mcp':(launcher.encode(),0o700),'kilo.json':(encoded(client),0o600)}
    manifest={'owner':OWNER,'profile':profile,'dependencies':observations,
              'files':{name:{'sha256':sha(data),'mode':mode} for name,(data,mode) in files.items()},
              'runtime_components':{'sessions':'Per-client private output, each with owner index; preserved for operator review.',
                                    'runs':'Unique indexed browser verification receipts; no model requests.',
                                    'tmp':'Ephemeral browser temporary data.','cache':'Owned browser cache.'}}
    return dict(files,**{'manifest.json':(encoded(manifest),0o600)})


def verify_files(base, files):
    safe_path(base)
    if base.stat().st_uid!=os.geteuid() or stat.S_IMODE(base.stat().st_mode)!=0o700:
        raise RuntimeError('Unexpected owned runtime directory')
    expected=set(files)|{'sessions','runs','tmp','cache'}
    if {p.name for p in base.iterdir()}!=expected:raise RuntimeError('Unexpected/missing managed runtime entries')
    for name,(data,mode) in files.items():
        p=safe_path(base/name);s=p.stat()
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)!=mode or p.read_bytes()!=data:
            raise RuntimeError('Managed file or dependency seal diverged: '+str(p))
    for name in ('sessions','runs','tmp','cache'):
        p=safe_path(base/name);s=p.stat()
        if not p.is_dir() or s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)!=0o700:
            raise RuntimeError('Unexpected component owner/mode: '+str(p))

#endregion
#region [J04] Lock, atomic publication and unchanged repeat

def publish(stage,base):
    # Linux renameat2 NOREPLACE preserves even an empty concurrently created target.
    libc=ctypes.CDLL(None,use_errno=True)
    rename=libc.renameat2
    rename.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
    rename.restype=ctypes.c_int
    if rename(-100,os.fsencode(stage),-100,os.fsencode(base),1):
        err=ctypes.get_errno();raise OSError(err,os.strerror(err),str(base))


def legacy_files(base,profile,observed):
    path=safe_path(base/'manifest.json')
    if not path.is_file():raise RuntimeError('Unmanaged target has no owned manifest; refuse adoption')
    raw=path.read_bytes()
    if sha(raw)!=REJECTED_MANIFEST_SHA256:
        raise RuntimeError('Managed state differs; only the exact rejected long-TMPDIR pilot may be repaired')
    manifest=json.loads(raw);old_profile=dict(profile);old_profile.pop('temporary_root')
    if manifest.get('owner')!=OWNER or manifest.get('profile')!=old_profile or manifest.get('dependencies')!=observed:
        raise RuntimeError('Rejected pilot dependencies/profile changed; refuse repair')
    files={'manifest.json':(raw,0o600)}
    if set(manifest['files'])!={'playwright-mcp','kilo.json'}:raise RuntimeError('Unexpected legacy file set')
    for name,row in manifest['files'].items():
        data=safe_path(base/name).read_bytes()
        if sha(data)!=row['sha256']:raise RuntimeError('Rejected pilot file diverged; preserve for review')
        files[name]=(data,row['mode'])
    verify_files(base,files)
    return files


def replace_owned(path,data,mode):
    safe_path(path)
    temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    try:
        write_new(temp,data,mode);os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()


def repair_rejected_pilot(base,profile,observed,files):
    old=legacy_files(base,profile,observed)
    folder=base/'runs'/('repair-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    receipt={'owner':OWNER,'status':'PREPARED','reason':'Exact rejected pilot: Chromium SingletonSocket path too long',
             'before_manifest_sha256':sha(old['manifest.json'][0]),'backups':{},'started_at':now()}
    for name,(data,mode) in old.items():
        write_new(folder/('before-'+name),data)
        if file_sha(folder/('before-'+name))!=sha(data):raise RuntimeError('Repair backup checksum failed')
        receipt['backups'][name]={'file':'before-'+name,'sha256':sha(data),'mode':mode}
    changed=[name for name in ('playwright-mcp','kilo.json','manifest.json') if old[name]!=files[name]]
    receipt['changed_files']=changed
    write_new(folder/'prepared.json',encoded(receipt))
    try:
        legacy_files(base,profile,observed)
        for name in changed:replace_owned(base/name,*files[name])
        verify_files(base,files);receipt['status']='REPAIRED_REJECTED_PILOT'
    except BaseException as exc:
        receipt.update(status='FAILED',error=type(exc).__name__+': '+str(exc))
        try:
            for name in changed:
                path=safe_path(base/name)
                if path.read_bytes() not in (old[name][0],files[name][0]):
                    raise RuntimeError('Concurrent repair divergence; no overwrite')
            for name in changed:replace_owned(base/name,*old[name])
            receipt['previous_files_restored']=True
        except BaseException as recovery:receipt['recovery_error']=str(recovery)
        raise
    finally:
        receipt['finished_at']=now();write_new(folder/'receipt.json',encoded(receipt))
        write_new(folder/'index.json',encoded({'owner':OWNER,'files':{p.name:{'bytes':p.stat().st_size,'sha256':file_sha(p)} for p in folder.iterdir() if p.is_file()}}))
    print(json.dumps({'status':'REPAIRED_REJECTED_PILOT','changed_files':len(changed),'runtime':str(base),'receipt':str(folder/'receipt.json')}))


def install(profile):
    identity(profile);base=safe_path(Path(profile['runtime']))
    # Preflight installed dependencies and existing ownership before writing.
    observed=inventory(profile);files=desired(profile,observed)
    if base.exists():
        try:verify_files(base,files)
        except RuntimeError:legacy_files(base,profile,observed)
    parent=safe_path(base.parent)
    if not parent.is_dir() or parent.stat().st_uid!=os.geteuid():raise RuntimeError('Expected existing owned tools directory')
    lockpath=safe_path(parent/'playwright-tool-install.lock')
    if lockpath.exists() and (lockpath.stat().st_uid!=os.geteuid() or not lockpath.is_file() or stat.S_IMODE(lockpath.stat().st_mode)!=0o600):
        raise RuntimeError('Unexpected installer lock owner/type')
    fd=os.open(lockpath,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if base.exists():
            try:verify_files(base,files)
            except RuntimeError:
                repair_rejected_pilot(base,profile,observed,files);return
            print(json.dumps({'status':'UNCHANGED','changed_files':0,'runtime':str(base)}));return
        stage=Path(tempfile.mkdtemp(prefix='.playwright-tool-stage-',dir=parent))
        try:
            for name in ('sessions','runs','tmp','cache'):(stage/name).mkdir(mode=0o700)
            for name,(data,mode) in files.items():write_new(stage/name,data,mode)
            verify_files(stage,files)
            if inventory(profile)!=observed:raise RuntimeError('Dependencies changed during staging; preserve candidate')
            if base.exists():raise RuntimeError('Target appeared during staging; preserve candidate')
            publish(stage,base)
        except BaseException as exc:
            raise RuntimeError('Installation stopped; existing tools untouched; candidate retained at '+str(stage)) from exc
    print(json.dumps({'status':'INSTALLED','changed_files':len(files),'runtime':str(base),'client_fragment':str(base/'kilo.json')}))

#endregion
#region [J05] Bounded MCP protocol and cleanup of this process tree only

class Mcp:
    def __init__(self,launcher,folder,env):
        self.folder=folder
        self.log=(folder/'mcp-stderr.log').open('xb');os.chmod(self.log.name,0o600)
        try:
            self.child=subprocess.Popen([str(launcher)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,
                                        env=env,start_new_session=True)
        except BaseException:
            self.log.close();raise
        self.selector=selectors.DefaultSelector();self.selector.register(self.child.stdout,selectors.EVENT_READ)
        self.buffer=b'';self.number=0
    def request(self,method,params):
        self.number+=1;rid=self.number
        self.child.stdin.write((json.dumps({'jsonrpc':'2.0','id':rid,'method':method,'params':params})+'\n').encode());self.child.stdin.flush()
        deadline=time.monotonic()+RPC_TIMEOUT
        while True:
            if b'\n' in self.buffer:
                line,self.buffer=self.buffer.split(b'\n',1)
                message=json.loads(line)
                if message.get('id')==rid:
                    if 'error' in message:raise RuntimeError('MCP RPC error: '+method)
                    return message['result']
                continue
            remaining=deadline-time.monotonic()
            if remaining<=0:raise RuntimeError('MCP timeout: '+method)
            if not self.selector.select(remaining):raise RuntimeError('MCP timeout: '+method)
            chunk=os.read(self.child.stdout.fileno(),65536)
            if not chunk:raise RuntimeError('MCP exited before response: '+method)
            self.buffer+=chunk
            if len(self.buffer)>2*1024*1024:raise RuntimeError('MCP response exceeds bounded limit')
    def call(self,name,args):
        result=self.request('tools/call',{'name':name,'arguments':args})
        write_new(self.folder/('tool-'+str(self.number)+'-'+name+'.json'),encoded(result))
        if result.get('isError'):raise RuntimeError('MCP tool failed: '+name+'; private response retained in '+str(self.folder))
        return result
    def initialize(self):
        info=self.request('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'ai-model-installer-check','version':'1'}})
        self.child.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n');self.child.stdin.flush()
        return info,self.request('tools/list',{})['tools']
    def close(self):
        owned={self.child.pid}|descendant_pids(self.child.pid)
        groups=set()
        for pid in owned:
            try:
                group=os.getpgid(pid)
                if group in owned:groups.add(group)
            except ProcessLookupError:pass
        try:
            if self.child.poll() is None:
                self.child.stdin.close()
                try:self.child.wait(timeout=5)
                except subprocess.TimeoutExpired:pass
            # Playwright can put Brave into a separate process group. Signal
            # only groups captured from our actual descendants before teardown.
            for group in groups:
                try:os.killpg(group,signal.SIGTERM)
                except ProcessLookupError:pass
            deadline=time.monotonic()+2
            while groups and time.monotonic()<deadline:
                for group in tuple(groups):
                    try:os.killpg(group,0)
                    except ProcessLookupError:groups.discard(group)
                if groups:time.sleep(0.05)
            for group in groups:
                try:os.killpg(group,signal.SIGKILL)
                except ProcessLookupError:pass
            self.child.wait(timeout=5)
        finally:
            self.selector.close();self.child.stdout.close();self.log.close()

#endregion
#region [J06] Actual MCP/browser fixture and kernel sandbox observations

def text(result):
    return '\n'.join(block.get('text','') for block in result.get('content',[]) if block.get('type')=='text')


def descendant_pids(parent):
    seen=set();pending=[parent]
    while pending:
        parent=pending.pop()
        try:children=(Path('/proc')/str(parent)/'task'/str(parent)/'children').read_text().split()
        except (FileNotFoundError,PermissionError,ProcessLookupError):continue
        for raw in children:
            if raw.isdigit() and int(raw) not in seen:
                seen.add(int(raw));pending.append(int(raw))
                if len(seen)>512:raise RuntimeError('Owned browser process tree exceeds bounded limit')
    return seen


def sandbox_processes(mcp_pid,renderer_pids):
    rows=[]
    for pid in sorted(descendant_pids(mcp_pid)):
        directory=Path('/proc')/str(pid)
        try:
            args=(directory/'cmdline').read_bytes().split(b'\0')
            if not args or not args[0]:continue
            executable=os.readlink(directory/'exe')
            if executable!='/opt/brave.com/brave/brave':continue
            status=dict(line.split(':',1) for line in (directory/'status').read_text().splitlines() if ':' in line)
            renderer=b'--type=renderer' in args
            rows.append({'pid':int(directory.name),'renderer':renderer,'sandbox_disabled':b'--no-sandbox' in args,
                         'seccomp':int(status.get('Seccomp','-1').strip()),'no_new_privs':int(status.get('NoNewPrivs','-1').strip())})
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    if not rows or any(row['sandbox_disabled'] for row in rows):raise RuntimeError('Owned native browser process/sandbox not verified')
    descendants=descendant_pids(mcp_pid)
    for pid in renderer_pids:
        if type(pid) is not int:raise RuntimeError('CDP renderer PID invalid')
        # Sandboxed children can hide proc ancestry. The owned browser CDP
        # connection and exact process cgroup jointly establish scope.
        if (Path('/proc')/str(pid)/'cgroup').read_text()!=(Path('/proc')/str(mcp_pid)/'cgroup').read_text():
            raise RuntimeError('CDP renderer escaped the owned MCP cgroup')
        status=dict(line.split(':',1) for line in (Path('/proc')/str(pid)/'status').read_text().splitlines() if ':' in line)
        rows.append({'pid':pid,'renderer':True,'identified_by':'owned browser CDP SystemInfo',
                     'seccomp':int(status.get('Seccomp','-1').strip()),'no_new_privs':int(status.get('NoNewPrivs','-1').strip()),'sandbox_disabled':None})
    if not any(row['renderer'] and row['seccomp']==2 and row['no_new_privs']==1 for row in rows):
        raise RuntimeError('No owned sandboxed renderer verified')
    return rows


def browser_probe(base,folder):
    marker='playwright-tool-'+uuid.uuid4().hex
    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path!='/':self.send_error(404);return
            data=('<!doctype html><html><body><h1>'+marker+'</h1><button onclick="document.querySelector(\'output\').textContent=\'clicked\'">Confirm</button><output>pending</output></body></html>').encode()
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Fixture);server.timeout=3
    thread=threading.Thread(target=server.serve_forever,daemon=True);mcp=None
    try:
        thread.start();mcp=Mcp(base/'playwright-mcp',folder,clean_env(base))
        info,tools=mcp.initialize();names={t['name'] for t in tools}
        required={'browser_navigate','browser_snapshot','browser_evaluate','browser_close','browser_run_code_unsafe'}
        if not required<=names:raise RuntimeError('Required browser tools unavailable')
        mcp.call('browser_navigate',{'url':'chrome://sandbox/'})
        summary=text(mcp.call('browser_evaluate',{'function':'() => document.body.innerText'})).replace('\\n','\n').replace('\\t','\t').replace('\\r','\r')
        if not re.search(r'Seccomp-BPF sandbox\s+Yes',summary,re.I) or not re.search(r'(Namespace sandbox|PID namespaces)\s+Yes',summary,re.I):
            raise RuntimeError('Browser sandbox page did not confirm namespace/seccomp')
        url='http://127.0.0.1:'+str(server.server_port)+'/'
        nav=text(mcp.call('browser_navigate',{'url':url}))
        snapshot=text(mcp.call('browser_snapshot',{}))
        if marker not in snapshot:raise RuntimeError('Actual browser did not observe the fixture marker')
        click=text(mcp.call('browser_evaluate',{'function':'() => { document.querySelector("button").click(); return document.querySelector("output").textContent; }'}))
        if 'clicked' not in click:raise RuntimeError('Browser fixture interaction failed')
        # Fixed trusted diagnostic code, never model/web-supplied code. Sandbox
        # renderers can hide cmdline/exe while still exposing their kernel status.
        cdp=text(mcp.call('browser_run_code_unsafe',{'code':'async (page) => { const s = await page.context().browser().newBrowserCDPSession(); try { const p = await s.send("SystemInfo.getProcessInfo"); return p.processInfo.filter(x => x.type === "renderer").map(x => x.id); } finally { await s.detach(); } }'}))
        part=cdp.split('### Result',1)
        if len(part)!=2:raise RuntimeError('CDP renderer result missing')
        renderer_pids=json.JSONDecoder().raw_decode(part[1].lstrip())[0]
        if not isinstance(renderer_pids,list) or not 1<=len(renderer_pids)<=128:raise RuntimeError('CDP renderer count invalid')
        process_rows=sandbox_processes(mcp.child.pid,renderer_pids)
        mcp.call('browser_close',{})
        return {'status':'VERIFIED_MCP_AND_SANDBOXED_BROWSER','server':info['serverInfo'],'tools':sorted(names),
                'fixture_url':url,'fixture_marker':marker,'marker_observed':True,'interaction':'clicked',
                'sandbox_page_namespace_and_seccomp':True,'browser_processes':process_rows,'new_model_requests':0}
    finally:
        if mcp:mcp.close()
        server.shutdown();server.server_close();thread.join(timeout=5)

#endregion
#region [J07] Indexed verification run, retained on failure

def verify(profile):
    identity(profile);base=Path(profile['runtime'])
    observed=inventory(profile);files=desired(profile,observed);verify_files(base,files)
    folder=base/'runs'/('verify-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    receipt={'owner':OWNER,'status':'RUNNING','started_at':now(),'dependencies':observed,'run_directory':str(folder)}
    def checkpoint():
        p=folder/'receipt.json';temp=folder/'receipt.json.new';temp.write_bytes(encoded(receipt));temp.chmod(0o600);os.replace(temp,p)
    checkpoint()
    try:
        receipt['probe']=browser_probe(base,folder)
        if inventory(profile)!=observed:raise RuntimeError('Dependencies changed during browser verification')
        verify_files(base,files);receipt['status']='VERIFIED'
    except BaseException as exc:
        receipt.update(status='FAILED',error=type(exc).__name__+': '+str(exc));raise
    finally:
        receipt['finished_at']=now();checkpoint()
        index={'owner':OWNER,'files':{p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in folder.iterdir() if p.is_file()}}
        write_new(folder/'index.json',encoded(index))
    print(json.dumps(receipt,indent=2))

#endregion
#region [J08] CLI and read-only inspect

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__ or 'Reuse existing Spark Brave/MCP as a managed stdio browser tool; no sudo or downloads.')
    parser.add_argument('action',choices=('inspect','install','verify'))
    args=parser.parse_args(argv)
    def interrupted(signum,frame):raise RuntimeError('Interrupted by signal '+str(signum))
    signal.signal(signal.SIGTERM,interrupted)
    try:
        profile=load_profile()
        if args.action=='inspect':
            result={'status':'READ_ONLY_INSPECTION','profile':profile,'host':platform.node(),'native_host':platform.node()==profile['hostname']}
            if result['native_host']:
                result['dependencies']=inventory(profile);base=Path(profile['runtime']);result['installed']=base.exists()
                if base.exists():
                    try:
                        verify_files(base,desired(profile,result['dependencies']));result['managed_files_verified']=True
                    except RuntimeError:
                        legacy_files(base,profile,result['dependencies']);result['known_rejected_pilot_verified']=True
                        result['repair_required']='Short TMPDIR correction; exact legacy files/dependencies verified'
            print(json.dumps(result,indent=2))
        elif args.action=='install':install(profile)
        else:verify(profile)
    except (OSError,ValueError,RuntimeError,KeyError,subprocess.SubprocessError) as exc:
        print(json.dumps({'status':'FAILED','error':type(exc).__name__,'message':str(exc)}),file=sys.stderr);return 1
    return 0


if __name__=='__main__':sys.exit(main())
#endregion
