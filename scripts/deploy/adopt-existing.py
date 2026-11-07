#!/usr/bin/env python3
"""Register an existing owned Kolibri deployment without changing its service.

adopt-existing.py
|-- inspect existing source/controller + exact live deployment identity
|-- copy source bytes into a sealed private registry (no venv/weights copied)
|-- recheck PID, fingerprint, profile and files before publication
`-- repeat verifies existing registration; no start/install/model generation
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from modelbench import common as c
import bootstrap_components as components


def observe(package):
    result = subprocess.run(['/usr/bin/python3', '-B', str(package / 'vllmctl.py'), 'status', 'kolibri-1'],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45,
                            env=components.environment(components.account(ROOT)))
    c.require(result.returncode == 0 and len(result.stdout) <= 1024 * 1024, 'Existing model controller status failed')
    status = json.loads(result.stdout)
    c.require(status.get('profile_matches') is True and status.get('deployment'), 'Existing deployment does not match its own source profile')
    service = status.get('service', {})
    c.require(service.get('ActiveState') == 'active' and service.get('MainPID') not in (None, '0'), 'Existing model is not active')
    return status


def snapshot(package):
    result = {}
    for path in sorted(package.rglob('*')):
        name = path.relative_to(package)
        if any(part in {'tests', '__pycache__', '.git'} for part in name.parts): continue
        c.require(not path.is_symlink(), 'Source package contains a symlink')
        if path.is_file():
            c.require(path.stat().st_size <= 8 * 1024 * 1024 and path.suffix not in {'.pem', '.key', '.eml', '.mbox', '.safetensors', '.gguf'}, 'Unexpected payload in source package')
            result[str(name)] = c.digest(path)
        c.require(len(result) <= 1000, 'Source package exceeds size limit')
    c.require('vllmctl.py' in result and 'config/defaults.json' in result and 'models/kolibri-1.json' in result, 'Incomplete source package')
    return result


def adopt(runtime, source, apply=False):
    target = components.account(ROOT, runtime)
    source = c.safe(source); runtime = c.safe(runtime)
    defaults = c.read(source / 'config/defaults.json')
    c.require(defaults['runtime_root'] == str(runtime) and defaults['user'] == target['user'] and defaults['hostname'] == target['hostname'], 'Source/runtime/account do not match the existing installation')
    model = c.read(source / 'models/kolibri-1.json')
    c.require(model['id'] == 'kolibri-1' and model['revision'] == '258cae8ffffc8c12db670bdbc6ac01bcf8826c87'
              and model['server']['max_model_len'] == 262144 and model['quantization'] == 'fp8', 'Unsupported adopted model/profile')
    calibration = 'on' if 'kv_calibration' in model else 'off'
    if calibration == 'on': c.pin({'path': model['kv_calibration']['manifest'], 'sha256': model['kv_calibration']['sha256']})
    files = snapshot(source); before = observe(source)
    identity = {'fingerprint': before['deployment']['fingerprint'], 'release': before['deployment']['release'],
                'pid': before['service']['MainPID'], 'unit_sha256': before['deployment']['unit_sha256']}
    key = c.fingerprint(files)
    destination = runtime / 'tools/bootstrap/model-source' / key[:20]
    record = {'package': str(destination), 'calibration': calibration, 'fingerprint': identity['fingerprint'],
              'adopted': True, 'original_source': str(source)}
    if not apply: return {'status': 'ADOPTION_PLAN_ONLY', 'selection': record, 'observed': identity, 'source_files': len(files), 'model_requests': 0}
    parent = c.private_directory(runtime / 'tools/bootstrap')
    with c.locked(parent / 'adoption.lock'):
        selected = parent / 'selected-model.json'
        if selected.exists(): c.require(c.read(selected) == record, 'Preserve conflicting model selection; no replacement')
        destination.parent.mkdir(mode=0o700, exist_ok=True)
        if not destination.exists():
            stage = Path(tempfile.mkdtemp(prefix='adopt-source-', dir=destination.parent))
            for name, checksum in files.items():
                path = stage / name; path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                shutil.copyfile(source / name, path)
                c.require(c.digest(path) == checksum, 'Source changed during copy')
            c.save(stage / 'bootstrap-source.json', {'fingerprint': key, 'files': files})
            c.require(snapshot(source) == files, 'Original source changed during adoption')
            components.load_script('install-playwright-mcp.py').publish(stage, destination)
        registry = c.read(destination / 'bootstrap-source.json')
        c.require(registry == {'fingerprint': key, 'files': files}, 'Adopted source registry changed')
        actual = c.inventory(destination); actual.pop('bootstrap-source.json', None)
        c.require(actual == files, 'Adopted source changed')
        after = observe(destination)
        c.require(after['deployment'] == before['deployment'] and after['service']['MainPID'] == identity['pid'], 'Existing deployment changed during adoption')
        reused = selected.exists()
        if not reused: c.save(selected, record)
        return {'status': 'UNCHANGED' if reused else 'EXISTING_MODEL_REGISTERED', 'selection': record,
                'source_files': len(files), 'model_requests': 0, 'service_changes': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--source-package', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(adopt(args.runtime_root, args.source_package, args.apply), indent=2)); return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr); return 2


if __name__ == '__main__': sys.exit(main())
