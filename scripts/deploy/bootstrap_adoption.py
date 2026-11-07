#!/usr/bin/env python3
"""Register an explicitly pinned existing Spark stack without redeployment.

Normal account only. No APT/npm, model inference, service mutation or root claim.
Inputs: reviewed JSON profile; private destination runtime. Evidence: --output.
Example: python3 -B scripts/deploy/bootstrap_adoption.py inspect --profile config/spark-adoption.json

bootstrap_adoption.py
|-- [J01] profile()/identity()  exact pins and normal-account/path boundary
|-- [J02] inspect()             maintenance, V5, MCP, health and live endpoints
|-- [J03] browser_proof()       current native Brave/MCP; no model generation
|-- [J04] adopt()               all gates first -> atomic registry publication
`-- [J05] check()/main()        drift refusal, unchanged repeat and CLI

VS Code: Ctrl+Shift+O for functions; Ctrl+F [J01]...[J05].
This adoption is not a fresh installation, updater rollout or worker C00 gate.
"""
import argparse
import contextlib
import copy
import ctypes
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import pwd
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
import uuid

OWNER = 'AI-Bench42/existing-host-adoption/v1'
COMPONENTS = {'maintenance', 'brave', 'playwright', 'vllm', 'kolibri', 'health'}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def safe(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'Absolute nontraversing path required')
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), 'Symlink in managed path: ' + str(parent))
    return path


def read(path):
    def pairs(items):
        value = {}
        for key, item in items:
            require(key not in value, 'Duplicate JSON key: ' + key)
            value[key] = item
        return value
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda _: require(False, 'Nonfinite JSON number'))


def write_new(path, value):
    path = safe(path)
    with path.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())


# [J01] Explicit host pins, never discovered and trusted automatically.
def profile(path):
    data = read(safe(path))
    require(set(data) - {'browser_runtime', 'controller_source'} == {'schema_version', 'hostname', 'user', 'source_root', 'existing_runtime',
                         'destination_runtime', 'files', 'model_fingerprint', 'calibration_sha256',
                         'model_revision', 'browser_sha256', 'node_sha256', 'module_seal_sha256',
                         'model_boot_state'}, 'Unexpected adoption profile fields')
    require(type(data['schema_version']) is int and data['schema_version'] == 1, 'Unsupported profile')
    require(data['model_boot_state'] in ('enabled', 'disabled'), 'Explicit model boot policy required')
    for field in ('source_root', 'existing_runtime', 'destination_runtime'):
        safe(data[field])
    root = Path(data['source_root'])
    require(Path(data['existing_runtime']) == root / 'runtime' / data['hostname'], 'Unexpected existing runtime')
    require(Path(data['destination_runtime']).is_relative_to(Path(data['existing_runtime'])), 'Destination must stay in protected host runtime')
    require(data['destination_runtime'] != data['existing_runtime'], 'Use a separate adoption runtime')
    for key in ('browser_runtime', 'controller_source'):
        if key in data:
            safe(data[key])
            require(Path(data[key]).is_relative_to(Path(data['existing_runtime'])), 'New coordinator/browser runtime must stay in protected existing runtime')
    require(len(data['files']) >= 10, 'Explicit maintenance and health file pins required')
    for name, row in data['files'].items():
        safe(name)
        require(set(row) == {'sha256', 'mode'} and type(row['mode']) is int, 'Invalid file pin')
    for value in [data[k] for k in ('model_fingerprint', 'calibration_sha256', 'browser_sha256',
                                   'node_sha256', 'module_seal_sha256')] + [r['sha256'] for r in data['files'].values()]:
        require(isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value), 'Invalid SHA256 pin')
    return data


def identity(data):
    user = pwd.getpwuid(os.geteuid())
    require(os.geteuid() != 0 and user.pw_name == data['user'] and os.environ.get('HOME') == user.pw_dir,
            'Run as the selected normal account, without sudo')
    require(platform.node() == data['hostname'] and platform.machine() == 'aarch64', 'Wrong host/architecture')
    release = platform.freedesktop_os_release()
    require(release.get('ID') == 'ubuntu' and release.get('VERSION_ID') == '24.04', 'Expected Ubuntu24.04 OEM host')
    require(Path('/proc/1/comm').read_text().strip() == 'systemd', 'Native systemd required')


def command(argv, timeout=30):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                            env={'HOME': pwd.getpwuid(os.getuid()).pw_dir, 'PATH': '/usr/bin:/bin',
                                 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'}, timeout=timeout)
    require(result.returncode == 0, 'Read-only command failed: ' + ' '.join(argv[:4]))
    require(len(result.stdout) < 2 * 1024 * 1024, 'Oversized observation')
    return result.stdout.strip()


def unit(name, boot='enabled'):
    raw = command(['systemctl', 'show', name, '-p', 'ActiveState', '-p', 'MainPID', '-p', 'InvocationID',
                   '-p', 'UnitFileState', '-p', 'FragmentPath', '-p', 'DropInPaths'])
    state = dict(line.split('=', 1) for line in raw.splitlines())
    require(state['ActiveState'] == 'active' and state['UnitFileState'] == boot, 'Service/boot-policy drift: ' + name)
    require(state['FragmentPath'] == '/etc/systemd/system/' + name and not state['DropInPaths'], 'Unit routing/drop-in drift: ' + name)
    return state


def get(url):
    # Fixed internal observations only. Never follow a redirect to another endpoint.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    require(url in {'http://127.0.0.1:8000/health', 'http://127.0.0.1:8000/v1/models',
                    'http://127.0.0.1:9817/healthz'}, 'Endpoint not allowlisted')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=10) as response:
        require(response.status == 200 and response.geturl() == url, 'Unexpected health response')
        body = response.read(1024 * 1024 + 1)
        require(len(body) <= 1024 * 1024, 'Oversized health response')
        return body


def module(path):
    name = 'adoption_' + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def file_pin(path, expected, root_owned=True):
    path = safe(path); state = path.stat()
    require(stat.S_ISREG(state.st_mode) and state.st_uid == (0 if root_owned else os.getuid()), 'Wrong file ownership/type: ' + str(path))
    require(stat.S_IMODE(state.st_mode) == expected['mode'] and digest(path) == expected['sha256'], 'Pinned file drift: ' + str(path))
    return dict(expected)


def process_argv(release, calibration, current, argv):
    from modules.lifecycle import server_argv
    expected = server_argv(current, release)
    lines = Path(expected[0]).read_text().splitlines()
    shebang = lines[0]
    require(shebang.startswith('#!/') and not any(c.isspace() for c in shebang[2:]), 'Unexpected vLLM interpreter shebang')
    interpreter = shebang[2:]
    if interpreter == '/bin/sh':
        # distlib's standard trampoline for interpreter paths beyond the kernel
        # shebang limit. Recognize its exact fixed syntax; never execute it here.
        trampoline = re.fullmatch(r"'''exec' (/[-A-Za-z0-9_./]+) \"\$0\" \"\$@\"", lines[1]) if len(lines) >= 3 else None
        require(trampoline is not None and lines[2] == "' '''", 'Unrecognized vLLM shell trampoline')
        interpreter = trampoline[1]
    allowed = {str(release / 'venv/bin/python'), str(Path(calibration['source_release']) / 'venv/bin/python')}
    require(interpreter in allowed and argv == [os.fsencode(interpreter), *map(os.fsencode, expected)],
            'Live vLLM launcher/interpreter/full arguments differ from the retained release')
    return interpreter


# [J02] Preserve existing ownership; identify exact active release and legacy tools.
def inspect(data):
    identity(data)
    source, old = Path(data['source_root']), Path(data['existing_runtime'])
    files = {name: file_pin(name, row) for name, row in data['files'].items()}
    security = Path('/etc/systemd/system/ai-model-security-updates.timer').read_text()
    weekly = Path('/etc/systemd/system/ai-model-weekly-updates.timer').read_text()
    require('OnCalendar=*-*-* 22:00:00 Europe/Berlin\n' in security, 'Daily Berlin schedule differs')
    require('OnCalendar=Sun *-*-* 03:00:00 Europe/Berlin\n' in weekly, 'Weekly Berlin schedule differs')
    units = {name: unit(name) for name in ('ai-model-security-updates.timer', 'ai-model-weekly-updates.timer',
                                         'dgx-spark-health.timer', 'dgx-spark-health-exporter.service')}
    # Timer invocation/PIDs naturally change; only stable policy enters the registry.
    units = {name: {key: value[key] for key in ('ActiveState', 'UnitFileState', 'FragmentPath', 'DropInPaths')}
             for name, value in units.items()}
    state_path = old / 'build/dgx-spark-vllm/kolibri-1.json'
    state = read(safe(state_path)); release = safe(state['release'])
    require(release.parent == old / 'build/dgx-spark-vllm/releases', 'Release escapes existing runtime')
    require(state.get('owner') == 'AI-Model/dgx-spark-vllm/v1' and state['model'] == 'kolibri-1'
            and state['fingerprint'] == data['model_fingerprint'], 'Unapproved model identity')
    current = read(release / 'profile.json'); model = current['model']; defaults = current['defaults']
    require(defaults['runtime_root'] == str(old) and defaults['user'] == data['user'] and defaults['hostname'] == data['hostname'], 'Model target differs')
    require(model['revision'] == data['model_revision'] and model['quantization'] == 'fp8'
            and model['server']['max_model_len'] == 262144 and model['server']['kv_cache_dtype'] == 'fp8'
            and model['server']['host'] == '127.0.0.1' and model['server']['port'] == 8000, 'Model/context/serving policy differs')
    require(read(release / 'source/models/kolibri-1.json') == model and read(release / 'source/config/defaults.json') == defaults, 'Release source/profile mismatch')
    sys.path.insert(0, str(release / 'source'))
    from modules.profiles import fingerprint
    from modules.calibration import validate_manifest
    require(fingerprint(current, release / 'source') == state['fingerprint'], 'Retained model source fingerprint differs')
    require(digest(release / 'server.service') == state['unit_sha256']
            and digest('/etc/systemd/system/ai-model-vllm-kolibri-1.service') == state['unit_sha256'], 'Model unit drift')
    calibration = model['kv_calibration']
    require(calibration['sha256'] == data['calibration_sha256'], 'Unapproved calibration')
    require(safe(calibration['manifest']).is_relative_to(old / 'build/dgx-spark-vllm/calibration'), 'Calibration escapes existing runtime')
    artifact = validate_manifest(calibration['manifest'], calibration['sha256'], model['revision'], verify_weights=False)
    require(artifact['scale_scope'] == 'kv-only-bf16-query', 'Expected V5 KV-only scales')
    live = unit('ai-model-vllm-kolibri-1.service', data['model_boot_state'])
    require(live['MainPID'].isdigit() and int(live['MainPID']) > 0, 'Missing model process')
    argv = (Path('/proc') / live['MainPID'] / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
    interpreter = process_argv(release, calibration, current, argv)
    require(command([str(release / 'venv/bin/python'), '-B', '-m', 'pip', 'freeze', '--all'], 120)
            == (release / 'requirements.lock').read_text().strip(), 'Existing model environment drift')
    models = json.loads(get('http://127.0.0.1:8000/v1/models'))['data']
    require(any(m['id'] == 'kolibri-1' and m.get('max_model_len') == 262144 for m in models), 'Live model/context identity differs')
    get('http://127.0.0.1:8000/health')
    installer = module(Path(data.get('controller_source', str(source))) / 'scripts/deploy/install-playwright-mcp.py')
    browser_profile = installer.load_profile(source)
    if data.get('browser_runtime'): browser_profile['runtime'] = data['browser_runtime']
    dependencies = installer.inventory(browser_profile)
    require(dependencies['browser_sha256'] == data['browser_sha256'] and dependencies['node_sha256'] == data['node_sha256']
            and dependencies['module_seal']['sha256'] == data['module_seal_sha256'], 'Current browser/Node/npm drift')
    base = Path(browser_profile['runtime']); legacy = read(base / 'manifest.json')
    require(legacy['owner'] == installer.OWNER and legacy['profile'] == browser_profile, 'Unowned MCP launcher/profile')
    require(legacy['dependencies']['node_sha256'] == dependencies['node_sha256'] and
            legacy['dependencies']['module_seal'] == dependencies['module_seal'], 'Legacy Node/npm seal drift')
    wanted = installer.desired(browser_profile, dependencies)
    mcp_files = {}
    for name in ('playwright-mcp', 'kilo.json'):
        content, mode = wanted[name]
        row = {'sha256': hashlib.sha256(content).hexdigest(), 'mode': mode}
        mcp_files[str(base / name)] = file_pin(base / name, row, False)
    # Old Brave hash is historical. A separately retained fresh proof qualifies
    # this exact new browser; never rewrite/relabel the historical manifest.
    historical = {'manifest': str(base / 'manifest.json'), 'sha256': digest(base / 'manifest.json'),
                  'browser_sha256': legacy['dependencies']['browser_sha256'],
                  'current_browser_differs': legacy['dependencies']['browser_sha256'] != dependencies['browser_sha256']}
    lock_path = old / 'tools/playwright/package-lock.json'
    require(digest(lock_path) == 'a80775921958f6a8be8fb02acf4395cb63863ee21f29558df03fb2797e525f4d', 'Unapproved npm lock')
    health = read('/etc/default/dgx-spark-health')
    require(health['owner'] == 'AI-Model/dgx-spark-health/v1' and health['model_unit'] == 'ai-model-vllm-kolibri-1.service'
            and health['vllm_url'] == 'http://127.0.0.1:8000' and health['port'] == 9817, 'Unknown health configuration')
    require(get('http://127.0.0.1:9817/healthz').strip() == b'ready', 'Health exporter not ready')
    return {'files': files, 'units': units, 'model': {'state': state, 'live': live, 'interpreter': interpreter,
            'profile_sha256': digest(release / 'profile.json'), 'requirements_sha256': digest(release / 'requirements.lock'),
            'calibration': calibration, 'layers': len(artifact['scales']), 'package': str(release / 'source')},
            'browser': {'profile': browser_profile, 'dependencies': dependencies, 'files': mcp_files,
                        'browser_version': command([browser_profile['browser'], '--version']),
                        'historical_manifest': historical, 'lock_sha256': digest(lock_path)},
            'health': {'configuration': health, 'legacy_runtime_preserved': True,
                       'model_python_matches_active_process': health['model_python'] == interpreter}}


# [J03] Coordinator-owned local browser proof; never model/worker qualification.
def browser_proof(data, output):
    installer = module(Path(data.get('controller_source', data['source_root'])) / 'scripts/deploy/install-playwright-mcp.py')
    output = safe(output); output.mkdir(parents=True, mode=0o700, exist_ok=False)
    result = installer.browser_probe(Path(data.get('browser_runtime', str(Path(data['existing_runtime']) / 'tools/playwright-tool'))), output)
    require(result['marker_observed'] and result['sandbox_page_namespace_and_seccomp'], 'Browser proof incomplete')
    result['scope'] = 'Coordinator MCP/browser compatibility only; not a model-issued call, C00 or egress qualification'
    write_new(output / 'proof.json', result)
    return {'path': str(output / 'proof.json'), 'sha256': digest(output / 'proof.json')}


def registry_path(runtime):
    return safe(Path(runtime) / 'tools/bootstrap/adoption.json')


def publish(stage, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.renameat2(-100, os.fsencode(stage), -100, os.fsencode(destination), 1)
    if result:
        raise OSError(ctypes.get_errno(), 'Atomic no-overwrite publication refused', str(destination))
    fd = os.open(destination.parent, os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


# [J04] No metadata publication until every required gate has passed.
def adopt(data, output):
    identity(data)
    destination = registry_path(data['destination_runtime']).parent
    if destination.exists():
        record = check(data['destination_runtime'], data=data)
        return {'status': 'UNCHANGED', 'registry': str(destination / 'adoption.json'), 'record': record}
    before = inspect(data)
    proof = browser_proof(data, output)
    after = inspect(data)
    require(before == after, 'Host changed during adoption proof; preserve evidence, no registration')
    destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with (destination.parent / '.adoption.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not destination.exists(), 'Adoption target appeared concurrently')
        stage = Path(tempfile.mkdtemp(prefix='.adoption-stage-', dir=destination.parent))
        record = {'owner': OWNER, 'schema_version': 1, 'profile': data, 'snapshot': after, 'browser_proof': proof,
                  'scope': 'Existing host adoption; no installs, model requests, restarts, boot changes or updater rollout'}
        selected = {'mode': 'adopted-existing-v1', 'package': after['model']['package'],
                    'calibration': 'on', 'fingerprint': after['model']['state']['fingerprint']}
        write_new(stage / 'selected-model.json', selected)
        write_new(stage / 'kilo.json', read(Path(data.get('browser_runtime', str(Path(data['existing_runtime']) / 'tools/playwright-tool'))) / 'kilo.json'))
        write_new(stage / 'adoption.json', record)
        require(inspect(data) == after, 'Host changed before publication; staging retained')
        publish(stage, destination)
    return {'status': 'ADOPTED_EXISTING', 'registry': str(destination / 'adoption.json'), 'record': record}


# [J05] Every subsequent on/inspect/verify rechecks all adopted identities.
def check(runtime, data=None):
    path = registry_path(runtime)
    require(path.is_file() and path.stat().st_uid == os.getuid() and stat.S_IMODE(path.stat().st_mode) == 0o600,
            'Missing/private adoption registry')
    record = read(path)
    require(record['owner'] == OWNER and record['schema_version'] == 1, 'Unknown adoption registry')
    pinned = record['profile']
    require(pinned['destination_runtime'] == str(runtime) and (data is None or data == pinned), 'Adoption target/profile changed')
    require(inspect(pinned) == record['snapshot'], 'Adopted installation diverged; preserve and review')
    proof = record['browser_proof']; require(digest(safe(proof['path'])) == proof['sha256'], 'Browser evidence changed')
    evidence = read(proof['path'])
    require(evidence['status'] == 'VERIFIED_MCP_AND_SANDBOXED_BROWSER' and evidence['new_model_requests'] == 0, 'Missing browser proof')
    registration_files(record, path)
    return record


def registration_files(record, path):
    pinned = record['profile']
    selected = read(path.parent / 'selected-model.json')
    expected = {'mode': 'adopted-existing-v1', 'package': record['snapshot']['model']['package'],
                'calibration': 'on', 'fingerprint': pinned['model_fingerprint']}
    require(selected == expected, 'Adopted model registration changed')
    require(read(path.parent / 'kilo.json') == read(Path(pinned.get('browser_runtime', str(Path(pinned['existing_runtime']) / 'tools/playwright-tool'))) / 'kilo.json'), 'Adopted MCP fragment changed')


def refresh_health(data, retention, output):
    """Explicit health-only handover after the owned health installer ran.

    Preserve the old registry and its browser/model evidence. Allow only the
    maintained native health executable and its explicit retention field to
    differ. No discovery/adoption of unrelated drift or service changes.
    """
    identity(data)
    require(str(retention) in ('disabled','forever','7','30','90','180','365'), 'Explicit health retention required')
    value = int(retention) if str(retention).isdigit() else str(retention)
    path = registry_path(data['destination_runtime'])
    safe(path); state = path.stat()
    require(state.st_uid == os.getuid() and stat.S_IMODE(state.st_mode) == 0o600, 'Untrusted adoption registry')
    before = path.read_bytes(); old = read(path)
    require(old['owner'] == OWNER and old['schema_version'] == 1, 'Unknown adoption registry')
    allowed = {'/etc/default/dgx-spark-health', '/usr/local/lib/dgx-spark-health/bootstrap.sh'}
    # Profile input may still describe the historical installation. All
    # unrelated pins/identities must remain exactly the previously adopted ones.
    a, b = copy.deepcopy(data), copy.deepcopy(old['profile'])
    for name in allowed:
        a['files'].pop(name); b['files'].pop(name)
    require(a == b, 'Health refresh cannot change unrelated profile pins')
    configuration = dict(old['snapshot']['health']['configuration'], retention_days=value)
    require(read('/etc/default/dgx-spark-health') == configuration, 'Health change exceeds explicit retention')
    source = Path(data['source_root']) / 'scripts/deploy/dgx-spark-health-bootstrap.sh'
    changes = {'/etc/default/dgx-spark-health': {'sha256': hashlib.sha256(encoded(configuration)).hexdigest(), 'mode': 0o644},
               '/usr/local/lib/dgx-spark-health/bootstrap.sh': {'sha256': digest(source), 'mode': 0o755}}
    updated = copy.deepcopy(old['profile']); updated['files'].update(changes)
    observed = inspect(updated)
    expected = copy.deepcopy(old['snapshot']); expected['files'].update(changes)
    expected['health']['configuration'] = configuration
    require(observed == expected, 'Unrelated live state changed; health refresh refused')
    registration_files(old, path)
    proof = old['browser_proof']
    require(digest(safe(proof['path'])) == proof['sha256'], 'Historical browser evidence changed')
    replacement = dict(old, profile=updated, snapshot=observed)
    if encoded(replacement) == before:
        check(data['destination_runtime'], updated)
        return {'status': 'UNCHANGED_HEALTH_ADOPTION', 'profile': updated}
    output = safe(output)
    with (path.parent.parent / '.adoption.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(path.read_bytes() == before, 'Adoption changed concurrently')
        output.mkdir(parents=True, mode=0o700, exist_ok=False)
        backup = output / 'adoption-before.json'
        with backup.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600); stream.write(before); stream.flush(); os.fsync(stream.fileno())
        require(digest(backup) == hashlib.sha256(before).hexdigest(), 'Adoption backup failed')
        candidate = path.with_name('.adoption-health-' + uuid.uuid4().hex)
        write_new(candidate, replacement)
        require(inspect(updated) == expected and path.read_bytes() == before, 'Host/registry changed before health refresh')
        os.replace(candidate, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    check(data['destination_runtime'], updated)
    return {'status': 'HEALTH_ADOPTION_REFRESHED', 'profile': updated, 'backup': str(backup),
            'previous_sha256': hashlib.sha256(before).hexdigest(), 'sha256': digest(path),
            'preserved_model_and_browser_proof': True}


def bootstrap(job):
    require(job['action'] == 'on', 'Adopted external services cannot be disabled by portable bootstrap')
    require(set(job['components']) <= COMPONENTS, 'Unknown adopted component')
    require(job.get('health_retention') is None, 'Adoption preserves existing health retention')
    require('kolibri' not in job['components'] or job['calibration'] == 'on', 'Existing V5 requires --calibration on')
    record = check(job['target']['runtime'])
    require(job['target']['user'] == record['profile']['user'] and job['target']['hostname'] == record['profile']['hostname'], 'Adoption account mismatch')
    return {'status': 'UNCHANGED_ADOPTED_EXISTING', 'components': job['components'], 'new_model_requests': 0,
            'host_mutations': 0, 'scope': record['scope']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'adopt', 'verify', 'refresh-health'])
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--retention', choices=['disabled','forever','7','30','90','180','365'])
    args = parser.parse_args(argv)
    try:
        data = profile(args.profile)
        if args.action == 'refresh-health':
            require(args.retention is not None and args.output is not None, 'Health refresh requires --retention and new --output')
            result = refresh_health(data, args.retention, args.output)
        elif args.retention is not None:
            raise RuntimeError('--retention is only supported by refresh-health')
        elif args.action == 'adopt':
            require(args.output is not None, 'Adoption requires a new private --output for browser proof')
            result = adopt(data, args.output)
        elif args.action == 'verify':
            record = check(data['destination_runtime'], data)
            result = {'status': 'ADOPTED_COMPONENTS_VERIFIED', 'registry': str(registry_path(data['destination_runtime'])),
                      'scope': record['scope'], 'live_model_canary_executed': False}
        else:
            result = {'status': 'ADOPTION_PREFLIGHT_PASSED', 'snapshot': inspect(data)}
        print(json.dumps(result, indent=2)); return 0
    except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': type(exc).__name__ + ': ' + str(exc)})); return 2


if __name__ == '__main__':
    sys.exit(main())
