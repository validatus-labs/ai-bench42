#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Kolibri deployment -- one model, one public entrypoint (Spark Python 3.12).
#
# kolibri.py
# |-- [J01] load_plan()               JSON policy/profile + pinned calibration
# |-- [J02] calibration_artifact()    sealed V5 K/V; BF16 Q/probability stay 1
# |-- [J03] status()                  read-only service/plan inspection
# |-- [J04] submit()                  durable systemd job + retained driver/logs
# |-- [J05] benchmark_guard()         exclude benchmarks and busy model requests
# |-- [J06] run_step()                bounded children, logs, signal cleanup
# |-- [J07] acceptance_id()           reuse completed checks without inference
# |-- [J08] rollback_candidate()      preserve journal; restore previous release
# |-- [J09] run_worker()              deploy -> calibrated capacity/tool acceptance
# `-- [J10] main()                    CLI and structured error reporting
#
# VS Code jump points:
#   Ctrl+Shift+O -> function name (for example run_worker)
#   Ctrl+F       -> [J01] ... [J10]; #region / #endregion provide folding.
#
# Use on Spark, as validatus, from /home/validatus/workspace/AI-Model:
#   python3 -B scripts/deploy/kolibri.py                 # deploy + acceptance
#   python3 -B scripts/deploy/kolibri.py plan            # read-only, also local
#   python3 -B scripts/deploy/kolibri.py status
#   python3 -B scripts/deploy/kolibri.py verify
#   python3 -B scripts/deploy/kolibri.py start|stop|restart
#
# Calibration is INCLUDED through the validated, SHA-pinned V5 checkpoint overlay.
# Reuse its qualified K/V scales; do not recalibrate against benchmark answers.
# Missing/divergent calibration fails BEFORE deployment. This entrypoint does not
# silently reconstruct a missing calibration or bootstrap an unqualified machine.
# Model weights, baseline venv, previous releases and evidence remain retained.
# All serving values come from validated JSON; no model/context/package CLI overrides.
# Long jobs survive this terminal; output identifies their unit and log directory.
"""Deploy the single qualified Kolibri profile, including its sealed calibration."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import urllib.request

SPARK_ROOT = Path('/home/validatus/workspace/AI-Model')
ACTIONS = ('plan', 'deploy', 'start', 'stop', 'restart', 'status', 'verify')
OWNER = 'AI-Model/kolibri-deployment/v1'


#region [J01] Validated JSON plan

def load_plan(root):
    package = root / 'scripts/deploy/dgx-spark-vllm'
    sys.path.insert(0, str(package))
    from modules.common import Context
    from modules.profiles import ContractError, fingerprint, load, read_json, validate
    schema = {'type': 'object', 'additionalProperties': False,
              'required': ['version', 'model', 'calibration', 'runtime_seconds', 'stage_seconds', 'acceptance_seconds'],
              'properties': {'version': {'type': 'integer', 'const': 1},
                  'model': {'type': 'string', 'const': 'kolibri-1'},
                  'calibration': {'type': 'string', 'const': 'qualified-v5-reuse'},
                  'runtime_seconds': {'type': 'integer', 'minimum': 7200, 'maximum': 14400},
                  'stage_seconds': {'type': 'integer', 'minimum': 3600, 'maximum': 7200},
                  'acceptance_seconds': {'type': 'integer', 'minimum': 1200, 'maximum': 3600}}}
    policy_path = root / 'config/kolibri-deployment.json'
    policy = read_json(policy_path)
    validate(policy, schema)
    if policy['runtime_seconds'] < policy['stage_seconds'] + policy['acceptance_seconds'] + 120:
        raise ContractError('Systemd deadline must cover deployment, acceptance and cleanup')
    ctx = Context(package, load(package, 'kolibri-1'))
    model = ctx.model
    if (model['repository'] != 'Aleph-Alpha/Kolibri-1' or not model['enabled']
            or model['server']['max_model_len'] != 262144 or model['server']['max_num_seqs'] != 1
            or model['server']['kv_cache_dtype'] != 'fp8' or model['quantization'] != 'fp8'
            or model['server']['host'] != '127.0.0.1' or model['server']['port'] != 8000
            or 'kv_calibration' not in model):
        raise ContractError('Only the calibrated FP8 Kolibri / 262144 / one-sequence profile is supported')
    from modules.calibration import digest
    inputs = [policy_path, root / 'config/kolibri-calibration.json',
              root / 'config/benchmark.json', root / 'scripts/benchmark/accept-calibration.py',
              root / 'scripts/benchmark/benchmark.py', root / 'scripts/audit/check-kolibri-protocol.py']
    return ctx, policy, {'owner': OWNER, 'model': ctx.id, 'fingerprint': fingerprint(ctx.profile, package),
        'repository': str(root), 'calibration': model['kv_calibration'], 'context_tokens': 262144,
        'source_sha256': {str(p.relative_to(root)): digest(p) for p in inputs}}

#endregion
#region [J02] Calibration is part of deployment

def calibration_artifact(ctx, root):
    from modules.calibration import validate_manifest
    from modules.profiles import ContractError, read_json
    spec = ctx.model['kv_calibration']
    manifest_path = Path(spec['manifest'])
    owned = ctx.base / 'calibration'
    manifest_path.resolve().relative_to(owned.resolve())
    manifest = validate_manifest(manifest_path, spec['sha256'], ctx.model['revision'], verify_weights=False)
    if (manifest.get('scale_scope') != 'kv-only-bf16-query'
            or manifest['spec'] != read_json(root / 'config/kolibri-calibration.json')):
        raise ContractError('Expected the qualified KV-only export and unchanged calibration specification')
    return {'status': 'SEALED_KV_CALIBRATION_VERIFIED', 'manifest': str(manifest_path),
            'sha256': spec['sha256'], 'scale_scope': manifest['scale_scope'], 'layers': len(manifest['scales']),
            'weight_shards_rehashed': False, 'new_calibration_inference_requests': 0}

#endregion
#region [J03] Read-only inspection

def status(ctx, plan):
    from modules import lifecycle
    state = lifecycle.managed(ctx)
    return {'status': 'MODEL_STATUS', 'plan': plan, 'deployment': state,
            'service': lifecycle.service_state(ctx),
            'profile_matches': bool(state and state['fingerprint'] == plan['fingerprint'])}

#endregion
#region [J04] Durable execution and immutable job inputs

def submit(ctx, policy, plan, action, root):
    from modules.common import atomic_json, safe_path
    from modules.profiles import ContractError
    ctx.identity()
    if root != SPARK_ROOT or platform.node() != ctx.defaults['hostname'] or sys.version_info < (3, 12):
        raise ContractError('Run on spark-a922 as validatus with the native Python 3.12+')
    if action != 'stop':
        calibration_artifact(ctx, root)
    ctx.initialize()
    folder = safe_path(ctx.base / 'operations' / ('kolibri-' + ctx.run_id))
    folder.mkdir(parents=True, mode=0o700)
    driver = folder / 'kolibri.py'
    shutil.copy2(Path(__file__), driver)
    driver.chmod(0o600)
    unit = 'ai-model-kolibri-operation-' + ctx.run_id + '.service'
    job = dict(plan, action=action, policy=policy, unit=unit,
               driver_sha256=hashlib.sha256(driver.read_bytes()).hexdigest())
    atomic_json(folder / 'job.json', job)
    command = ['systemd-run', '--user', '--wait', '--quiet', '--unit=' + unit,
        '--property=Type=exec', '--property=UMask=0077',
        '--property=RuntimeMaxSec=' + str(policy['runtime_seconds']),
        '--property=TimeoutStopSec=' + str(ctx.defaults['health']['startup_seconds'] + 120),
        '--property=WorkingDirectory=' + str(root), '--setenv=HOME=' + os.environ['HOME'],
        '--setenv=PYTHONDONTWRITEBYTECODE=1', '--setenv=PYTHONNOUSERSITE=1',
        '--property=StandardOutput=append:' + str(folder / 'worker.log'),
        '--property=StandardError=inherit', ctx.defaults['python'], '-B', str(driver), '--_job', str(folder)]
    print(json.dumps({'status': 'SUBMITTING', 'unit': unit, 'job_directory': str(folder)}), flush=True)
    result = subprocess.run(command)
    receipt = folder / 'receipt.json'
    if result.returncode or not receipt.is_file():
        raise ContractError('Systemd operation failed; inspect ' + str(folder) + ' and ' + unit)
    from modules.profiles import read_json
    data = read_json(receipt)
    print(json.dumps(data, indent=2), flush=True)
    return 0 if data['status'] == 'COMPLETED' else 1

#endregion
#region [J05] Preserve benchmark and live-request exclusion

@contextlib.contextmanager
def benchmark_guard(ctx):
    from modules.profiles import ContractError
    folder = ctx.root / 'tools/benchmark'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'benchmark.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (folder / 'active-run.json').exists():
            raise ContractError('Existing active/interrupted benchmark requires review')
        from modules import lifecycle
        if lifecycle.service_state(ctx).get('ActiveState') == 'active':
            body = metrics()
            if counter(body, 'vllm:num_requests_running') or counter(body, 'vllm:num_requests_waiting'):
                raise ContractError('Model requests are active; refuse lifecycle interference')
        yield


def metrics():
    with urllib.request.urlopen('http://127.0.0.1:8000/metrics', timeout=15) as response:
        return response.read().decode()


def counter(body, name):
    return sum(float(s.rsplit(' ', 1)[1]) for s in body.splitlines()
               if s.startswith(name + '{') or s.startswith(name + ' '))

#endregion
#region [J06] Bounded subprocesses and evidence

def run_step(folder, receipt, name, command, timeout, env, cleanup_seconds=30):
    from modules.common import atomic_json, now
    from modules.profiles import ContractError
    row = {'name': name, 'started_at': now(), 'status': 'RUNNING'}
    receipt['steps'].append(row)
    atomic_json(folder / 'receipt.json', receipt)
    with (folder / (name + '.log')).open('xb') as log:
        child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = child.wait(timeout=timeout)
        except BaseException as exc:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=cleanup_seconds)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=30)
            row.update(status='FAILED', finished_at=now(), error={'type': type(exc).__name__, 'message': str(exc)})
            atomic_json(folder / 'receipt.json', receipt)
            raise
    row.update(finished_at=now(), exit_code=code, status='COMPLETED' if code == 0 else 'FAILED')
    atomic_json(folder / 'receipt.json', receipt)
    if code:
        raise ContractError(name + ' failed; evidence preserved, no automatic retry')

#endregion
#region [J07] Reuse accepted calibration/capacity without duplicate inference

def acceptance_id(ctx, state, pid):
    from modules.profiles import ContractError, read_json
    base = ctx.root / 'tools/benchmark/acceptances'
    matches = []
    for path in sorted(base.glob('*/receipt.json')):
        old = read_json(path)
        if (old.get('release') != state['release']
                or old.get('manifest_sha256') != ctx.model['kv_calibration']['sha256']):
            continue
        recorded_pid = old.get('after', old.get('before', {})).get('unit', {}).get('MainPID')
        if recorded_pid != pid:
            continue
        if old.get('status') != 'VERIFIED_CAPACITY_AND_SEMANTIC_PROTOCOL':
            raise ContractError('Existing incomplete acceptance requires review: ' + str(path))
        if path.parent.name != old['run_id']:
            raise ContractError('Acceptance ID/path mismatch')
        matches.append(old['run_id'])
    return (matches[0], True) if matches else ('deployment-' + state['fingerprint'][:12] + '-' + pid, False)

#endregion
#region [J08] Roll back only a newly committed, unchanged candidate

def rollback_candidate(ctx, folder, before, candidate):
    from modules import deployment, lifecycle
    from modules.common import atomic_json
    from modules.profiles import ContractError, read_json
    if not candidate or candidate == before:
        return False
    with benchmark_guard(ctx), ctx.locked():
        if lifecycle.managed(ctx) != candidate:
            raise ContractError('Candidate diverged; preserve evidence and recover manually')
        journal = ctx.base / (ctx.id + '-transaction.json')
        transaction = read_json(journal)
        if (transaction.get('phase') != 'committed' or transaction['previous'] != before
                or transaction['candidate'] != candidate['release']):
            raise ContractError('Unexpected cutover journal; refuse recovery')
        shutil.copy2(journal, folder / 'transaction-before-acceptance-rollback.json')
        shutil.copy2(Path(candidate['release']) / 'transaction.json', folder / 'release-transaction-before-acceptance-rollback.json')
        deployment.rollback(ctx, transaction)
        atomic_json(folder / 'rollback.json', {'status': 'PREVIOUS_RELEASE_RESTORED', 'previous': before,
                                             'service': lifecycle.service_state(ctx)})
        return True

#endregion
#region [J09] One model pipeline

def job_provenance(job):
    from modules.profiles import ContractError
    invocation = os.environ.get('INVOCATION_ID', '')
    cgroup = Path('/proc/self/cgroup').read_text().strip()
    unit = job.get('unit', '')
    if (len(invocation) != 32 or any(c not in '0123456789abcdef' for c in invocation)
            or not unit.startswith('ai-model-kolibri-operation-') or '/' in unit
            or not cgroup.endswith('/' + unit)):
        raise ContractError('The worker must run in its submitted durable systemd service')
    return {'unit': unit, 'invocation': invocation, 'cgroup': cgroup}


def run_worker(folder):
    from_root = SPARK_ROOT
    ctx, policy, plan = load_plan(from_root)
    from modules import lifecycle
    from modules.common import atomic_json, now, safe_path
    from modules.profiles import ContractError, read_json
    from modules.calibration import digest
    ctx.identity()
    folder = safe_path(folder)
    if folder.parent != ctx.base / 'operations' or folder.stat().st_uid != os.geteuid():
        raise ContractError('Unexpected operation directory')
    job = read_json(folder / 'job.json')
    if (job.get('owner') != OWNER or job.get('action') not in ACTIONS[1:5] + ('verify',)
            or job['fingerprint'] != plan['fingerprint'] or job['source_sha256'] != plan['source_sha256']
            or job['policy'] != policy or digest(Path(__file__)) != job['driver_sha256']):
        raise ContractError('Job/source/profile changed; refuse operation')
    if (folder / 'receipt.json').exists():
        raise ContractError('Retained job cannot be replayed; inspect its receipt')
    provenance = job_provenance(job)
    before, candidate = None, None
    receipt = {'owner': OWNER, 'status': 'RUNNING', 'action': job['action'], 'started_at': now(),
               'model': ctx.id, 'steps': [], 'calibration': None, 'job': provenance,
               'fingerprint': plan['fingerprint'], 'source_sha256': plan['source_sha256'],
               'driver_sha256': job['driver_sha256']}
    atomic_json(folder / 'receipt.json', receipt)
    with (ctx.base / '.kolibri-operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = lifecycle.managed(ctx)
            receipt['before'] = before
            if job['action'] != 'stop':
                receipt['calibration'] = calibration_artifact(ctx, from_root)
            env = ctx.environment()
            command = [ctx.defaults['python'], '-B', str(ctx.package / 'vllmctl.py')]
            if job['action'] != 'verify':
                with benchmark_guard(ctx):
                    run_step(folder, receipt, 'lifecycle', command + [job['action'], ctx.id], policy['stage_seconds'], env, ctx.defaults['health']['startup_seconds'] + 30)
            candidate = lifecycle.managed(ctx)
            if job['action'] != 'stop':
                if not candidate or candidate['fingerprint'] != plan['fingerprint']:
                    raise ContractError('Exact calibrated profile/source must be deployed')
                pid = lifecycle.service_state(ctx)['MainPID']
                aid, reused = acceptance_id(ctx, candidate, pid)
                receipt['acceptance'] = {'run_id': aid, 'reused_completed_id': reused}
                run_step(folder, receipt, 'acceptance', [ctx.defaults['python'], '-B',
                    str(from_root / 'scripts/benchmark/accept-calibration.py'), '--config',
                    str(from_root / 'config/benchmark.json'), '--run-id', aid], policy['acceptance_seconds'], env, ctx.defaults['health']['startup_seconds'] + 30)
            receipt.update(status='COMPLETED', after=lifecycle.managed(ctx), service=lifecycle.service_state(ctx))
        except BaseException as exc:
            receipt.update(status='FAILED', error={'type': type(exc).__name__, 'message': str(exc)})
            # vllmctl rolls back cutover failures itself. This handles a later
            # capacity/protocol failure only when deploy created a new release.
            if job['action'] == 'deploy' and candidate and candidate != before:
                try:
                    receipt['previous_release_restored'] = rollback_candidate(ctx, folder, before, candidate)
                except BaseException as recovery:
                    receipt['recovery_error'] = str(recovery)
            raise
        finally:
            receipt['finished_at'] = now()
            atomic_json(folder / 'receipt.json', receipt)
    return 0

#endregion
#region [J10] Single CLI

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', default='deploy', choices=ACTIONS)
    parser.add_argument('--_job', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    def interrupted(signum, frame):
        raise RuntimeError('Kolibri operation interrupted by signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args._job:
            return run_worker(args._job)
        root = Path(__file__).resolve().parents[2]
        ctx, policy, plan = load_plan(root)
        if args.action == 'plan':
            plan['calibration_available_here'] = Path(ctx.model['kv_calibration']['manifest']).is_file()
            plan['status'] = 'READ_ONLY_PLAN_NOT_LIVE_ACCEPTANCE'
            print(json.dumps(plan, indent=2))
            return 0
        ctx.identity()
        if args.action == 'status':
            print(json.dumps(status(ctx, plan), indent=2))
            return 0
        return submit(ctx, policy, plan, args.action, root)
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'FAILED', 'error': type(exc).__name__, 'message': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
#endregion
