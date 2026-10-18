"""Optional repeatable benchmark-tool venv setup from a sealed offline wheelhouse.

provision.py
|-- existing environment  reuse, then check the complete installed lock
`-- absent environment    --copies venv -> hash-locked, wheel-only pip install
"""
from pathlib import Path

from . import common as c


def ensure_runtime(spec, folder, validate_data):
    python_spec = spec['python']
    c.require(isinstance(python_spec.get('path'), str), 'Configure the benchmark venv interpreter path')
    python = c.safe(python_spec['path'])
    if python.exists(): return
    setup = spec.get('provision')
    c.require(isinstance(setup, dict), 'Benchmark environment is absent; configure provision or supply a pinned environment')
    c.require(python.name == 'python' and python.parent.name == 'bin', 'Provision target must be <venv>/bin/python')
    venv = python.parent.parent
    c.require(not venv.exists(), 'Partial/unowned benchmark environment exists; preserve it and select a new environment path')
    base = c.pin(setup['base_python'])
    lock = c.pin(setup['install_lock'])
    wheelhouse = c.safe(setup['wheelhouse'])
    validate_data(setup['data_manifest'], roots=[wheelhouse])
    c.require(wheelhouse.is_dir() and any(wheelhouse.glob('*.whl')), 'Offline wheelhouse is empty')
    c.require(all(path.suffix == '.whl' for path in wheelhouse.iterdir()), 'Wheelhouse must contain wheels only; no source builds')
    c.require('--hash=sha256:' in lock.read_text(), 'Installation lock must contain pip SHA-256 hashes')
    c.private_directory(venv.parent)
    with c.locked(venv.parent / (venv.name + '.provision.lock')):
        c.require(not venv.exists(), 'Environment appeared concurrently; inspect it before reuse')
        marker = venv.parent / (venv.name + '.provision.json')
        c.require(not marker.exists(), 'Previous failed provisioning is retained; use a new environment path')
        record = {'schema_version': 1, 'status': 'PREPARING', 'inputs': spec}
        c.save(marker, record)
        try:
            result = c.execute([str(base), '-I', '-m', 'venv', '--copies', str(venv)], folder / 'create-venv', 300)
            c.require(result.get('exit_code') == 0, 'Could not create benchmark venv')
            c.pin(python_spec)
            result = c.execute([str(python), '-I', '-m', 'pip', '--isolated', 'install', '--no-index', '--no-input',
                                '--disable-pip-version-check', '--only-binary=:all:', '--require-hashes',
                                '--find-links', str(wheelhouse), '-r', str(lock)], folder / 'install-wheels', 1800)
            c.require(result.get('exit_code') == 0, 'Hash-locked offline benchmark installation failed')
            validate_data(setup['data_manifest'], roots=[wheelhouse]); c.pin(setup['install_lock'])
            record['status'] = 'INSTALLED_AWAITING_RUNTIME_LOCK_CHECK'
        except BaseException:
            record['status'] = 'FAILED_RETAINED'
            raise
        finally:
            c.save(marker, record)
