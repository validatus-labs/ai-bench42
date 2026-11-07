#!/usr/bin/env python3
"""Converge private loopback metrics as the normal OS account; never touch vLLM.

prometheus_bootstrap.py
|-- settings()/layout()  validated JSON -> exact runtime, binaries, config, units
|-- inspect()/verify()   file pins + systemd + actual Prometheus scrape targets
`-- install()           preflight -> checksum release -> backup -> reload -> verify

Invoked by scripts/bootstrap.py --metrics; uses no privileged package installer.
Existing exact legacy config may gain only the health scrape; unknown drift stops.
"""
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import tarfile
import time
import urllib.request
import uuid

import bootstrap_components as common

OWNER = 'AI-Bench42/monitoring/v1'
VERSION = '3.15.0'
ARCHIVE_SHA = 'f1f90ec08e849d494ca66c611470afc50192f0355f1a61c33f2cbde02d067823'
UNITS = ('ai-model-benchmark-prometheus.service', 'ai-model-benchmark-metrics.service')
HERE = Path(__file__).resolve().parent


def require(value, message):
    if not value: raise RuntimeError(message)


def settings(target, supplied=None):
    data = dict(supplied or {})
    require(not set(data) - {'schema_version', 'runtime', 'include_health'}, 'Unknown monitoring policy fields')
    require(data.get('schema_version', 1) == 1 and type(data.get('include_health', True)) is bool, 'Invalid monitoring policy')
    base = common.safe(Path(data.get('runtime') or (Path(target['runtime']) / 'tools/monitoring')))
    # Existing external monitoring can be explicitly adopted; never guess paths.
    require(base.is_relative_to(Path(target['home']) / 'workspace') or base.is_relative_to(Path(target['runtime'])), 'Monitoring runtime must be in the account workspace or selected runtime')
    return {'schema_version': 1, 'runtime': str(base), 'include_health': data.get('include_health', True)}


def text(data): return (json.dumps(data, indent=2) + '\n').encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()
def run(argv): return subprocess.check_output([str(x) for x in argv], text=True, stderr=subprocess.STDOUT, timeout=60)


def private(path):
    common.safe(path)
    if not path.exists(): path.mkdir(parents=True, mode=0o700)
    require(path.is_dir() and path.stat().st_uid == os.getuid() and not path.stat().st_mode & 0o022, 'Untrusted monitoring directory: ' + str(path))


def checked_file(path):
    common.safe(path)
    require(path.is_file() and path.stat().st_uid == os.getuid() and not path.stat().st_mode & 0o022, 'Untrusted monitoring file: ' + str(path))
    return path.read_bytes()


def known_file(path, allowed):
    """Accept exact account-owned legacy 0664 files for explicit mode migration."""
    common.safe(path)
    require(path.is_file() and path.stat().st_uid == os.getuid(), 'Untrusted monitoring file: ' + str(path))
    mode=path.stat().st_mode & 0o777
    require(mode in (0o600,0o644,0o664) and path.stat().st_gid == os.getgid(), 'Unexpected monitoring ownership/mode: ' + str(path))
    raw=path.read_bytes()
    require(raw in allowed, 'Preserve divergent monitoring file: ' + str(path))
    return raw


def migrate_legacy_modes(base, files):
    """Back up previous metadata, then remove only known legacy group-write bits."""
    changes={str(p):{'uid':p.stat().st_uid,'gid':p.stat().st_gid,'mode':oct(p.stat().st_mode & 0o777),'sha256':common.digest(p) if p.is_file() else None}
             for p in [base,*files] if p.exists() and p.stat().st_mode & 0o022}
    if not changes:return
    require(base.stat().st_uid==os.getuid() and base.stat().st_gid==os.getgid() and (base.stat().st_mode & 0o777) in (0o700,0o755,0o775),'Unexpected legacy monitoring directory')
    # Preflight has verified all files byte-for-byte before this first mutation.
    backup=base/('legacy-metadata-'+sha(text(changes))+'.json')
    common.atomic(backup,{'owner':OWNER,'before':changes})
    for name in changes:
        path=Path(name);path.chmod(0o700 if path.is_dir() else 0o600)


def layout(target, policy):
    base = Path(policy['runtime']); release = base / ('prometheus-' + VERSION + '.linux-arm64')
    labels = {'host': target['hostname'].split('.')[0], 'model_id':'kolibri-1',
              'revision':'258cae8ffffc8c12db670bdbc6ac01bcf8826c87', 'quantization':'fp8',
              'context_tokens':'262144', 'max_num_seqs':'1'}
    config = {'global':{'scrape_interval':'5s','evaluation_interval':'5s'}, 'scrape_configs':[
        {'job_name':'vllm','static_configs':[{'targets':['127.0.0.1:8000'],'labels':labels}]},
        {'job_name':'benchmark-host','static_configs':[{'targets':['127.0.0.1:9199']}]}]}
    legacy = text(config)
    if policy['include_health']:
        config['scrape_configs'].append({'job_name':'dgx-spark-health','scrape_interval':'30s',
                                       'static_configs':[{'targets':['127.0.0.1:9817']}]})
    suffix = '\nRestart=on-failure\nRestartSec=5\nNoNewPrivileges=yes\nPrivateTmp=yes\nUMask=0077\nNice=10\nMemoryMax=768M\nCPUQuota=100%\n\n[Install]\nWantedBy=default.target\n'
    units = {
        UNITS[0]: '[Unit]\nDescription=AI-Model benchmark Prometheus (loopback only)\n\n[Service]\nExecStart=' + str(release/'prometheus') + ' --config.file=' + str(base/'prometheus.json') + ' --web.listen-address=127.0.0.1:9090 --storage.tsdb.path=' + str(base/'tsdb') + ' --storage.tsdb.retention.time=3d --storage.tsdb.retention.size=512MB' + suffix,
        UNITS[1]: '[Unit]\nDescription=AI-Model benchmark host and run metadata\n\n[Service]\nExecStart=/usr/bin/python3 -B ' + str(base/'metrics.py') + ' --runtime ' + str(base) + suffix}
    unit_root = Path(target['home']) / '.config/systemd/user'
    files = {base/'metrics.py':(HERE/'metrics-exporter.py').read_bytes(),
             **{unit_root/name:body.encode() for name,body in units.items()}}
    return base, release, config, legacy, files


def preflight(target, policy):
    common.validate_target(target)
    require(os.getuid() == target['uid'] != 0 and platform.machine() == 'aarch64', 'Monitoring requires the normal account on ARM64')
    base, release, config, legacy, files = layout(target, policy)
    for path, expected in files.items():
        common.safe(path)
        if path.exists(): known_file(path, (expected,))
    path = base/'prometheus.json'
    if path.exists():
        try:known_file(path,(text(config),legacy))
        except RuntimeError as exc:raise RuntimeError('Preserve divergent monitoring scrape configuration: '+str(exc)) from exc
    registry = base/'monitoring-bootstrap.json'
    if registry.exists():
        for p in [*files,path]:checked_file(p)
        old = json.loads(checked_file(registry))
        require(old.get('owner') == OWNER and old.get('policy') == policy, 'Another monitoring policy owns this runtime')
        for name, pin in old['files'].items(): require(common.digest(common.safe(Path(name))) == pin, 'Monitoring registry drift: ' + name)
    for unit in UNITS:
        require(not run(['systemctl','--user','show',unit,'-p','DropInPaths','--value']).strip(), 'Unexpected monitoring unit drop-in')
        loaded = run(['systemctl','--user','show',unit,'-p','LoadState','--value']).strip()
        require(loaded in ('not-found','') or (Path(target['home'])/'.config/systemd/user'/unit).exists(), 'Foreign loaded monitoring unit')
    return base, release, config, legacy, files


def http(path):
    require(path.startswith('/') and not path.startswith('//'), 'Fixed local Prometheus path required')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:9090' + path, timeout=5) as response:
        require(response.geturl() == 'http://127.0.0.1:9090' + path, 'Unexpected monitoring redirect')
        raw = response.read(8*1024*1024+1)
    require(len(raw) <= 8*1024*1024, 'Oversized monitoring response')
    return raw


def verify(target, policy, timeout=65):
    base, release, config, _, files = preflight(target, policy)
    require((base/'monitoring-bootstrap.json').exists(), 'Monitoring has no bootstrap registration')
    for unit in UNITS:
        run(['systemctl','--user','is-enabled','--quiet',unit]);run(['systemctl','--user','is-active','--quiet',unit])
    run([release/'promtool','check','config',base/'prometheus.json'])
    require(json.loads(checked_file(base/'prometheus.json')) == config, 'Expected scrape configuration is not installed')
    http('/-/ready')
    expected = {'vllm','benchmark-host'} | ({'dgx-spark-health'} if policy['include_health'] else set())
    deadline = time.monotonic()+timeout
    while True:
        reply = json.loads(http('/api/v1/targets?state=active'))
        rows = reply.get('data',{}).get('activeTargets',[])
        require(reply.get('status') == 'success', 'Prometheus target API failed')
        found = {row['labels']['job']:row for row in rows}
        if expected <= found.keys() and all(found[key]['health'] == 'up' and not found[key].get('lastError') for key in expected):break
        require(time.monotonic() < deadline, 'Expected scrape targets are not all healthy')
        time.sleep(2)
    build = json.loads(http('/api/v1/status/buildinfo'))
    require(build['data']['version'] == VERSION, 'Live Prometheus version differs')
    flags = json.loads(http('/api/v1/status/flags'))['data']
    require(flags['config.file'] == str(base/'prometheus.json') and flags['storage.tsdb.path'] == str(base/'tsdb') and flags['web.listen-address'] == '127.0.0.1:9090', 'Live Prometheus identity differs')
    return {'status':'PASS','scope':'monitoring only; no model inference','runtime':str(base),'version':VERSION,
            'targets':{key:{'health':found[key]['health'],'url':found[key]['scrapeUrl']} for key in sorted(expected)},
            'retention':{'time':'3d','size':'512MB'},'registry_sha256':common.digest(base/'monitoring-bootstrap.json')}


def inspect(target, policy):
    try:return verify(target, policy, timeout=0)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:return {'status':'BLOCKED','reason':str(exc),'scope':'read-only monitoring inspection'}


def release_files(base, release):
    archive = base/(release.name+'.tar.gz')
    if not archive.exists():
        partial = base/('download-'+uuid.uuid4().hex+'.part')
        url = 'https://github.com/prometheus/prometheus/releases/download/v'+VERSION+'/'+archive.name
        with urllib.request.urlopen(url,timeout=60) as response, partial.open('xb') as out:
            total=0
            while block:=response.read(1024*1024):
                total+=len(block);require(total<=256*1024*1024,'Oversized Prometheus archive');out.write(block)
        require(common.digest(partial)==ARCHIVE_SHA,'Prometheus archive SHA256 mismatch');partial.replace(archive)
    require(common.digest(archive)==ARCHIVE_SHA,'Retained Prometheus archive SHA256 mismatch')
    payload={}
    with tarfile.open(archive,'r:gz') as stream:
        for name in ('prometheus','promtool'):
            member=stream.getmember(release.name+'/'+name)
            require(member.isfile() and member.size<=512*1024*1024,'Unsafe Prometheus binary member')
            payload[release/name]=stream.extractfile(member).read()
    for path,raw in payload.items():
        if path.exists():require(checked_file(path)==raw,'Retained Prometheus binary drift')
    return payload


def publish(path, raw, mode=0o600):
    if path.exists() and checked_file(path)==raw:return False
    private(path.parent);temporary=path.with_name('.'+path.name+'-'+uuid.uuid4().hex)
    with temporary.open('xb') as out:
        os.fchmod(out.fileno(),mode);out.write(raw);out.flush();os.fsync(out.fileno())
    os.replace(temporary,path);return True


def install(target, supplied=None):
    policy=settings(target,supplied)
    # All existing config/unit identity checks precede any mutation.
    base,release,config,legacy,files=preflight(target,policy)
    if run(['loginctl','show-user',target['user'],'-p','Linger','--value']).strip() != 'yes':
        run(['sudo','-n','loginctl','enable-linger',target['user']])
    if base.exists():
        require(base.is_dir() and base.stat().st_uid==os.getuid() and base.stat().st_gid==os.getgid() and (base.stat().st_mode & 0o777) in (0o700,0o755,0o775), 'Untrusted monitoring runtime')
    else:base.mkdir(parents=True,mode=0o700)
    with (base/'monitoring-bootstrap.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        migrate_legacy_modes(base,[*files,base/'prometheus.json'])
        private(base)
        base,release,config,legacy,files=preflight(target,policy)
        archive_files=release_files(base,release)
        config_path=base/'prometheus.json';old=config_path.read_bytes() if config_path.exists() else None
        wanted=text(config);config_changed=old!=wanted
        if config_changed:
            if old is not None:
                backup=base/'config-backups';private(backup)
                publish(backup/(sha(old)+'.json'),old)
            candidate=base/('.monitoring-'+uuid.uuid4().hex+'.candidate')
            publish(candidate,wanted)
        changed=[]
        for path,raw in archive_files.items():
            if publish(path,raw,0o755):changed.append(str(path))
        if config_changed:run([release/'promtool','check','config',candidate])
        for path,raw in files.items():
            if publish(path,raw):changed.append(str(path))
        if config_changed:
            candidate.replace(config_path);changed.append(str(config_path))
        was_active=subprocess.run(['systemctl','--user','is-active','--quiet',UNITS[0]]).returncode==0
        try:
            if any('/.config/systemd/user/' in x for x in changed):run(['systemctl','--user','daemon-reload'])
            for unit in UNITS:run(['systemctl','--user','enable','--now',unit])
            require(run(['loginctl','show-user',target['user'],'-p','Linger','--value']).strip()=='yes','Persistent user manager needs configured lingering; do not alter it implicitly')
            if config_changed and was_active:run(['systemctl','--user','kill','--kill-who=main','--signal=HUP',UNITS[0]])
            all_files={**files,**archive_files,config_path:wanted}
            registry={'owner':OWNER,'policy':policy,'files':{str(path):common.digest(path) for path in all_files}}
            common.atomic(base/'monitoring-bootstrap.json',registry)
            result=verify(target,policy)
        except BaseException:
            # Only an existing known config is eligible for automatic rollback.
            # Newly created failed installs remain retained for operator review.
            if old is not None and config_changed:
                publish(config_path,old)
                with contextlib.suppress(Exception):run(['systemctl','--user','kill','--kill-who=main','--signal=HUP',UNITS[0]])
                registry_path=base/'monitoring-bootstrap.json'
                if registry_path.exists():
                    prior=json.loads(registry_path.read_text());prior['files'][str(config_path)]=sha(old)
                    common.atomic(registry_path,prior)
            raise
        result.update(status='UPDATED' if changed else 'UNCHANGED',files_changed=changed)
        return result


def disable(target, supplied=None):
    policy=settings(target,supplied);base,_,_,_,_=preflight(target,policy)
    require((base/'monitoring-bootstrap.json').exists(),'Refuse disabling unregistered monitoring')
    for unit in UNITS:run(['systemctl','--user','disable','--now',unit])
    return {'status':'DISABLED','data_preserved':True,'runtime':str(base)}
