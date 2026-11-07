#!/usr/bin/env python3
"""One native Spark stack entrypoint; compose existing protected installers.

bootstrap-spark.py
|-- [J01] plan()          validated JSON, fixed installers and exact source hashes
|-- [J02] inspect()       native host + CUDA + qualified V5 asset prerequisites
|-- [J03] submit()        bounded durable systemd job; private logs/Run-ID
|-- [J04] apply()         lock -> preflight -> native/Brave/MCP/model/health/metrics
|-- [J05] verify()        actual units, model/context, three healthy scrape targets
`-- [J06] main()          plan | inspect | install | verify

VS Code: Ctrl+Shift+O for functions; Ctrl+F [J01]...[J06].
Native Spark, as validatus: python3 -B scripts/deploy/bootstrap-spark.py install
Source-only local preview: python3 -B scripts/deploy/bootstrap-spark.py plan
Explicit infrastructure-only: install --without-model (never claims model readiness).
No SSH, driver/security modification, new calibration, secrets or C01–C07.
"""
import argparse
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import pwd
import subprocess
import sys
import time
import uuid
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
SPARK=Path('/home/validatus/workspace/AI-Model')
RUNTIME=SPARK/'runtime/spark-a922'
OWNER='AI-Model/spark-bootstrap/v1'


def encoded(value):return (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def module(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),ROOT/'scripts/deploy'/name)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result
def save(path,value):
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('xb') as out:os.fchmod(out.fileno(),0o600);out.write(encoded(value))
    os.replace(temp,path)
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()


def plan(without_model=False):
    profile=json.loads((ROOT/'config/spark-bootstrap.json').read_text())
    expected={'version':1,'hostname':'spark-a922','user':'validatus','project':str(SPARK),
        'model':'kolibri-1','calibration':'qualified-v5-reuse','context_tokens':262144,
        'runtime_seconds':21600,'stage_seconds':14400,'include_health_scrape':True,'install_benchmark_clients':False}
    if encoded(profile)!=encoded(expected):raise ValueError('Unsupported bootstrap JSON; review contract before changing')
    py='/usr/bin/python3';base=ROOT/'scripts/deploy'
    stages=[('host',['sudo','-n',py,'-B',str(base/'bootstrap-host.py'),'install']),
        ('brave',['sudo','-n',py,'-B',str(base/'install-spark-brave.py'),'--install']),
        ('mcp-dependencies',[py,'-B',str(base/'bootstrap-playwright-deps.py'),'install']),
        ('mcp-launcher',[py,'-B',str(base/'install-playwright-mcp.py'),'install'])]
    if not without_model:stages.append(('kolibri-calibrated',[py,'-B',str(base/'kolibri.py'),'deploy']))
    stages.extend([('health',['sudo','-n','/bin/bash',str(base/'dgx-spark-health-bootstrap.sh'),'install']),
        ('metrics',[py,'-B',str(ROOT/'scripts/benchmark/setup-metrics.py'),'--runtime',str(RUNTIME/'tools/benchmark'),
                    '--metrics-only','--include-health'])])
    inputs=[p for folder in [ROOT/'config',base,ROOT/'scripts/benchmark'] for p in folder.rglob('*')
            if p.is_file() and p.suffix in {'.py','.sh','.json','.txt','.service','.timer','.sources','.preferences','.cfg'}
            and '__pycache__' not in p.parts]
    inputs+=[ROOT/'config/99ai-model-updates']
    return {'owner':OWNER,'profile':profile,'without_model':without_model,'stages':[[name,argv] for name,argv in stages],
        'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(set(inputs))},
        'scope':'SOURCE_PLAN_ONLY; this does not assert a fresh host or installed stack is qualified',
        'greenfield_inputs':['NVIDIA OEM Ubuntu24.04 ARM64 image + driver/CUDA, validatus UID1001 at fixed project path',
           'Approved signed native Node22+ APT source and existing Ubuntu Brave AppArmor attachment',
           'For model mode: exact V5 manifest/overlay + original weights + matching original baseline venv/lock; never fabricated']}


def identity():
    if (ROOT!=SPARK or platform.node()!='spark-a922' or platform.machine()!='aarch64'
        or os.geteuid()!=1001 or pwd.getpwuid(os.geteuid()).pw_name!='validatus'
        or os.environ.get('HOME')!='/home/validatus' or sys.version_info<(3,12)):
        raise RuntimeError('Run natively as validatus UID1001 on Spark, Python3.12+, mirrored project path')


def inspect(spec):
    native=subprocess.run(['sudo','-n','/usr/bin/python3','-B',str(ROOT/'scripts/deploy/bootstrap-host.py'),'inspect'],
        capture_output=True,text=True,timeout=60)
    if native.returncode:
        return {'status':'BLOCKED','blockers':['Read-only native prerequisite inspection failed; check root-file access/host contract'],
                'native_inspection_exit':native.returncode}
    facts={'host':json.loads(native.stdout),'blockers':[],'model_requested':not spec['without_model']}
    facts['blockers']+=facts['host']['incompatible']
    for path in [Path('/usr/local/cuda'),Path('/etc/apparmor.d/brave')]:
        if not path.exists():facts['blockers'].append('Required OEM prerequisite missing: '+str(path))
    apparmor=subprocess.run(['sudo','-n','/usr/bin/cat','/sys/kernel/security/apparmor/profiles'],
        capture_output=True,text=True,timeout=10)
    if apparmor.returncode or 'brave (unconfined)' not in apparmor.stdout.splitlines():
        facts['blockers'].append('Existing loaded Ubuntu Brave attachment not verified; no policy will be created')
    facts['existing_brave_attachment_verified']=apparmor.returncode==0 and 'brave (unconfined)' in apparmor.stdout.splitlines()
    try:
        gpu=subprocess.run(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],capture_output=True,text=True,timeout=20)
        facts['gpu']=gpu.stdout.strip()
        if gpu.returncode or 'GB10' not in gpu.stdout:facts['blockers'].append('Native GB10 driver not verified')
    except OSError:facts['blockers'].append('nvidia-smi unavailable; provision NVIDIA OEM driver first')
    user_manager=subprocess.run(['systemctl','--user','show-environment'],capture_output=True,timeout=10)
    if user_manager.returncode:facts['blockers'].append('Existing user systemd manager unavailable')
    if not spec['without_model']:
        try:
            kolibri=module('kolibri.py');ctx,_,_=kolibri.load_plan(ROOT)
            facts['calibration']=kolibri.calibration_artifact(ctx,ROOT)
            original=Path(ctx.model['kv_calibration']['source_release'])
            requirements=original/'requirements.lock'
            if not (original/'venv/bin/python').exists() or sha(requirements)!=ctx.model['kv_calibration']['requirements_sha256']:
                raise RuntimeError('Original qualified environment/lock missing or different')
        except (OSError,ValueError,RuntimeError) as exc:
            facts['blockers'].append('Qualified V5 input unavailable: '+str(exc))
    facts['status']='BLOCKED' if facts['blockers'] else 'PREREQUISITES_ACCEPTED_NOT_INSTALLED'
    return facts


def submit(spec,action):
    identity();facts=inspect(spec)
    if facts.get('blockers'):return {'status':'BLOCKED','inspection':facts}
    base=RUNTIME/'build/spark-bootstrap';module('install-playwright-mcp.py').safe_path(base)
    base.mkdir(parents=True,exist_ok=True,mode=0o700)
    folder=base/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(mode=0o700)
    unit='ai-model-spark-bootstrap-'+folder.name+'.service'
    save(folder/'job.json',dict(spec,action=action,unit=unit,inspection=facts))
    driver=folder/'bootstrap-spark.py';driver.write_bytes(Path(__file__).read_bytes());driver.chmod(0o600)
    argv=['sudo','-n','systemd-run','--unit='+unit,'--uid=validatus','--gid=validatus',
        '--working-directory='+str(ROOT),'--property=RuntimeMaxSec='+str(spec['profile']['runtime_seconds']),
        '--property=UMask=0077','--property=MemoryMax=12G','--property=TasksMax=1024',
        '--property=TimeoutStopSec=60','--setenv=HOME=/home/validatus',
        '--setenv=XDG_RUNTIME_DIR=/run/user/1001','--setenv=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1001/bus',
        '--setenv=PYTHONDONTWRITEBYTECODE=1','--property=StandardOutput=append:'+str(folder/'worker.log'),
        '--property=StandardError=inherit','/usr/bin/python3','-B',str(driver),'--_job',str(folder)]
    subprocess.run(argv,check=True,timeout=30)
    return {'status':'SUBMITTED','unit':unit,'runtime':str(folder),'receipt':str(folder/'receipt.json')}


def fetch(url):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url,timeout=5) as response:return response.status,response.read(2*1024*1024)


def verify(without_model=False):
    units={'system':['dgx-spark-health.timer','dgx-spark-health-exporter.service','ai-model-security-updates.timer','ai-model-weekly-updates.timer'],
           'user':['ai-model-benchmark-prometheus.service','ai-model-benchmark-metrics.service']}
    if not without_model:units['system'].append('ai-model-vllm-kolibri-1.service')
    observations={}
    for kind,names in units.items():
        for name in names:
            command=['systemctl']+(['--user'] if kind=='user' else [])
            r=subprocess.run(command+['is-active','--quiet',name],capture_output=True,timeout=10)
            observations[name]={'active':r.returncode==0}
            if r.returncode:raise RuntimeError('Inactive required service: '+name)
    if not without_model:
        status,data=fetch('http://127.0.0.1:8000/v1/models');models=json.loads(data)['data']
        if status!=200 or len(models)!=1 or models[0]['id']!='kolibri-1' or models[0]['max_model_len']!=262144:
            raise RuntimeError('Model/context identity mismatch')
        if fetch('http://127.0.0.1:8000/health')[0]!=200:raise RuntimeError('Model unhealthy')
    required={'benchmark-host','dgx-spark-health'}|({'vllm'} if not without_model else set())
    for attempt in range(45):
        status,data=fetch('http://127.0.0.1:9090/api/v1/targets');targets=json.loads(data)['data']['activeTargets']
        healthy={t['labels'].get('job') for t in targets if t['health']=='up'}
        if required<=healthy:break
        time.sleep(1)
    else:raise RuntimeError('Required Prometheus targets not healthy: '+','.join(sorted(required-healthy)))
    if fetch('http://127.0.0.1:9817/healthz')[0]!=200:raise RuntimeError('Health snapshot not fresh')
    return {'status':'INFRASTRUCTURE_READY_MODEL_NOT_DEPLOYED' if without_model else 'STACK_ENDPOINTS_VERIFIED',
            'units':observations,'prometheus_targets':sorted(healthy),'no_generation_request':True,
            'scope':'Endpoint checks do not grant ModelBench readiness, full context quality or a new calibration qualification'}


def apply(folder):
    # A private copied driver receives the original root through its sealed job.
    global ROOT
    job=json.loads((folder/'job.json').read_text());ROOT=SPARK;identity()
    if type(job.get('without_model')) is not bool:raise RuntimeError('Invalid job model selection')
    expected=plan(job['without_model'])
    if any(job.get(k)!=v for k,v in expected.items()):raise RuntimeError('Sealed bootstrap inputs changed')
    if job['action'] not in {'install','verify'}:raise RuntimeError('Invalid bootstrap job action')
    report={'owner':OWNER,'started':now(),'status':'RUNNING','steps':[],'job':str(folder/'job.json')}
    base=RUNTIME/'build/spark-bootstrap'
    with (base/'bootstrap.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        save(folder/'receipt.json',report)
        try:
            facts=inspect(job)
            if facts['blockers']:raise RuntimeError(json.dumps(facts))
            if job['action']=='install':
                for name,argv in job['stages']:
                    if any(sha(ROOT/rel)!=digest for rel,digest in job['source_sha256'].items()):
                        raise RuntimeError('Bootstrap inputs changed; stop before next component')
                    if name=='brave' and Path('/opt/brave.com/brave/brave').is_file():
                        report['steps'].append({'name':name,'status':'REUSED_EXISTING_NO_APT'});save(folder/'receipt.json',report);continue
                    row={'name':name,'started':now(),'status':'RUNNING'};report['steps'].append(row);save(folder/'receipt.json',report)
                    with (folder/(name+'.log')).open('xb') as log:
                        subprocess.run(argv,check=True,timeout=job['profile']['stage_seconds'],stdout=log,stderr=subprocess.STDOUT)
                    row.update(status='COMPLETED',finished=now());save(folder/'receipt.json',report)
            report['verification']=verify(job['without_model'])
            browser=module('install-playwright-mcp.py');profile=browser.load_profile()
            before=set((Path(profile['runtime'])/'runs').glob('verify-*'))
            with (folder/'browser-verify.log').open('xb') as log:
                subprocess.run(['/usr/bin/python3','-B',str(ROOT/'scripts/deploy/install-playwright-mcp.py'),'verify'],
                    check=True,timeout=600,stdout=log,stderr=subprocess.STDOUT)
            fresh=set((Path(profile['runtime'])/'runs').glob('verify-*'))-before
            if len(fresh)!=1:raise RuntimeError('Ambiguous browser verification run')
            receipt=next(iter(fresh))/'receipt.json'
            if json.loads(receipt.read_text())['status']!='VERIFIED':raise RuntimeError('Browser verification failed')
            report['browser']={'receipt':str(receipt),'sha256':sha(receipt)}
            report['status']='COMPLETED_INFRASTRUCTURE_ONLY' if job['without_model'] else 'COMPLETED'
        except BaseException as exc:
            report.update(status='FAILED',error=type(exc).__name__+': '+str(exc));raise
        finally:report['finished']=now();save(folder/'receipt.json',report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',nargs='?',choices=['plan','inspect','install','verify'],default='plan')
    parser.add_argument('--without-model',action='store_true')
    parser.add_argument('--_job',type=Path,help=argparse.SUPPRESS);args=parser.parse_args()
    if args._job:apply(args._job);return
    spec=plan(args.without_model)
    if args.action=='plan':result=spec
    else:
        identity()
        result=inspect(spec) if args.action=='inspect' else submit(spec,args.action)
    print(json.dumps(result,indent=2));return 1 if result.get('status')=='BLOCKED' else 0


if __name__=='__main__':sys.exit(main())
