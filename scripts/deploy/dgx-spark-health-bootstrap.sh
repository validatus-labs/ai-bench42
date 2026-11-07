#!/usr/bin/env bash
# DGX Spark / GB10 health bridge: one stdlib-only deployment entrypoint.
# Run inspect/status/config as any user; install/run-once as root on spark-a922.
# Inputs: DGX_CHECK_INTERVAL (60s), DGX_RETENTION_DAYS (30), DGX_MODEL_PYTHON.
# Effects: managed health units, root-owned installed copy/config, /var/lib state.
# Never installs dependencies or changes Prometheus, node_exporter, vLLM or security.
#
# dgx-spark-health-bootstrap.sh
# |-- [J01] settings()       strict configuration, ownership and path validation
# |-- [J02] collect()        16 bounded, observational checks; unavailable = -1
# |-- [J03] exposition()    atomic snapshot -> freshness-aware Prometheus metrics
# |-- [J04] serve()         unprivileged loopback HTTP; never run checks on scrape
# |-- [J05] inspect_host()  read-only inventory, including user Prometheus
# |-- [J06] desired_files() root-owned copy + checker/exporter/timer definitions
# |-- [J07] install()       preflight all files -> backup -> converge -> verify
# |   `-- rollback()       restore only unchanged installer-owned candidates
# `-- [J08] main()          inspect | install | status | run-once | config
#
# VS Code: Ctrl+F -> [J01]...[J08]. Embedded Python uses #region folding;
# choose Python language mode temporarily for Ctrl+Shift+O function navigation.
# Example: bash scripts/deploy/dgx-spark-health-bootstrap.sh inspect
#          sudo bash scripts/deploy/dgx-spark-health-bootstrap.sh install
set -Eeuo pipefail
exec /usr/bin/python3 -B - "$0" "$@" <<'PYTHON'
# managed-by: dgx-spark-health-bootstrap
import argparse
import ast
import contextlib
import datetime
import fcntl
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

OWNER = 'AI-Model/dgx-spark-health/v1'
PREFIX = Path('/usr/local/lib/dgx-spark-health')
STATE = Path('/var/lib/dgx-spark-health')
CONFIG = Path('/etc/default/dgx-spark-health')
UNIT_DIR = Path('/etc/systemd/system')
SERVICE, TIMER, EXPORTER = ('dgx-spark-health.service', 'dgx-spark-health.timer', 'dgx-spark-health-exporter.service')
UNITS = (SERVICE, TIMER, EXPORTER)
MODEL = 'ai-model-vllm-kolibri-1.service'
PROJECT = Path('/home/validatus/workspace/AI-Model')
TARGET_HOST = 'spark-a922'
TARGET_RUNTIME = ''
SCRIPT = Path(sys.argv[1]).absolute()
IDS = ('memory.uma_pressure', 'memory.swap', 'pressure.cpu', 'pressure.memory', 'pressure.io',
       'storage.space', 'storage.inodes', 'kernel.oom_events', 'gpu.xid_error',
       'gpu.nvml_available', 'gpu.temperature', 'gpu.power_telemetry',
       'vllm.service', 'vllm.health', 'vllm.queue', 'cuda.torch_cpu_only')


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def command(args, timeout=8):
    return subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, timeout=timeout, env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C',
                          'PYTHONDONTWRITEBYTECODE': '1'})


def checked(args, timeout=20):
    result = command(args, timeout)
    if result.returncode:
        raise RuntimeError(Path(args[0]).name + ' failed: ' + result.stderr[-600:])
    return result.stdout


def atomic(path, data, mode=0o644):
    temp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with temp.open('xb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


#region [J01] Strict settings and managed ownership

def safe_path(path):
    for part in (path,) + tuple(path.parents):
        if part.is_symlink():
            raise RuntimeError('Symlink refused: ' + str(part))
    return path


def interval_seconds(interval):
    if not isinstance(interval, str) or not re.fullmatch(r'[1-9][0-9]{0,3}[smh]', interval):
        raise ValueError('DGX_CHECK_INTERVAL must be like 60s, 2m or 1h')
    seconds = int(interval[:-1]) * {'s': 1, 'm': 60, 'h': 3600}[interval[-1]]
    if not 30 <= seconds <= 3600:
        raise ValueError('Check interval must be between 30s and 1h')
    return seconds


def validate_config(data):
    base_keys = {'owner', 'interval', 'model_unit', 'model_python', 'vllm_url', 'port'}
    if not base_keys <= set(data) or set(data) - base_keys - {'runtime_root', 'retention_days'}:
        raise ValueError('Unknown/missing health configuration key')
    if data['owner'] != OWNER or data['model_unit'] != MODEL or data['vllm_url'] != 'http://127.0.0.1:8000':
        raise ValueError('Expected the owned local Kolibri endpoint/unit')
    if type(data['port']) is not int or data['port'] != 9817:
        raise ValueError('Health exporter must use loopback port9817')
    interval_seconds(data['interval'])
    retention_value(data.get('retention_days', 30))
    runtime = safe_path(Path(data.get('runtime_root', str(PROJECT/'runtime/spark-a922'))))
    if not runtime.is_absolute() or '..' in runtime.parts:
        raise ValueError('Invalid health runtime root')
    python = data['model_python']
    if not isinstance(python, str) or (python and (not python.startswith(str(runtime/'build/dgx-spark-vllm/releases') + '/')
            or not python.endswith('/venv/bin/python') or '..' in Path(python).parts or any(c in python for c in '\r\n\x00'))):
        raise ValueError('Model Python must be an absolute retained Spark release venv, or empty')
    return data


def retention_value(value):
    if isinstance(value, str) and value in ('forever', 'never'):
        return 'forever'
    if type(value) is int and value in (7, 30, 90, 180, 365):
        return value
    if isinstance(value, str) and value in ('7', '30', '90', '180', '365'):
        return int(value)
    raise ValueError('Retention must be forever, 7, 30, 90, 180 or 365 days (never is an alias)')


def settings():
    safe_path(CONFIG)
    st = CONFIG.stat()
    if st.st_uid != 0 or st.st_mode & 0o022 or not stat.S_ISREG(st.st_mode):
        raise RuntimeError('Configuration must be a root-owned, non-writable regular file')
    return validate_config(json.loads(CONFIG.read_text()))


def live_unit():
    result = command(['/usr/bin/systemctl', 'show', MODEL, '-p', 'LoadState', '-p', 'MainPID', '-p', 'ActiveState', '-p', 'ControlGroup'])
    facts = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if result.returncode and facts.get('LoadState') != 'not-found':
        raise RuntimeError('Model unit inspection unavailable')
    return facts


def get(url, limit=2*1024*1024):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=3) as response:
        body = response.read(limit + 1)
        if len(body) > limit:
            raise RuntimeError('Response exceeds bounded body limit')
        if response.status != 200:
            raise RuntimeError('Endpoint did not return HTTP200')
        return body


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None

#endregion
#region [J02] Sixteen observational health checks

def numeric(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('Non-finite observation')
    return result


def severity_low(value, warning, critical):
    return 3 if value < critical else 2 if value < warning else 0


def severity_high(value, warning, critical):
    return 3 if value >= critical else 2 if value >= warning else 0


def metric(body, name):
    values = [numeric(line.rsplit(None, 1)[1]) for line in body.splitlines()
              if line.startswith(name + '{') or line.startswith(name + ' ')]
    if not values:
        raise ValueError('Required model metric unavailable')
    return sum(values)


def journal_events():
    # Recent window only. No raw messages survive this function or enter metrics.
    result = command(['/usr/bin/journalctl', '-k', '--since=-10min', '--no-pager',
                      '--output=json', '--lines=2001'], timeout=10)
    if result.returncode or result.stderr.strip():
        raise RuntimeError('Recent kernel journal unavailable or access-limited')
    lines = result.stdout.splitlines()
    if len(lines) > 2000:
        raise RuntimeError('Kernel journal window truncated')
    messages = [str(json.loads(line).get('MESSAGE', '')) for line in lines]
    return {'oom': sum(bool(re.search(r'Out of memory:|oom-kill:|Killed process .*total-vm:', m, re.I)) for m in messages),
            'xid': sum(bool(re.search(r'NVRM:.*Xid', m)) for m in messages)}


def torch_observation(python, facts):
    # Never execute/import user-writable model Python as root or allocate CUDA memory.
    pid = facts.get('MainPID', '0')
    if not python or not pid.isdigit() or pid == '0' or facts.get('ActiveState') != 'active':
        raise RuntimeError('No configured, active model Python')
    cmdline = (Path('/proc')/pid/'cmdline').read_bytes().split(b'\0')
    if not cmdline or os.fsdecode(cmdline[0]) != python:
        raise RuntimeError('Configured Python differs from live model command')
    venv = Path(python).parent.parent
    candidates = list((venv/'lib').glob('python3.*/site-packages/torch/version.py'))
    if len(candidates) != 1:
        raise RuntimeError('Exact torch metadata unavailable')
    tree = ast.parse(candidates[0].read_text())
    cuda = None
    found = False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'cuda' for t in node.targets):
            cuda, found = ast.literal_eval(node.value), True
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == 'cuda':
            cuda, found = ast.literal_eval(node.value), True
    if not found:
        raise RuntimeError('Torch CUDA build field unavailable')
    if cuda is None:
        return 3, 0, 'Configured live torch metadata reports a CPU-only build'
    if not isinstance(cuda, str) or not re.fullmatch(r'[0-9]+\.[0-9]+', cuda):
        raise RuntimeError('Unexpected CUDA metadata')
    cg = facts['ControlGroup']
    if cg != '/system.slice/' + MODEL:
        raise RuntimeError('Unexpected model cgroup')
    pids = (Path('/sys/fs/cgroup')/cg.lstrip('/')/'cgroup.procs').read_text().split()
    for worker in pids[:128]:
        if not worker.isdigit():
            continue
        try:
            maps = (Path('/proc')/worker/'maps').read_text()
        except (FileNotFoundError, PermissionError):
            continue
        if 'libtorch_cuda.so' in maps and re.search(r'/libcuda\.so', maps):
            return 0, 1, 'CUDA-built torch and driver libraries mapped in live model cgroup; no fresh CUDA execution test'
    raise RuntimeError('GPU-built torch metadata, but live CUDA library mapping unverified')


def collect(config):
    started = time.time()
    report = {'owner': OWNER, 'collected_at': now(), 'timestamp': started,
              'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'config_sha256': sha(encoded(config)), 'checks': []}
    cache = {}
    def cached(key, call):
        if key not in cache:
            try:
                cache[key] = (True, call())
            except Exception as exc:
                cache[key] = (False, exc)
        ok, value = cache[key]
        if not ok:
            raise value
        return value
    def check(check_id, call):
        try:
            level, value, explanation = call()
            if level not in (-1, 0, 1, 2, 3):
                raise ValueError('Invalid check status')
            row = {'check_id': check_id, 'status': level, 'detail': explanation}
            if value is not None:
                row['value'] = numeric(value)
        except Exception as exc:
            row = {'check_id': check_id, 'status': -1, 'detail': 'Observation unavailable: ' + type(exc).__name__}
        report['checks'].append(row)
    def mem():
        return {line.split(':',1)[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line}
    def available():
        m=cached('mem',mem); v=m['MemAvailable']/m['MemTotal']*100
        return severity_low(v,10,5),v,'Host MemAvailable percent (unified memory, not discrete GPU VRAM)'
    def swap():
        m=cached('mem',mem); value=m['SwapTotal']-m['SwapFree']
        return (2 if value else 0),value,'Host swap used bytes; not an OOM-cause diagnosis'
    check('memory.uma_pressure', available)
    check('memory.swap', swap)
    for name, warning, critical in [('cpu',25,50),('memory',5,20),('io',10,30)]:
        def pressure(name=name,warning=warning,critical=critical):
            lines=Path('/proc/pressure',name).read_text().splitlines()
            some=next(line for line in lines if line.startswith('some '))
            value=numeric(dict(item.split('=') for item in some.split()[1:])['avg10'])
            return severity_high(value,warning,critical),value,'PSI some avg10 percent; threshold is a heuristic'
        check('pressure.'+name,pressure)
    for name, free, total in [('space','f_bavail','f_blocks'),('inodes','f_favail','f_files')]:
        def storage(free=free,total=total):
            s=cached('statvfs',lambda:os.statvfs(PROJECT))
            v=getattr(s,free)/getattr(s,total)*100
            return severity_low(v,10,5),v,'Available filesystem percent for the project mount'
        check('storage.'+name,storage)
    for check_id,key in [('kernel.oom_events','oom'),('gpu.xid_error','xid')]:
        def events(key=key):
            v=cached('journal',journal_events)[key]
            return (3 if v else 0),v,'Matching messages in last10min; count is log matches, not unique incidents'
        check(check_id,events)
    def nvml():
        text=checked(['/usr/bin/nvidia-smi','--query-gpu=name,driver_version','--format=csv,noheader'],timeout=8).strip()
        if not text or 'GB10' not in text:
            raise RuntimeError('Expected GB10 was not observed')
        return 0,1,'nvidia-smi queried GB10/driver; this is not full NVML/DCGM qualification'
    check('gpu.nvml_available',nvml)
    for field,check_id in [('temperature.gpu','gpu.temperature'),('power.draw','gpu.power_telemetry')]:
        def gpu(field=field):
            text=checked(['/usr/bin/nvidia-smi','--query-gpu='+field,'--format=csv,noheader,nounits'],timeout=8).strip()
            v=numeric(text)
            return (severity_high(v,80,90) if field=='temperature.gpu' else 0),v,('GPU temperature Celsius; heuristic80/90 thresholds' if field=='temperature.gpu' else 'Reported GPU power watts; not total system power or efficiency')
        check(check_id,gpu)
    def service():
        f=cached('unit',live_unit)
        return (0 if f.get('ActiveState')=='active' and f.get('MainPID','0')!='0' else 3),None,'Observed model systemd state'
    check('vllm.service',service)
    check('vllm.health',lambda:(0,len(get(config['vllm_url']+'/health',65536)),'Model /health returned HTTP200; no generation request'))
    def queue():
        body=cached('vllm_metrics',lambda:get(config['vllm_url']+'/metrics').decode())
        running=metric(body,'vllm:num_requests_running'); waiting=metric(body,'vllm:num_requests_waiting')
        cache['queue_observation']={'running':running,'waiting':waiting}
        return severity_high(waiting,2,8),waiting,'Waiting requests (heuristic2/8); max_num_seqs remains1'
    check('vllm.queue',queue)
    check('cuda.torch_cpu_only',lambda:torch_observation(config['model_python'],cached('unit',live_unit)))
    assert tuple(row['check_id'] for row in report['checks'])==IDS
    report.update(duration_seconds=time.time()-started, model_unit=cache.get('unit',(False,{}))[1] if cache.get('unit',(False,))[0] else {}, queue=cache.get('queue_observation',{}))
    return report

#endregion
#region [J03] Atomic, freshness-aware snapshots and metrics

def read_report(config):
    path=STATE/'report.json'
    if path.is_symlink() or path.stat().st_size>128*1024:
        raise RuntimeError('Invalid snapshot path/size')
    data=json.loads(path.read_text())
    if data['owner']!=OWNER or tuple(r['check_id'] for r in data['checks'])!=IDS:
        raise RuntimeError('Unexpected snapshot schema')
    if data['config_sha256']!=sha(encoded(config)):
        raise RuntimeError('Snapshot configuration changed')
    return data


def exposition(report, config, timestamp=None, boot_id=None):
    timestamp=time.time() if timestamp is None else timestamp
    boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip() if boot_id is None else boot_id
    age=timestamp-numeric(report['timestamp'])
    stale=age<0 or age>interval_seconds(config['interval'])*3+30 or report['boot_id']!=boot_id
    lines=['# HELP dgx_health_check_status -1 unknown, 0 OK, 1 info, 2 warning, 3 critical.',
           '# TYPE dgx_health_check_status gauge',
           '# TYPE dgx_health_snapshot_stale gauge','dgx_health_snapshot_stale '+str(int(stale)),
           '# TYPE dgx_health_last_collection_timestamp_seconds gauge','dgx_health_last_collection_timestamp_seconds '+str(report['timestamp']),
           '# TYPE dgx_health_snapshot_age_seconds gauge','dgx_health_snapshot_age_seconds '+str(age),
           '# TYPE dgx_health_collection_duration_seconds gauge','dgx_health_collection_duration_seconds '+str(report['duration_seconds'])]
    for row in report['checks']:
        label='{check_id='+json.dumps(row['check_id'])+'}'
        lines.append('dgx_health_check_status'+label+' '+str(-1 if stale else row['status']))
        if not stale and 'value' in row:
            lines.append('dgx_health_observation'+label+' '+str(row['value']))
    return '\n'.join(lines)+'\n',stale


def history_file(path):
    safe_path(path)
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or st.st_nlink != 1 or stat.S_IMODE(st.st_mode) != 0o600:
        raise RuntimeError('Untrusted health history file: ' + str(path))
    if st.st_size > 16 * 1024 * 1024:
        raise RuntimeError('Health history hour exceeds 16 MiB; inspect collection frequency')


def history_rows(path, hour):
    history_file(path)
    raw = path.read_bytes()
    if raw and not raw.endswith(b'\n'):
        raise RuntimeError('Incomplete health history hour: ' + str(path))
    rows = []
    for line in raw.splitlines():
        if len(line) > 128 * 1024:
            raise RuntimeError('Oversized health history snapshot')
        row = json.loads(line)
        timestamp = numeric(row['timestamp'])
        if row.get('owner') != OWNER or not hour <= timestamp < hour + 3600:
            raise RuntimeError('Unexpected health history snapshot')
        rows.append((timestamp, line + b'\n'))
    return rows


def archive_report(report, config):
    """Called under the collector lock; manage only our private hourly history."""
    folder = safe_path(STATE / 'history')
    if not folder.exists():
        folder.mkdir(mode=0o700)
    st = folder.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) != 0o700:
        raise RuntimeError('Untrusted health history directory')
    marker = folder / 'owner.json'
    identity = {'owner': OWNER, 'format': 'hourly-jsonl/v1'}
    if marker.exists() or marker.is_symlink():
        history_file(marker)
        if marker.read_bytes() != encoded(identity):
            raise RuntimeError('Unexpected health history ownership')
    elif any(folder.iterdir()):
        raise RuntimeError('Refuse unregistered health history')
    else:
        atomic(marker, encoded(identity), 0o600)
    hours = []
    for path in folder.iterdir():
        if path.name == 'owner.json':
            continue
        if not re.fullmatch(r'[0-9]{8}T[0-9]{2}0000Z\.jsonl', path.name):
            raise RuntimeError('Unknown health history entry: ' + path.name)
        history_file(path)
        hour = datetime.datetime.strptime(path.name, '%Y%m%dT%H0000Z.jsonl').replace(tzinfo=datetime.timezone.utc).timestamp()
        hours.append((path, hour))
    timestamp = numeric(report['timestamp'])
    date = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
    path = folder / date.strftime('%Y%m%dT%H0000Z.jsonl')
    rows = history_rows(path, date.timestamp()) if path.exists() else []
    line = (json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    if len(line) > 128 * 1024:
        raise RuntimeError('Oversized health history snapshot')
    content = b''.join(row for _, row in rows) + line
    if len(content) > 16 * 1024 * 1024:
        raise RuntimeError('Health history hour exceeds 16 MiB; inspect collection frequency')
    atomic(path, content, 0o600)
    retention = retention_value(config.get('retention_days', 30))
    if retention == 'forever':
        return
    cutoff = time.time() - retention * 86400
    # Expired hours can be unlinked; trim the boundary hour by snapshot timestamp.
    # The current hour is necessarily newer than a supported retention period.
    for old, hour in hours:
        if hour + 3600 <= cutoff:
            old.unlink()
        elif hour < cutoff:
            kept = b''.join(line for ts, line in history_rows(old, hour) if ts >= cutoff)
            if kept:
                if kept != old.read_bytes():
                    atomic(old, kept, 0o600)
            else:
                old.unlink()


def run_collection():
    root_required()
    config=settings()
    with (STATE/'private/collector.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        report=collect(config)
        archive_report(report,config)
        atomic(STATE/'report.json',encoded(report))
    print(json.dumps({'status':'COLLECTED','checks':len(report['checks']),
        'levels':{str(level):sum(r['status']==level for r in report['checks']) for level in (-1,0,1,2,3)},
        'retention_days':retention_value(config.get('retention_days',30)),'timestamp':report['collected_at']}))

#endregion
#region [J04] Loopback HTTP; exporter never executes probes

def handler_for(config):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.connection.settimeout(3)
            if self.path not in ('/metrics','/healthz'):
                self.send_error(404);return
            try:
                body,stale=exposition(read_report(config),config)
                data=(body if self.path=='/metrics' else ('stale\n' if stale else 'ready\n')).encode()
                code=503 if self.path=='/healthz' and stale else 200
            except Exception:
                code,data=503,b'health snapshot unavailable\n'
            self.send_response(code)
            self.send_header('Content-Type','text/plain; version=0.0.4; charset=utf-8')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
        def log_message(self,*args):
            pass
    return Handler


def serve():
    config=settings()
    class BoundedHTTPServer(HTTPServer):
        def get_request(self):
            sock,addr=super().get_request();sock.settimeout(3);return sock,addr
    with BoundedHTTPServer(('127.0.0.1',config['port']),handler_for(config)) as server:
        server.serve_forever()

#endregion
#region [J05] Read-only inventory and status

def inspect_host():
    result={'status':'READ_ONLY_INSPECTION','time':now(),'hostname':platform.node(),'architecture':platform.machine(),
            'python':platform.python_version(),'system_units':{},'user_units':{},'endpoints':{}}
    for name in UNITS+('prometheus.service','prometheus-node-exporter.service','node_exporter.service',MODEL):
        p=command(['/usr/bin/systemctl','show',name,'-p','LoadState','-p','ActiveState','-p','MainPID'])
        result['system_units'][name]=dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)
    for name in ('ai-model-benchmark-prometheus.service','ai-model-benchmark-metrics.service'):
        p=command(['/usr/bin/systemctl','--user','is-active',name])
        result['user_units'][name]=p.stdout.strip() or 'unavailable'
    for port,path in [(8000,'/health'),(9090,'/-/ready'),(9100,'/metrics'),(9199,'/metrics'),(9817,'/healthz')]:
        try: get('http://127.0.0.1:'+str(port)+path);result['endpoints'][str(port)]='HTTP200'
        except Exception as e:result['endpoints'][str(port)]='unavailable: '+type(e).__name__
    print(json.dumps(result,indent=2))


def status():
    config=settings();report=read_report(config);_,stale=exposition(report,config)
    print('Collected '+report['collected_at']+(' [STALE]' if stale else ' [FRESH]'))
    retention=retention_value(config.get('retention_days',30))
    print('Local history retention: '+('forever (never delete)' if retention=='forever' else str(retention)+' days'))
    for row in report['checks']:
        print('{:<26} {:>2}  {}'.format(row['check_id'],-1 if stale else row['status'],row['detail']))
    print('Prometheus scrape job is printed by config; installation never edits Prometheus.')

#endregion
#region [J06] Managed systemd files

def desired_files(source, config):
    common='''NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
UMask=0022
Nice=10
CPUQuota=20%
MemoryMax=192M
TasksMax=32
'''
    unit_header='# managed-by: dgx-spark-health-bootstrap\n'
    checker=unit_header+'''[Unit]
Description=DGX Spark observational health checks
After=network.target

[Service]
Type=oneshot
User=root
ExecStart=/bin/bash /usr/local/lib/dgx-spark-health/bootstrap.sh _collect
TimeoutStartSec=55
ReadWritePaths=/var/lib/dgx-spark-health
'''+common
    exporter=unit_header+'''[Unit]
Description=DGX Spark cached health metrics (loopback only)
After=network.target

[Service]
DynamicUser=yes
ExecStart=/bin/bash /usr/local/lib/dgx-spark-health/bootstrap.sh _serve
Restart=on-failure
RestartSec=5
RestrictAddressFamilies=AF_INET AF_UNIX
CapabilityBoundingSet=
'''+common+'''
[Install]
WantedBy=multi-user.target
'''
    timer=unit_header+'''[Unit]
Description=DGX Spark health check interval

[Timer]
OnBootSec=30s
OnUnitInactiveSec='''+config['interval']+'''
AccuracySec=1s
Unit=dgx-spark-health.service

[Install]
WantedBy=timers.target
'''
    return {PREFIX/'bootstrap.sh':(source,0o755),CONFIG:(encoded(config),0o644),
            UNIT_DIR/SERVICE:(checker.encode(),0o644),UNIT_DIR/TIMER:(timer.encode(),0o644),
            UNIT_DIR/EXPORTER:(exporter.encode(),0o644)}

#endregion
#region [J07] Preflight, backup, convergence and guarded rollback

def root_required():
    if os.geteuid()!=0:
        raise RuntimeError('Run this action with sudo; inspect/status/config do not need root')


def verify_registry(registry, paths):
    if registry.get('owner')!=OWNER or set(registry.get('files',{}))!={str(p) for p in paths}:
        raise RuntimeError('Unexpected installation registry')
    for p in paths:
        safe_path(p);st=p.stat();row=registry['files'][str(p)]
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=0 or sha(p.read_bytes())!=row['sha256'] or stat.S_IMODE(st.st_mode)!=row['mode']:
            raise RuntimeError('Managed file diverged: '+str(p))


def unit_state(name):
    raw=checked(['/usr/bin/systemctl','show',name,'-p','LoadState','-p','ActiveState','-p','UnitFileState','-p','FragmentPath','-p','DropInPaths','-p','MainPID'])
    return dict(line.split('=',1) for line in raw.splitlines())


def ensure_local_ready():
    # Bounded readiness observation, never an inference request or server restart.
    deadline=time.monotonic()+10
    while True:
        try:
            get('http://127.0.0.1:9817/healthz',65536)
            return
        except Exception:
            if time.monotonic()>=deadline:raise RuntimeError('Health exporter did not become ready')
            time.sleep(0.25)


def rollback(previous, old_states, desired, folder):
    # Install lock is still held; do not overwrite edits made during installation.
    for path,(data,mode) in desired.items():
        safe_path(path)
        if path.exists() and (path.read_bytes()!=data or path.stat().st_uid!=0 or stat.S_IMODE(path.stat().st_mode)!=mode):
            raise RuntimeError('Rollback refused divergent candidate: '+str(path))
    for name in (TIMER,EXPORTER,SERVICE):
        checked(['/usr/bin/systemctl','stop',name],timeout=65)
    # Remove newly created enablement while candidate units still exist.
    for name in (TIMER,EXPORTER):
        if old_states[name].get('UnitFileState')!='enabled':
            checked(['/usr/bin/systemctl','disable',name])
    for path,old in previous.items():
        if old is None:
            if path.exists():path.unlink()
        else:
            atomic(path,old[0],old[1])
    checked(['/usr/bin/systemctl','daemon-reload'])
    for name in (TIMER,EXPORTER):
        old=old_states[name]
        if old.get('UnitFileState')=='enabled':checked(['/usr/bin/systemctl','enable',name])
        if old.get('ActiveState')=='active':checked(['/usr/bin/systemctl','start',name])
    atomic(folder/'rollback.json',encoded({'status':'PREVIOUS_MANAGED_FILES_RESTORED','time':now()}),0o600)


def install_host_required():
    root_required()
    if platform.node()!=TARGET_HOST or platform.machine()!='aarch64' or Path('/proc/1/comm').read_text().strip()!='systemd':
        raise RuntimeError('Install only on native spark-a922 with systemd PID1')


def install():
    install_host_required()
    # Validate all inputs/ownership before the first write; do not trust marker comments.
    safe_path(SCRIPT)
    source=SCRIPT.read_bytes()
    if b'# managed-by: dgx-spark-health-bootstrap' not in source:
        raise RuntimeError('Expected complete managed bootstrap source')
    registry_path=PREFIX/'installed.json'
    for path in (PREFIX,STATE,STATE/'private',CONFIG,registry_path):
        safe_path(path)
        if path.exists() and (path.stat().st_uid!=0 or path.stat().st_mode&0o022):
            raise RuntimeError('Untrusted managed path ownership/mode: '+str(path))
    registry=json.loads(registry_path.read_text()) if registry_path.exists() else None
    if registry:
        config=settings()
    else:
        config={'owner':OWNER,'interval':'60s','model_unit':MODEL,'model_python':'','vllm_url':'http://127.0.0.1:8000','port':9817}
        if TARGET_RUNTIME:
            config['runtime_root'] = TARGET_RUNTIME
        # Reading argv establishes the interpreter path; no user Python executes.
        facts=live_unit();pid=facts.get('MainPID','0')
        if pid.isdigit() and pid!='0':
            config['model_python']=os.fsdecode((Path('/proc')/pid/'cmdline').read_bytes().split(b'\0')[0])
    if 'DGX_CHECK_INTERVAL' in os.environ:config['interval']=os.environ['DGX_CHECK_INTERVAL']
    if 'DGX_MODEL_PYTHON' in os.environ:config['model_python']=os.environ['DGX_MODEL_PYTHON']
    config['retention_days']=retention_value(os.environ.get('DGX_RETENTION_DAYS',config.get('retention_days',30)))
    validate_config(config)
    desired=desired_files(source,config)
    old_states={name:unit_state(name) for name in UNITS}
    if any(s.get('DropInPaths') for s in old_states.values()):
        raise RuntimeError('Refuse health unit drop-ins; preserve them for review')
    if registry:
        verify_registry(registry,desired)
    else:
        for path in desired:
            safe_path(path)
            if path.exists():raise RuntimeError('Refuse unmanaged target: '+str(path))
        for name,s in old_states.items():
            if s.get('LoadState')!='not-found':raise RuntimeError('Refuse pre-existing unmanaged unit: '+name)
        if PREFIX.exists() or STATE.exists():
            raise RuntimeError('Refuse existing unregistered health directory')
    # A listening managed exporter is allowed only with exact unit ownership.
    with socket.socket() as probe:
        try:probe.bind(('127.0.0.1',9817))
        except OSError:
            s=old_states[EXPORTER]
            if not registry or s.get('ActiveState')!='active' or s.get('FragmentPath')!=str(UNIT_DIR/EXPORTER):
                raise RuntimeError('Port9817 is occupied by an unowned listener')
    PREFIX.mkdir(mode=0o755,parents=True,exist_ok=True)
    STATE.mkdir(mode=0o755,parents=True,exist_ok=True)
    (STATE/'private').mkdir(mode=0o700,exist_ok=True)
    with (STATE/'private/install.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Detect source/registry changes since preflight, before installing anything.
        if registry:verify_registry(registry,desired)
        changed={p:row for p,row in desired.items() if not p.exists() or p.read_bytes()!=row[0] or stat.S_IMODE(p.stat().st_mode)!=row[1]}
        folder=STATE/'private'/('install-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8])
        folder.mkdir(mode=0o700)
        previous={p:(p.read_bytes(),stat.S_IMODE(p.stat().st_mode)) if p.exists() else None for p in desired}
        old_registry=registry_path.read_bytes() if registry_path.exists() else None
        journal={'owner':OWNER,'status':'PREPARED','started_at':now(),'changed':[str(p) for p in changed],'previous_units':old_states,'backups':{}}
        for i,(path,old) in enumerate(previous.items()):
            if old:
                backup=folder/('backup-'+str(i));atomic(backup,old[0],0o600)
                if sha(backup.read_bytes())!=sha(old[0]):raise RuntimeError('Backup hash mismatch')
                journal['backups'][str(path)]={'file':backup.name,'sha256':sha(old[0]),'bytes':len(old[0]),'mode':old[1]}
        if old_registry:atomic(folder/'installed-before.json',old_registry,0o600)
        atomic(folder/'transaction.json',encoded(journal),0o600)
        try:
            for p,(data,mode) in changed.items():atomic(p,data,mode)
            # systemd verifies the actual candidate files before they can be enabled.
            checked(['/usr/bin/systemd-analyze','verify']+[str(UNIT_DIR/n) for n in UNITS],timeout=25)
            if changed:checked(['/usr/bin/systemctl','daemon-reload'])
            checker_changed=bool({PREFIX/'bootstrap.sh',CONFIG,UNIT_DIR/SERVICE}&set(changed))
            if checker_changed or not (STATE/'report.json').is_file():
                checked(['/usr/bin/systemctl','start',SERVICE],timeout=65)
            if {PREFIX/'bootstrap.sh',CONFIG,UNIT_DIR/EXPORTER}&set(changed) and old_states[EXPORTER].get('ActiveState')=='active':
                checked(['/usr/bin/systemctl','restart',EXPORTER])
            checked(['/usr/bin/systemctl','enable','--now',EXPORTER,TIMER])
            if UNIT_DIR/TIMER in changed and old_states[TIMER].get('ActiveState')=='active':
                checked(['/usr/bin/systemctl','restart',TIMER])
            ensure_local_ready()
            for name in (EXPORTER,TIMER):
                checked(['/usr/bin/systemctl','is-enabled','--quiet',name]);checked(['/usr/bin/systemctl','is-active','--quiet',name])
            new_registry={'owner':OWNER,'files':{str(p):{'sha256':sha(data),'mode':mode} for p,(data,mode) in desired.items()}}
            if old_registry!=encoded(new_registry):atomic(registry_path,encoded(new_registry),0o600)
            journal.update(status='VERIFIED',finished_at=now(),exporter=unit_state(EXPORTER))
        except BaseException as exc:
            journal.update(status='FAILED',error=type(exc).__name__+': '+str(exc))
            try:
                rollback(previous,old_states,desired,folder)
                if old_registry:atomic(registry_path,old_registry,0o600)
            except BaseException as recovery:journal['rollback_error']=str(recovery)
            raise
        finally:atomic(folder/'transaction.json',encoded(journal),0o600)
    print(json.dumps({'status':'INSTALLED' if changed else 'UNCHANGED','changed_files':len(changed),'receipt':str(folder/'transaction.json'),'config':str(CONFIG),'metrics':'http://127.0.0.1:9817/metrics'}))

#endregion
#region [J08] Public CLI

def main(args=None):
    parser=argparse.ArgumentParser(prog=SCRIPT.name,description='DGX Spark health bridge:16observational checks, loopback metrics and owned systemd timer. No Prometheus/model changes.')
    parser.add_argument('action',choices=('inspect','install','status','run-once','config','_collect','_serve'))
    retention=parser.add_mutually_exclusive_group()
    retention.add_argument('--retention',choices=('forever','never','7','30','90','180','365'),help='local history days; fresh default 30; preserve existing setting on repeat')
    retention.add_argument('--never',dest='retention',action='store_const',const='forever',help='alias for --retention forever (never delete history)')
    args=parser.parse_args(args)
    try:
        if args.retention is not None:
            if args.action!='install':raise ValueError('--retention/--never requires install')
            os.environ['DGX_RETENTION_DAYS']=str(retention_value(args.retention))
        if args.action=='inspect':inspect_host()
        elif args.action=='install':install()
        elif args.action=='status':status()
        elif args.action=='run-once':
            root_required();settings();checked(['/usr/bin/systemctl','start',SERVICE],timeout=65);status()
        elif args.action=='config':
            print("# Add manually to EXISTING Prometheus scrape_configs; nothing is modified.\n- job_name: dgx-spark-health\n  scrape_interval: 30s\n  static_configs:\n    - targets: ['127.0.0.1:9817']\n# Container loopback refers to that container, not the host.")
        elif args.action=='_collect':run_collection()
        elif args.action=='_serve':serve()
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:
        print(json.dumps({'status':'FAILED','error':type(exc).__name__,'message':str(exc)}),file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main(sys.argv[2:]))
#endregion
PYTHON
