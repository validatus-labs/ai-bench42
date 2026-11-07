#!/usr/bin/env python3
"""Verify an owned calibrated release before its frozen benchmark cohort.

Run as validatus: python3 -B scripts/benchmark/accept-calibration.py
  --config config/benchmark.json --run-id kvonly-v5-20261017-v1
Flow: validated profiles + exclusive benchmark lock -> loaded/backend/semantic
gates -> no-op deploy -> real full context -> reasoning/tools -> unique receipt.
Preserves all releases, prior evidence and source. Failed/interrupted IDs refuse
automatic retries. Repeating a completed ID verifies retained hashes/current PID
without issuing model requests. No installs, server restart or host changes.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from benchmark import check_idle, inventory, load_config, now, write_json


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', required=True, type=Path)
    ap.add_argument('--run-id', required=True)
    args = ap.parse_args()
    root = Path('/home/validatus/workspace/AI-Model')
    if args.config.resolve() != root / 'config/benchmark.json' or not re.fullmatch('[a-z0-9-]+', args.run_id):
        ap.error('Use the owned Spark configuration and a bounded run ID')
    package = root / 'scripts/deploy/dgx-spark-vllm'
    sys.path.insert(0, str(package))
    from modules.common import Context
    from modules.profiles import fingerprint, load
    from modules import lifecycle
    ctx = Context(package, load(package, 'kolibri-1'))
    ctx.identity()
    config = load_config(args.config)
    base = Path(config['runtime'])
    if base != root / 'runtime/spark-a922/tools/benchmark':
        raise RuntimeError('Unexpected benchmark runtime')
    with (base / 'benchmark.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (base / 'active-run.json').exists():
            raise RuntimeError('Review the existing benchmark marker first')
        state = lifecycle.managed(ctx)
        if not state or state['fingerprint'] != fingerprint(ctx.profile, package):
            raise RuntimeError('Current exact source/profile must already be deployed')
        release = Path(state['release'])
        spec = ctx.model.get('kv_calibration')
        if not spec:
            raise RuntimeError('A calibrated release is required')
        loaded_path = release / 'loaded-calibration.json'
        loaded = json.loads(loaded_path.read_text())
        accepted = json.loads((release / 'acceptance.json').read_text())
        before = inventory(config, 'kolibri-1')
        check_idle(before, config)
        if (loaded['status'] != 'ALL_200_SCALES_LOADED' or loaded['manifest_sha256'] != spec['sha256']
                or accepted.get('smoke', {}).get('semantic_fixture_verified') is not True
                or not loaded.get('backend_compatibility', {}).get('selector_uses_actual_worker_config_and_platform')):
            raise RuntimeError('Mechanical, backend and semantic cutover gates must pass')
        if ((Path('/proc') / str(loaded['worker_pid']) / 'cgroup').read_text().strip() != loaded['cgroup']
                or loaded['cgroup'].split('::', 1)[-1] != before['unit']['ControlGroup']):
            raise RuntimeError('Loaded-scale worker is no longer live in its attested cgroup')
        folder = base / 'acceptances' / args.run_id
        receipt_path = folder / 'receipt.json'
        if folder.exists():
            old = json.loads(receipt_path.read_text())
            if (old.get('status') != 'VERIFIED_CAPACITY_AND_SEMANTIC_PROTOCOL'
                    or old.get('release') != str(release)
                    or old['after']['unit']['MainPID'] != before['unit']['MainPID']):
                raise RuntimeError('Existing incomplete/stale acceptance requires review; no automatic retry')
            for name, row in old['files'].items():
                path = Path(name)
                if path.is_symlink() or path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
                    raise RuntimeError('Retained acceptance artifact changed')
            print(json.dumps({'status': 'ALREADY_VERIFIED_NO_INFERENCE', 'receipt': str(receipt_path)}))
            return
        folder.mkdir(parents=True, mode=0o700)
        for path in (Path(__file__), Path(__file__).with_name('benchmark.py')):
            shutil.copy2(path, folder / path.name)
        protocol = ctx.log_root / ('kolibri-calibration-' + args.run_id + '-protocol.json')
        if protocol.exists():
            raise RuntimeError('Unique protocol evidence path already exists')
        result = {'status': 'RUNNING', 'run_id': args.run_id, 'started_at': now(), 'release': str(release),
                  'manifest_sha256': spec['sha256'], 'before': before, 'steps': [],
                  'scope': 'Finite semantic/capacity fixtures, not general quality or benchmark scores.'}
        write_json(receipt_path, result)

        def step(name, script, arguments, timeout):
            row = {'name': name, 'started_at': now(), 'script_sha256': sha(script)}
            result['steps'].append(row)
            write_json(receipt_path, result)
            with (folder / (name + '.log')).open('x') as log:
                process = subprocess.run(['/usr/bin/python3', '-B', str(script)] + arguments,
                                         cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            row.update(finished_at=now(), exit_code=process.returncode)
            write_json(receipt_path, result)
            if process.returncode:
                raise RuntimeError(name + ' failed; preserve evidence and review, no automatic retry')

        try:
            state_before = ctx.state_path.read_bytes()
            releases_before = sorted(p.name for p in (ctx.base / 'releases').iterdir())
            step('idempotent-deploy', package / 'vllmctl.py', ['deploy', 'kolibri-1'], 300)
            if (ctx.state_path.read_bytes() != state_before
                    or sorted(p.name for p in (ctx.base / 'releases').iterdir()) != releases_before
                    or lifecycle.service_state(ctx)['MainPID'] != before['unit']['MainPID']):
                raise RuntimeError('Repeat deploy changed state/releases/PID')
            result['idempotence'] = {'state_unchanged': True, 'release_count': len(releases_before), 'pid_unchanged': True}
            previous = set(ctx.log_root.glob('kolibri-1-*-verification.json'))
            step('full-context', package / 'vllmctl.py', ['verify', 'kolibri-1', '--long-context'], 900)
            created = set(ctx.log_root.glob('kolibri-1-*-verification.json')) - previous
            if len(created) != 1:
                raise RuntimeError('Exactly one new capacity receipt required')
            capacity_path = created.pop()
            capacity = json.loads(capacity_path.read_text())
            if not capacity['full_context_request_verified'] or capacity['long_context']['usage']['total_tokens'] != 262144:
                raise RuntimeError('Full context acceptance missing')
            result['capacity'] = {'path': str(capacity_path), 'sha256': sha(capacity_path), 'data': capacity}
            step('protocol', root / 'scripts/audit/check-kolibri-protocol.py', ['--output', str(protocol)], 600)
            evidence = json.loads(protocol.read_text())
            if evidence.get('passed') is not True or evidence['release'] != str(release):
                raise RuntimeError('Current-release protocol acceptance missing')
            result['protocol'] = {'path': str(protocol), 'sha256': sha(protocol)}
            result['after'] = inventory(config, 'kolibri-1')
            check_idle(result['after'], config)
            if result['after']['unit']['MainPID'] != before['unit']['MainPID'] or ctx.state_path.read_bytes() != state_before:
                raise RuntimeError('Model changed during acceptance')
            result['status'] = 'VERIFIED_CAPACITY_AND_SEMANTIC_PROTOCOL'
        except BaseException as exc:
            result.update(status='FAILED', error={'type': type(exc).__name__, 'message': str(exc)})
            raise
        finally:
            result['finished_at'] = now()
            files = [p for p in folder.iterdir() if p.is_file() and p != receipt_path]
            files += [loaded_path, release / 'acceptance.json']
            if 'capacity' in result:
                files.append(Path(result['capacity']['path']))
            if protocol.exists():
                files.append(protocol)
            result['files'] = {str(p): {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in files}
            write_json(receipt_path, result)
        print(json.dumps({'status': result['status'], 'receipt': str(receipt_path), 'protocol_evidence': str(protocol)}))


if __name__ == '__main__':
    main()
