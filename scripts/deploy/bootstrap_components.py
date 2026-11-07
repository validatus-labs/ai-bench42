"""Portable bootstrap components. Called by scripts/bootstrap.py, never by sudo directly.

bootstrap_components.py
|-- account() / validate_target()  OS account and explicit runtime identity
|-- model_package()                retained per-account model source/profile
|-- playwright()                   locked npm tree and managed MCP tool
|-- engine()                       idempotent pinned vLLM environment
`-- model()                        FP8 checkpoint + optional reusable KV calibration
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import pwd
import re
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[2]
DEPLOY = PROJECT / 'scripts/deploy'
PACKAGES = {'@playwright/mcp': '0.0.83', 'playwright': '1.64.0-alpha-1790635538000',
            'playwright-core': '1.64.0-alpha-1790635538000'}


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    if path.exists() and not path.is_symlink() and path.read_bytes() == rendered:
        if path.stat().st_mode & 0o777 != 0o600:
            raise ValueError('Managed JSON permissions changed: ' + str(path))
        return
    temporary = path.with_name(path.name + '.tmp-' + str(os.getpid()) + '-' + os.urandom(6).hex())
    with temporary.open('x') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)


def safe(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or not re.fullmatch(r'/[a-zA-Z0-9_./@-]+', str(path)):
        raise ValueError('Use an absolute path without spaces, traversal or systemd special characters')
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('Symlink in managed path: ' + str(parent))
    return path


def account(project=PROJECT, runtime=None):
    if os.geteuid() == 0:
        raise ValueError('Start the wrapper as your normal account, without sudo')
    user = pwd.getpwuid(os.geteuid())
    project = safe(Path(project).resolve())
    return {'user': user.pw_name, 'uid': user.pw_uid, 'gid': user.pw_gid,
            'home': user.pw_dir, 'hostname': platform.node(), 'project': str(project),
            'runtime': str(safe(Path(runtime) if runtime else Path(user.pw_dir) / '.modelbench' / platform.node()))}


def validate_target(target):
    expected = {'user', 'uid', 'gid', 'home', 'hostname', 'project', 'runtime'}
    if set(target) != expected or type(target['uid']) is not int or type(target['gid']) is not int:
        raise ValueError('Invalid bootstrap target')
    user = pwd.getpwnam(target['user'])
    if target['uid'] == 0 or (user.pw_uid, user.pw_gid, user.pw_dir) != (target['uid'], target['gid'], target['home']):
        raise ValueError('Target differs from the OS account; no account is created or granted sudo')
    if target['hostname'] != platform.node():
        raise ValueError('Bootstrap target belongs to another host')
    for field in ('home', 'project', 'runtime'):
        safe(target[field])
    return target


def environment(target):
    return {'HOME': target['home'], 'USER': target['user'], 'LOGNAME': target['user'],
            'PATH': '/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
            'XDG_RUNTIME_DIR': '/run/user/' + str(target['uid'])}


def load_script(name):
    spec = importlib.util.spec_from_file_location('bootstrap_' + name.replace('-', '_'), DEPLOY / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def model_package(target, calibration=False):
    original = DEPLOY / 'dgx-spark-vllm'
    fingerprint = hashlib.sha256(json.dumps({'target': target, 'calibration': calibration}, sort_keys=True).encode())
    fingerprint.update(Path(__file__).read_bytes())
    for path in sorted(original.rglob('*')):
        if path.is_file() and path.suffix in {'.py', '.json'} and 'tests' not in path.parts:
            fingerprint.update(str(path.relative_to(original)).encode())
            fingerprint.update(path.read_bytes())
    if calibration:
        calibration_record = json.loads((Path(target['runtime']) / 'tools/bootstrap/calibration.json').read_text())
        proof = Path(calibration_record['kv_calibration']['manifest']).parent / 'loader-exact-preflight.json'
        if digest(proof) != calibration_record['loader_proof_sha256']:
            raise ValueError('Calibration loader proof changed')
        fingerprint.update(json.dumps(calibration_record, sort_keys=True).encode())
    destination = safe(Path(target['runtime']) / 'tools/bootstrap/model-source' / fingerprint.hexdigest()[:20])
    if destination.exists():
        registry = json.loads((destination / 'bootstrap-source.json').read_text())
        actual_files = {str(p.relative_to(destination)) for p in destination.rglob('*') if p.is_file()}
        if actual_files != set(registry['files']) | {'bootstrap-source.json'}:
            raise ValueError('Unexpected file in retained model source')
        if registry['fingerprint'] != fingerprint.hexdigest():
            raise ValueError('Model source fingerprint differs')
        for name, checksum in registry['files'].items():
            if digest(safe(destination / name)) != checksum:
                raise ValueError('Retained bootstrap model source diverged: ' + name)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='model-source-stage-', dir=destination.parent))
    shutil.copytree(original, stage, dirs_exist_ok=True, ignore=shutil.ignore_patterns('tests', '__pycache__', '*.pyc'))
    defaults = json.loads((stage / 'config/defaults.json').read_text())
    defaults.update(user=target['user'], hostname=target['hostname'], runtime_root=target['runtime'])
    atomic(stage / 'config/defaults.json', defaults)
    profile = json.loads((stage / 'models/kolibri-1.json').read_text())
    profile.pop('kv_calibration', None)
    if calibration:
        profile['kv_calibration'] = calibration_record['kv_calibration']
        profile['server']['kv_cache_dtype'] = 'fp8'
    atomic(stage / 'models/kolibri-1.json', profile)
    files = {str(p.relative_to(stage)): digest(p) for p in stage.rglob('*') if p.is_file()}
    atomic(stage / 'bootstrap-source.json', {'fingerprint': fingerprint.hexdigest(), 'files': files})
    if destination.exists():
        raise ValueError('Model source appeared concurrently; staging retained')
    load_script('install-playwright-mcp.py').publish(stage, destination)
    return destination


def activate(package):
    # Each worker handles one target; module names remain consistent during calibration.
    text = str(package)
    if text not in sys.path:
        sys.path.insert(0, text)
    from modules.common import Context
    from modules.profiles import load
    return Context(package, load(package, 'kolibri-1'))


def playwright(target):
    # Fresh installations and explicit updates use a qualified release. Keep
    # legacy data in place; never rewrite its seal after an APT browser update.
    import toolchain_lifecycle as lifecycle
    root = lifecycle.store(target)
    data = lifecycle.policy(PROJECT / 'config/toolchain-updates.json')
    with lifecycle.locked(root, wait_seconds=7200):
        selected = lifecycle.active(root)
        if selected is None:
            lifecycle.update(root, data, promote_after=data['automatic_promotion'])
            selected = lifecycle.active(root)
        else:
            lifecycle.verify_release(root, selected['release'])
            try: lifecycle.qualification(root, data, selected['release'])
            except (RuntimeError, OSError): lifecycle.qualify(root, data, selected['release'])
        if selected is None:
            raise ValueError('No qualified browser toolchain is active')
        import importlib.util
        spec = importlib.util.spec_from_file_location('modelbench_toolchain_cli', PROJECT / 'scripts/toolchain.py')
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        cli.publish_client(target, root, selected['release'])
        return {'status': 'READY_HOST_TOOLCHAIN_NOT_C00', 'release': selected['release']}


def legacy_playwright(target):
    """Historical native-browser layout; retained only for operator recovery."""
    installer = load_script('install-playwright-mcp.py')
    root = Path(target['runtime'])
    base = safe(root / 'tools/playwright')
    profile = {'version': 1, 'hostname': target['hostname'], 'user': target['user'], 'node': '/usr/bin/node',
               'minimum_node_major': 22, 'module_root': str(base / 'node_modules'), 'packages': PACKAGES,
               'browser': '/opt/brave.com/brave/brave', 'runtime': str(root / 'tools/playwright-tool'),
               'temporary_root': str(root / 'tmp')}
    installer.ROOT = installer.SPARK = Path(target['project'])
    installer.identity(profile)
    if not base.exists():
        base.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='playwright-stage-', dir=base.parent))
        node = subprocess.check_output(['/usr/bin/node', '--version'], text=True).strip()
        if int(node.lstrip('v').split('.')[0]) < 22:
            raise ValueError('Native Node 22+ is required; configure its signed APT source first')
        atomic(stage / 'package.json', {'private': True, 'dependencies': PACKAGES})
        env = dict(environment(target), PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD='1',
                   npm_config_cache=str(stage / 'cache'), npm_config_update_notifier='false')
        for arguments in (['install', '--package-lock-only'], ['ci']):
            subprocess.run(['/usr/bin/npm', *arguments, '--ignore-scripts', '--no-audit', '--no-fund'],
                           cwd=stage, env=env, check=True, timeout=900)
        lock = json.loads((stage / 'package-lock.json').read_text())
        for name, value in lock['packages'].items():
            if name and (not value.get('resolved', '').startswith('https://registry.npmjs.org/')
                         or not value.get('integrity', '').startswith('sha512-')):
                raise ValueError('Unexpected npm origin or missing integrity; staging retained')
        seal = installer.seal_modules(stage / 'node_modules')
        atomic(stage / 'bootstrap.json', {'packages': PACKAGES, 'lock_sha256': digest(stage / 'package-lock.json'), 'seal': seal})
        installer.publish(stage, base)
    receipt = json.loads((base / 'bootstrap.json').read_text())
    if (receipt['packages'] != PACKAGES or receipt['lock_sha256'] != digest(base / 'package-lock.json')
            or receipt['seal'] != installer.seal_modules(base / 'node_modules')):
        raise ValueError('Installed MCP dependency tree changed; preserve and investigate')
    safe(root / 'tmp').mkdir(parents=True, exist_ok=True, mode=0o700)
    installer.install(profile)
    client = json.loads((Path(profile['runtime']) / 'kilo.json').read_text())
    atomic(root / 'tools/bootstrap/kilo.json', client)
    return {'status': 'READY', 'lock_sha256': receipt['lock_sha256'], 'tool': profile['runtime']}


def engine(target):
    package = model_package(target)
    ctx = activate(package)
    from modules import compatibility, environment as model_env
    from modules.common import atomic_json
    from modules.profiles import fingerprint
    with ctx.locked():
        compatibility.host(ctx)
        key = fingerprint(ctx.profile, package)
        destination = ctx.base / 'engines' / key[:20]
        receipt = destination / 'bootstrap-engine.json'
        if destination.exists():
            state = json.loads(receipt.read_text())
            frozen = subprocess.check_output([str(destination / 'venv/bin/python'), '-B', '-m', 'pip', 'freeze', '--all'],
                                             env=ctx.environment(destination / 'venv/bin/python'), text=True)
            if state['fingerprint'] != key or frozen != (destination / 'requirements.lock').read_text():
                raise ValueError('Existing engine environment changed')
            return {'status': 'UNCHANGED', 'engine': str(destination)}
        destination.mkdir(parents=True)
        python = model_env.prepare(ctx, destination)
        atomic_json(receipt, {'fingerprint': key, 'python': str(python)})
        return {'status': 'READY', 'engine': str(destination)}


def _controller(package, command):
    module = load_path('portable_vllm_controller', package / 'vllmctl.py')
    if module.main([command, 'kolibri-1']):
        raise RuntimeError('vLLM controller failed: ' + command)


def load_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def calibrated_artifact(target, package):
    ctx = activate(package)
    from modules import lifecycle
    from modules.calibration import digest as model_digest, validate_manifest
    previous = lifecycle.managed(ctx)
    if not previous:
        raise ValueError('Deploy a verified baseline before calibration')
    baseline = Path(previous['release'])
    identity = hashlib.sha256((previous['fingerprint'] + previous['unit_sha256']).encode()).hexdigest()[:16]
    experiment = 'kolibri-bootstrap-kv-' + identity
    folder = ctx.base / 'calibration' / experiment
    manifest = folder / 'manifest.json'
    if folder.exists():
        if not manifest.exists():
            raise ValueError('Previous calibration is incomplete; preserve its evidence before retrying')
        record = validate_manifest(manifest, model_digest(manifest), ctx.model['revision'])
        if record['baseline'] != previous:
            raise ValueError('Retained calibration belongs to a different baseline')
    else:
        (ctx.root / 'tools/benchmark').mkdir(parents=True, exist_ok=True)
        specification = {'experiment': experiment, 'revision': ctx.model['revision'], 'context_tokens': 262144,
                         'baseline_unit_sha256': previous['unit_sha256'], 'samples': 32,
                         'languages': ['en', 'de', 'fr', 'code'], 'input_tokens': 2048, 'output_tokens': 64,
                         'margin': 1.1, 'fp8_max': 448, 'scale_storage_dtype': 'bfloat16',
                         'scale_rounding': 'toward_positive_infinity', 'scale_scope': 'kv-only-bf16-query'}
        # calibrate.py compares this exact maintained input against the supplied path.
        specification_path = package.parents[2] / 'config/kolibri-calibration.json'
        if specification_path.exists():
            if json.loads(specification_path.read_text()) != specification:
                raise ValueError('Existing calibration specification differs')
        else:
            atomic(specification_path, specification)
        calibrator = load_path('portable_calibrator', package / 'calibrate.py')
        original = sys.argv
        try:
            sys.argv = [str(package / 'calibrate.py'), '--spec', str(specification_path)]
            calibrator.main()
        finally:
            sys.argv = original
        validate_manifest(manifest, model_digest(manifest), ctx.model['revision'])
    # Exercise the real vendor CPU loader before promoting the observed scales.
    proof = folder / 'loader-exact-preflight.json'
    if not proof.exists():
        subprocess.run([str(baseline / 'venv/bin/python'), '-B', str(package / 'scale-loader-preflight.py'),
                        '--scales', str(folder / 'scales.json'), '--output', str(proof)],
                       env=ctx.environment(baseline / 'venv/bin/python'), check=True, timeout=180)
    result = {'manifest': str(manifest), 'sha256': model_digest(manifest), 'source_release': str(baseline),
              'requirements_sha256': model_digest(baseline / 'requirements.lock')}
    atomic(Path(target['runtime']) / 'tools/bootstrap/calibration.json', {'kv_calibration': result,
           'loader_proof_sha256': model_digest(proof), 'baseline': previous})
    return result


def model(target, calibration, enabled=True):
    selected = Path(target['runtime']) / 'tools/bootstrap/selected-model.json'
    if enabled and selected.exists() and json.loads(selected.read_text()).get('adopted') is True:
        import verify_installation
        package, selection, profile, status = verify_installation.model_status(target)
        if selection['calibration'] != calibration:
            raise ValueError('Requested calibration differs from the adopted model; no automatic model change')
        if profile['server']['max_model_len'] != 262144 or profile['quantization'] != 'fp8':
            raise ValueError('Adopted model compatibility changed')
        return {'status': 'UNCHANGED', 'calibration': calibration, 'model_requests': 0, 'service_changes': 0}
    package = model_package(target)
    ctx = activate(package)
    from modules import lifecycle
    from modules.calibration import validate_manifest
    if not enabled:
        if lifecycle.managed(ctx):
            _controller(package, 'stop')
            from modules.common import run
            run(['sudo', '-n', 'systemctl', 'disable', ctx.unit])
        return {'status': 'OFF', 'packages_and_models_preserved': True}
    selected = Path(target['runtime']) / 'tools/bootstrap/selected-model.json'
    pending = selected.with_name('pending-model.json')
    if pending.exists():
        request = json.loads(pending.read_text())
        if request['calibration'] != calibration:
            raise ValueError('Interrupted model change requires its original calibration selection')
        candidate = Path(request['package'])
        if candidate != model_package(target, calibration == 'on'):
            raise ValueError('Interrupted model source changed; retained evidence requires review')
        active = activate(candidate)
        previous = lifecycle.managed(active)
        transaction_path = active.base / 'kolibri-1-transaction.json'
        transaction = json.loads(transaction_path.read_text()) if transaction_path.exists() else {}
        if previous and previous['fingerprint'] == request['fingerprint'] and transaction.get('phase') == 'committed':
            acceptance = json.loads((Path(previous['release']) / 'acceptance.json').read_text())
            if 'kv_calibration' in active.model and not acceptance['smoke'].get('semantic_fixture_verified'):
                raise ValueError('Interrupted calibrated model lacks semantic acceptance')
            if 'kv_calibration' in active.model:
                spec = active.model['kv_calibration']
                validate_manifest(spec['manifest'], spec['sha256'], active.model['revision'])
            _controller(candidate, 'start')
            atomic(selected, request)
            pending.unlink()
            return {'status': 'RECOVERED_COMMITTED_MODEL', 'calibration': calibration}
    if selected.exists():
        state = json.loads(selected.read_text())
        if state['calibration'] == calibration:
            active_package = Path(state['package'])
            # Verify retained package bytes and calibration before reusing the deployment.
            if active_package != model_package(target, calibration == 'on'):
                raise ValueError('Selected model source changed; use a reviewed new runtime')
            active = activate(active_package)
            previous = lifecycle.managed(active)
            if previous and previous['fingerprint'] == state['fingerprint']:
                if 'kv_calibration' in active.model:
                    spec = active.model['kv_calibration']
                    validate_manifest(spec['manifest'], spec['sha256'], active.model['revision'])
                _controller(active_package, 'start')
                return {'status': 'UNCHANGED', 'calibration': calibration, 'new_calibration_requests': 0}
    _controller(package, 'deploy')
    if calibration == 'on':
        calibrated_artifact(target, package)
        package = model_package(target, True)
        ctx = activate(package)
        from modules.profiles import fingerprint
        atomic(pending, {'package': str(package), 'calibration': calibration,
                         'fingerprint': fingerprint(ctx.profile, package)})
        _controller(package, 'deploy')
    current = lifecycle.managed(ctx)
    atomic(selected, {'package': str(package), 'calibration': calibration, 'fingerprint': current['fingerprint']})
    if pending.exists():
        pending.unlink()
    return {'status': 'READY', 'calibration': calibration, 'weights': 'FP8',
            'kv_cache': 'FP8 calibrated' if calibration == 'on' else 'FP8 without project calibration'}
