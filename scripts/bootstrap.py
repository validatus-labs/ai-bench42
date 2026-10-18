#!/usr/bin/env python3
"""Select portable DGX Spark bootstrap components; preview is the default.

scripts/bootstrap.py
|-- --plan                   resolve the current OS account and preview
|-- --on                     converge selected components; one sudo boundary
|-- --off                    disable selected owned services/tools, preserve data
|-- --brave --playwright     browser and managed MCP installation
|-- --maintenance --health  scheduled maintenance and observational health
`-- --vllm --kolibri         engine environment / FP8 checkpoint service

Use --calibration on|off with --kolibri. Run long installation in screen.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/deploy'))
import bootstrap_components as components

OWNER = 'ModelBench/portable-bootstrap/v1'
FLAGS = ('brave', 'playwright', 'maintenance', 'health', 'vllm', 'kolibri')


def parser():
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for flag in FLAGS:
        result.add_argument('--' + flag, dest=flag, action='store_true')
    action = result.add_mutually_exclusive_group()
    action.add_argument('--on', action='store_true', help='install/enable selected components')
    action.add_argument('--off', action='store_true', help='disable owned components without uninstalling')
    action.add_argument('--plan', action='store_true', help='preview only (default)')
    action.add_argument('--inspect', action='store_true', help='inspect existing host/components without installing or generating tokens')
    action.add_argument('--verify', action='store_true', help='verify installed state and run real model/browser canaries')
    result.add_argument('--output', type=Path, help='private directory for inspection/verification evidence')
    result.add_argument('--calibration', choices=['on', 'off'], default='off',
                        help='Kolibri KV calibration; FP8 checkpoint weights are always retained')
    result.add_argument('--runtime-root', type=Path)
    retention = result.add_mutually_exclusive_group()
    retention.add_argument('--retention', choices=['forever', 'never', '7', '30', '90', '180', '365'],
                           help='local health history days; fresh default 30; requires --health')
    retention.add_argument('--never', dest='retention', action='store_const', const='forever',
                           help='alias for --retention forever: never delete health history')
    updates = result.add_mutually_exclusive_group()
    updates.add_argument('--check-updates', action='store_true', help='resolve newer browser-toolchain versions without installing')
    updates.add_argument('--update', action='store_true', help='prepare, qualify and promote a new browser toolchain')
    result.add_argument('--_root-job', type=Path, help=argparse.SUPPRESS)
    result.add_argument('--_user-job', type=Path, help=argparse.SUPPRESS)
    return result


def sources():
    roots = [ROOT / 'scripts', ROOT / 'config/bootstrap']
    return {str(path.relative_to(ROOT)): components.digest(path)
            for base in roots for path in sorted(base.rglob('*'))
            if path.is_file() and (base == ROOT / 'config/bootstrap' or path.suffix in {'.py', '.sh', '.cjs', '.json', '.sources', '.preferences', '.cfg', '.service', '.timer'})
            and '__pycache__' not in path.parts} | {
                'config/bootstrap/99ai-model-updates': components.digest(ROOT / 'config/bootstrap/99ai-model-updates'),
                'config/toolchain-updates.json': components.digest(ROOT / 'config/toolchain-updates.json')}


def plan(args):
    selected = [name for name in FLAGS if getattr(args, name)]
    if not selected:
        raise ValueError('Choose at least one component, for example --brave --playwright --health')
    if args.calibration == 'on' and not args.kolibri:
        raise ValueError('--calibration on requires --kolibri')
    retention = 'forever' if args.retention == 'never' else args.retention
    if retention is not None and (not args.health or args.off):
        raise ValueError('--retention/--never requires --health with --on or --plan')
    target = components.account(ROOT, args.runtime_root)
    inputs = sources()
    mode = 'off' if args.off else 'on'
    fingerprint = hashlib.sha256(json.dumps({'target': target, 'components': selected, 'mode': mode,
                                           'calibration': args.calibration, 'health_retention': retention,
                                           'sources': inputs}, sort_keys=True).encode()).hexdigest()
    return {'owner': OWNER, 'target': target, 'components': selected, 'action': mode,
            'calibration': args.calibration, 'sources': inputs, 'fingerprint': fingerprint,
            'health_retention': retention,
            'health_retention_policy': 'explicit override' if retention is not None else 'preserve installed setting; fresh installation uses 30 days',
            'model_weights': 'pinned FP8 checkpoint; no BF16-to-FP8 requantization',
            'sudo': 'one root supervisor; all model/browser installers run as the selected OS account',
            'scope': 'host setup, not a ModelBench C00 worker-isolation qualification'}


def check_sources(job):
    if sources() != job['sources']:
        raise ValueError('Bootstrap source files changed since selection')
    for name, checksum in job['sources'].items():
        path = components.safe(ROOT / name)
        if components.digest(path) != checksum:
            raise ValueError('Source changed since bootstrap selection: ' + name)


def host_check():
    release = platform.freedesktop_os_release()
    if release.get('ID') != 'ubuntu' or release.get('VERSION_ID') != '24.04' or platform.machine() != 'aarch64':
        raise ValueError('Installation requires the Ubuntu 24.04 ARM64 NVIDIA DGX Spark OEM host')
    if Path('/proc/1/comm').read_text().strip() != 'systemd':
        raise ValueError('A native systemd host is required')
    gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], text=True)
    if 'GB10' not in gpu:
        raise ValueError('NVIDIA GB10 was not detected; existing drivers are not changed')


def configure_native_source(target):
    root = components.safe(Path(target['runtime']) / 'tools/bootstrap/native-source')
    files = {p.relative_to(ROOT / 'config/bootstrap'): p for p in (ROOT / 'config/bootstrap').rglob('*') if p.is_file()}
    mapping = {root / 'config' / name: source for name, source in files.items()}
    mapping[root / 'scripts/deploy/spark-apt-maintenance.sh'] = ROOT / 'scripts/deploy/spark-apt-maintenance.sh'
    for destination, source in mapping.items():
        components.safe(destination)
        data = source.read_bytes()
        if source.suffix == '.service':
            data = data.replace(b'@HOSTNAME@', target['hostname'].split('.')[0].encode())
        if destination.exists():
            if destination.read_bytes() != data:
                raise ValueError('Existing native input differs: ' + str(destination))
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as out:
                os.fchmod(out.fileno(), 0o644)
                out.write(data)
    return root


def owned_service(name, marker, action):
    path = Path('/etc/systemd/system') / name
    components.safe(path)
    if not path.exists():
        return
    if marker not in path.read_text():
        raise ValueError('Unowned service preserved: ' + name)
    dropins = subprocess.check_output(['systemctl', 'show', name, '-p', 'DropInPaths', '--value'], text=True).strip()
    if dropins:
        raise ValueError('Unexpected service drop-ins: ' + name)
    command = ['systemctl', action] + ([] if action == 'stop' else ['--now']) + [name]
    subprocess.run(command, check=True)


def root_components(job):
    target = job['target']
    selected = set(job['components'])
    if job['action'] == 'off':
        if 'maintenance' in selected:
            for name in ['ai-model-security-updates.timer', 'ai-model-weekly-updates.timer']:
                owned_service(name, 'Managed by ModelBench bootstrap maintenance v1', 'disable')
            for name in ['modelbench-toolchain-update.path', 'modelbench-toolchain-update.timer']:
                owned_service(name, 'Managed by ModelBench toolchain updates v1', 'disable')
            owned_service('modelbench-toolchain-update.service', 'Managed by ModelBench toolchain updates v1', 'stop')
        if 'health' in selected:
            for name in ['dgx-spark-health.timer', 'dgx-spark-health-exporter.service']:
                owned_service(name, 'managed-by: dgx-spark-health-bootstrap', 'disable')
            owned_service('dgx-spark-health.service', 'managed-by: dgx-spark-health-bootstrap', 'stop')
        return
    if selected & {'maintenance', 'brave', 'playwright', 'vllm', 'kolibri'}:
        source = configure_native_source(target)
        host = components.load_script('bootstrap-host.py')
        host.ROOT, host.DEPLOY_USER = source, target['user']
        if 'maintenance' not in selected:
            # Install prerequisites only; selecting another tool does not opt into timers/linger.
            host.targets = lambda: []
            host.INSTALL_MAINTENANCE = False
        host.PACKAGES += ['build-essential', 'python3-dev', 'ninja-build'] if selected & {'vllm', 'kolibri'} else []
        host.install()
        if 'maintenance' in selected:
            components.load_script('toolchain_native.py').install(target, ROOT)
    if 'brave' in selected:
        binary = Path('/opt/brave.com/brave/brave')
        if binary.is_file():
            print(json.dumps({'component': 'brave', 'status': 'REUSED_EXISTING_NO_UPGRADE'}), flush=True)
        else:
            subprocess.run(['/usr/bin/python3', '-B', str(ROOT / 'scripts/deploy/install-spark-brave.py'),
                            '--install', '--project-root', str(source), '--hostname', target['hostname']], check=True)
    if 'health' in selected:
        install_health(target, job.get('health_retention'))


def install_health(target, retention=None):
    module = health_module(ROOT / 'scripts/deploy/dgx-spark-health-bootstrap.sh')
    module.TARGET_HOST = target['hostname']
    module.TARGET_RUNTIME = target['runtime']
    previous = os.environ.get('DGX_MODEL_PYTHON')
    previous_retention = os.environ.pop('DGX_RETENTION_DAYS', None)
    try:
        if retention is not None:
            os.environ['DGX_RETENTION_DAYS'] = str(module.retention_value(retention))
        facts = module.live_unit()
        pid = facts.get('MainPID', '0')
        if pid.isdigit() and pid != '0':
            interpreter = os.fsdecode((Path('/proc') / pid / 'cmdline').read_bytes().split(b'\0')[0])
            prefix = str(Path(target['runtime']) / 'build/dgx-spark-vllm/releases') + '/'
            if not interpreter.startswith(prefix):
                raise ValueError('Health target model is outside the selected runtime')
            os.environ['DGX_MODEL_PYTHON'] = interpreter
        else:
            os.environ['DGX_MODEL_PYTHON'] = ''
        module.install()
    finally:
        if previous is None:
            os.environ.pop('DGX_MODEL_PYTHON', None)
        else:
            os.environ['DGX_MODEL_PYTHON'] = previous
        if previous_retention is None:
            os.environ.pop('DGX_RETENTION_DAYS', None)
        else:
            os.environ['DGX_RETENTION_DAYS'] = previous_retention


def health_module(path):
    import types
    module = types.ModuleType('portable_health')
    source = path.read_text().split("<<'PYTHON'\n", 1)[1].rsplit('\nPYTHON', 1)[0]
    with contextlib.redirect_stdout(sys.stdout):
        original = sys.argv
        try:
            sys.argv = ['python', str(path)]
            exec(compile(source, str(path), 'exec'), module.__dict__)
        finally:
            sys.argv = original
    return module


def service_command(job, argv, timeout):
    """Only the exact owned model unit can cross the inherited privilege channel."""
    unit = 'ai-model-vllm-kolibri-1.service'
    destination = Path('/etc/systemd/system') / unit
    target = job['target']
    sys.path.insert(0, str(ROOT / 'scripts/deploy/dgx-spark-vllm'))
    components.safe(destination)
    if argv == ['systemctl', 'daemon-reload']:
        return subprocess.check_output(argv, stderr=subprocess.STDOUT, timeout=timeout, text=True)
    if len(argv) == 3 and argv[0] == 'systemctl' and argv[1] in {'start', 'stop', 'restart', 'reset-failed', 'disable', 'enable'} and argv[2] == unit:
        if not destination.exists():
            raise ValueError('Owned model unit is absent')
        if destination.exists():
            contents = destination.read_text()
            if '# Managed by AI-Model/dgx-spark-vllm/v1' not in contents or '\nUser=' + target['user'] + '\n' not in contents:
                raise ValueError('Existing model service is not owned by this account')
        return subprocess.check_output(argv, stderr=subprocess.STDOUT, timeout=timeout, text=True)
    if len(argv) == 9 and argv[:7] == ['install', '-o', 'root', '-g', 'root', '-m', '0644'] and argv[-1] == str(destination):
        if destination.exists() and ('# Managed by AI-Model/dgx-spark-vllm/v1' not in destination.read_text() or '\nUser=' + target['user'] + '\n' not in destination.read_text()):
            raise ValueError('Unowned existing model unit preserved')
        source = components.safe(Path(argv[-2]))
        release = source.parent
        if source.name != 'server.service' or release.parent != Path(target['runtime']) / 'build/dgx-spark-vllm/releases':
            raise ValueError('Unit source outside the selected runtime')
        from modules.common import Context
        from modules.profiles import load
        from modules.lifecycle import unit_text
        profile = load(release / 'source', 'kolibri-1')
        if (profile['defaults']['user'] != target['user'] or profile['defaults']['runtime_root'] != target['runtime']
                or profile['defaults']['hostname'] != target['hostname']):
            raise ValueError('Unit profile differs from the selected account/runtime')
        expected = unit_text(Context(release / 'source', profile), release)
        if source.read_text() != expected:
            raise ValueError('Unit contents differ from the trusted user-service template')
        return subprocess.check_output(argv, stderr=subprocess.STDOUT, timeout=timeout, text=True)
    if argv == ['rm', '--', str(destination)]:
        if not destination.exists():
            return ''
        data = destination.read_text()
        if '# Managed by AI-Model/dgx-spark-vllm/v1' not in data or '\nUser=' + target['user'] + '\n' not in data:
            raise ValueError('Unowned model service preserved')
        destination.unlink()
        return ''
    raise ValueError('Privileged command refused')


def user_components(job):
    target = components.validate_target(job['target'])
    if os.geteuid() != target['uid']:
        raise ValueError('User phase is running under the wrong account')
    selected = set(job['components'])
    if job['action'] == 'off':
        if selected & {'kolibri', 'vllm'}:
            components.model(target, job['calibration'], False)
        if 'playwright' in selected:
            config = Path(target['runtime']) / 'tools/bootstrap/kilo.json'
            if config.exists():
                data = json.loads(config.read_text())
                data['mcp']['playwright']['enabled'] = False
                components.atomic(config, data)
        return
    if 'vllm' in selected and 'kolibri' not in selected:
        components.engine(target)
    if 'kolibri' in selected:
        components.model(target, job['calibration'])
        from modules.common import run
        run(['sudo', '-n', 'systemctl', 'enable', 'ai-model-vllm-kolibri-1.service'])
    if 'playwright' in selected:
        components.playwright(target)


def run_user(job, job_path):
    target = job['target']
    parent, child = socket.socketpair()
    env = components.environment(target)
    env['MODEL_BENCH_PRIVILEGE_FD'] = str(child.fileno())
    process = subprocess.Popen(['/usr/bin/python3', '-B', str(Path(__file__).resolve()), '--_user-job', str(job_path)],
                               user=target['uid'], group=target['gid'],
                               extra_groups=os.getgrouplist(target['user'], target['gid']),
                               env=env, pass_fds=(child.fileno(),), cwd=target['project'])
    child.close()
    with parent, parent.makefile('rwb') as stream:
        while line := stream.readline(65537):
            try:
                if len(line) > 65536 or not line.endswith(b'\n'):
                    raise ValueError('Oversized privilege request')
                request = json.loads(line)
                timeout = request['timeout']
                if type(timeout) not in (int, float) or not 0 < timeout <= 180:
                    raise ValueError('Invalid privilege operation timeout')
                output = service_command(job, request['argv'], timeout)
                reply = {'returncode': 0, 'output': output[-16000:]}
            except Exception as exc:
                reply = {'returncode': 1, 'output': type(exc).__name__ + ': ' + str(exc)[-1500:]}
            stream.write((json.dumps(reply) + '\n').encode())
            stream.flush()
    if process.wait():
        raise RuntimeError('User component phase failed; retained state was not discarded')


def root_job(path):
    if os.geteuid() != 0:
        raise ValueError('Internal root phase requires sudo')
    job = json.loads(path.read_text())
    if job.get('owner') != OWNER or set(job['components']) - set(FLAGS) or job['action'] not in {'on', 'off'} or job['calibration'] not in {'on', 'off'}:
        raise ValueError('Invalid bootstrap job')
    retention = job.get('health_retention')
    if retention is not None and (retention not in ('forever','7','30','90','180','365') or 'health' not in job['components'] or job['action'] != 'on'):
        raise ValueError('Invalid health retention in bootstrap job')
    target = components.validate_target(job['target'])
    if path.stat().st_uid != target['uid'] or path.stat().st_mode & 0o077:
        raise ValueError('Bootstrap job must be private and owned by the selected account')
    check_sources(job)
    host_check()
    lock_path = Path('/run/lock/modelbench-bootstrap.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        owner = Path('/var/lib/modelbench-bootstrap/owner.json')
        if owner.exists():
            if json.loads(owner.read_text()) != {'owner': OWNER, 'target': target}:
                raise ValueError('Another bootstrap account/runtime owns the host; existing services preserved')
        elif job['action'] == 'off':
            receipt = path.with_name('receipt.json')
            components.atomic(receipt, {'owner': OWNER, 'status': 'UNCHANGED_NOT_INSTALLED', 'action': 'off'})
            os.chown(receipt, target['uid'], target['gid'])
            return
        else:
            components.atomic(owner, {'owner': OWNER, 'target': target})
        receipt = path.with_name('receipt.json')
        result = {'owner': OWNER, 'fingerprint': job['fingerprint'], 'status': 'RUNNING',
                  'components': job['components'], 'action': job['action'], 'target': target, 'calibration': job['calibration'],
                  'scope': job['scope'], 'health_retention': retention}
        try:
            root_components(job)
            check_sources(job)
            if set(job['components']) & {'playwright', 'vllm', 'kolibri'}:
                run_user(job, path)
            if job['action'] == 'on' and {'health', 'kolibri'} <= set(job['components']):
                install_health(target, retention)
            result['status'] = 'COMPLETED'
        except BaseException as exc:
            result.update(status='FAILED', error=type(exc).__name__ + ': ' + str(exc))
            raise
        finally:
            components.atomic(receipt, result)
            os.chown(receipt, target['uid'], target['gid'])
            print(json.dumps(result), flush=True)


def submit(job, observer=None):
    # No timestamp refresh loop and no sudoers changes: sudo starts one root supervisor.
    host_check()
    target = job['target']
    base = components.safe(Path(target['runtime']) / 'tools/bootstrap/jobs')
    base.mkdir(parents=True, exist_ok=True)
    folder = base / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + uuid.uuid4().hex[:8])
    folder.mkdir(mode=0o700)
    path = folder / 'job.json'
    components.atomic(path, job)
    log = folder / 'worker.log'
    log.touch(mode=0o600)
    unit = 'modelbench-bootstrap-' + folder.name
    command = ['sudo', 'systemd-run', '--wait', '--collect', '--unit=' + unit,
               '--property=Type=exec', '--property=RuntimeMaxSec=21600', '--property=TimeoutStopSec=180',
               '--property=UMask=0077', '--property=StandardOutput=append:' + str(log), '--property=StandardError=inherit',
               '/usr/bin/python3', '-B', str(Path(__file__).resolve()), '--_root-job', str(path)]
    if not sys.stdin.isatty():
        command.insert(1, '-n')
    details = {'unit': unit, 'receipt': str(folder / 'receipt.json'), 'log': str(log), 'request': str(path)}
    print(json.dumps(details), flush=True)
    if observer is not None:
        observer(dict(details, argv=command))
    return subprocess.run(command).returncode


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args._root_job:
            root_job(args._root_job)
            return 0
        if args._user_job:
            user_components(json.loads(args._user_job.read_text()))
            return 0
        if args.check_updates or args.update:
            if args.on or args.off or args.plan or args.inspect or args.verify or args.output or any(getattr(args, flag) for flag in FLAGS) or args.calibration != 'off' or args.retention is not None:
                raise ValueError('Use --check-updates/--update separately from component installation flags')
            command = ['/usr/bin/python3', '-B', str(ROOT / 'scripts/toolchain.py')]
            if args.runtime_root: command += ['--runtime-root', str(args.runtime_root)]
            command += ['check' if args.check_updates else 'update']
            return subprocess.run(command, check=False).returncode
        if args.inspect or args.verify:
            if args.retention is not None or args.calibration != 'off':
                raise ValueError('Inspection/verification uses installed settings; do not select retention/calibration changes')
            selected = [flag for flag in FLAGS if getattr(args, flag)] or list(FLAGS)
            import verify_installation
            return verify_installation.cli(args, selected)
        if args.output:
            raise ValueError('--output requires --inspect or --verify')
        job = plan(args)
        if not (args.on or args.off):
            print(json.dumps(dict(job, status='PLAN_ONLY'), indent=2))
            return 0
        return submit(job)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': type(exc).__name__ + ': ' + str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
