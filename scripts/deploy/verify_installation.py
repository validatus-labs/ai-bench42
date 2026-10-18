"""Portable host inspection and live acceptance; never installs or repairs.

verify_installation.py
|-- inspect_host()  OS/GPU, packages, units and retained component identities
|-- verify()        model generation, browser/model tools and health observations
`-- cli()           bootstrap --inspect / --verify, optional private JSON receipt
"""
import json
from pathlib import Path
import platform
import subprocess
import sys
import uuid

import bootstrap_components as components

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from modelbench import common


def observe(argv, timeout=15):
    result = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=timeout,
                            env=components.environment(components.account(ROOT)))
    common.require(len(result.stdout) + len(result.stderr) <= 1024 * 1024, 'Oversized inspection output')
    return result.returncode, result.stdout.strip()


def retained_model(target):
    selected = common.read(Path(target['runtime']) / 'tools/bootstrap/selected-model.json')
    package = components.safe(Path(selected['package']))
    parent = Path(target['runtime']) / 'tools/bootstrap/model-source'
    common.require(package.parent == parent, 'Selected model source is outside the owned runtime')
    registry = common.read(package / 'bootstrap-source.json')
    actual = {str(p.relative_to(package)) for p in package.rglob('*') if p.is_file()}
    common.require(actual == set(registry['files']) | {'bootstrap-source.json'}, 'Retained model source entries differ')
    for name, checksum in registry['files'].items():
        common.require(common.digest(components.safe(package / name)) == checksum, 'Retained model source changed: ' + name)
    profile = common.read(package / 'models/kolibri-1.json')
    defaults = common.read(package / 'config/defaults.json')
    common.require(defaults['user'] == target['user'] and defaults['hostname'] == target['hostname']
                   and defaults['runtime_root'] == target['runtime'], 'Retained model belongs to another account/host/runtime')
    return package, selected, profile


def model_status(target):
    package, selected, profile = retained_model(target)
    code, output = observe(['/usr/bin/python3', '-B', str(package / 'vllmctl.py'), 'status', 'kolibri-1'])
    common.require(code == 0, 'Retained model status failed')
    status = json.loads(output)
    common.require(status.get('profile_matches') and status.get('deployment'), 'Model deployment/profile differs')
    common.require(status['deployment']['fingerprint'] == selected['fingerprint'], 'Selected/deployed fingerprints differ')
    return package, selected, profile, status


def inspect_host(target, selected):
    rows = []
    def check(name, function, missing='MISSING', existing=None):
        try:
            details = function()
            rows.append({'check': name, 'status': 'PASS', 'details': details})
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
            rows.append({'check': name, 'status': 'CONFLICT' if existing is not None and Path(existing).exists() else missing, 'reason': str(exc)})

    def host():
        release = platform.freedesktop_os_release()
        common.require(release.get('ID') == 'ubuntu' and release.get('VERSION_ID') == '24.04'
                       and platform.machine() == 'aarch64', 'Requires Ubuntu 24.04 ARM64 Spark OEM host')
        common.require(Path('/proc/1/comm').read_text().strip() == 'systemd', 'Requires native systemd')
        common.require(sys.version_info >= (3, 12), 'Requires Python 3.12+')
        code, gpu = observe(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'])
        common.require(code == 0 and 'GB10' in gpu, 'Expected usable NVIDIA GB10/OEM driver')
        return {'os': release['PRETTY_NAME'], 'gpu': gpu}
    check('platform', host, 'UNSUPPORTED')
    def packages():
        names = ['ca-certificates', 'curl', 'gnupg', 'python3-venv', 'rsync', 'bubblewrap', 'unattended-upgrades', 'nodejs']
        code, installed = observe(['dpkg-query', '-W', '-f=${binary:Package} ${Version} ${db:Status-Status}\n', *names])
        common.require(code == 0 and all(line.endswith(' installed') for line in installed.splitlines()), 'Native prerequisite packages are incomplete')
        code, node = observe(['/usr/bin/node', '--version'])
        common.require(code == 0 and int(node.lstrip('v').split('.')[0]) >= 22, 'Native Node 22+ is required by the bootstrap profile')
        return installed.splitlines()
    if set(selected) - {'health'}: check('native_packages', packages)
    if {'brave', 'playwright'} & set(selected):
        def browser():
            binary = Path('/opt/brave.com/brave/brave')
            common.require(binary.is_file(), 'Native Brave is missing')
            code, version = observe([str(binary), '--version'])
            common.require(code == 0, 'Brave version query failed')
            return {'version': version, 'sha256': common.digest(binary)}
        check('brave', browser)
    if 'kolibri' in selected:
        def model():
            package, current, profile, status = model_status(target)
            engine = Path(status['deployment']['release']) / 'venv/bin/python'
            common.require(engine.exists(), 'Model interpreter missing')
            code, installed = observe([str(engine), '-B', '-m', 'pip', 'freeze', '--all'], timeout=120)
            common.require(code == 0 and installed == (Path(status['deployment']['release']) / 'requirements.lock').read_text().strip(),
                           'Model dependency environment differs from its retained lock')
            return {'selected': current, 'model': profile['id'], 'revision': profile['revision'],
                    'context_tokens': profile['server']['max_model_len'],
                    'quantization': profile.get('quantization'), 'kv_cache_dtype': profile['server']['kv_cache_dtype'],
                    'service': status['service']}
        check('model', model, existing=Path(target['runtime']) / 'tools/bootstrap/selected-model.json')
    elif 'vllm' in selected:
        def engine():
            root = components.safe(Path(target['runtime']) / 'build/dgx-spark-vllm/engines')
            paths = sorted(root.glob('*/bootstrap-engine.json'))
            common.require(paths, 'No retained standalone engine')
            observations = []
            for path in paths:
                record = common.read(path)
                common.require(path.parent.name == record['fingerprint'][:20], 'Engine identity directory differs')
                python = Path(record['python'])
                components.safe(python.parent)
                common.require(python.parent.parent.parent == path.parent, 'Engine interpreter escapes retained environment')
                common.require(common.digest(python) == common.digest('/usr/bin/python3.12'), 'Unexpected engine interpreter bytes')
                code, installed = observe([str(python), '-B', '-m', 'pip', 'freeze', '--all'], timeout=120)
                lock = path.parent / 'requirements.lock'
                common.require(code == 0 and installed == lock.read_text().strip(), 'Standalone engine dependencies differ')
                observations.append({'fingerprint': record['fingerprint'], 'requirements_sha256': common.digest(lock)})
            return observations
        check('engine', engine)
    if 'playwright' in selected:
        def toolchain():
            import toolchain_lifecycle as lifecycle
            folder = components.safe(Path(target['runtime']) / 'tools/toolchains')
            pointer = lifecycle.active(folder)
            common.require(pointer is not None, 'No stable toolchain release')
            _, manifest = lifecycle.verify_release(folder, pointer['release'])
            # Read-only: verify evidence; no renewal or model request during inspect.
            try:
                lifecycle.qualification(folder, None, pointer['release'], enforce_age=False)
                qualification = 'QUALIFIED_HOST_TOOLCHAIN_NOT_C00'
            except (OSError, RuntimeError, ValueError, KeyError):
                qualification = 'NEEDS_REQUALIFICATION'
            return {'release': pointer['release'], 'selection': manifest['selection_id'], 'qualification': qualification}
        check('toolchain', toolchain, existing=Path(target['runtime']) / 'tools/toolchains/active.json')
        if rows[-1].get('details', {}).get('qualification') == 'NEEDS_REQUALIFICATION':
            rows[-1]['status'] = 'NEEDS_VERIFICATION'
    if 'health' in selected:
        def health():
            path = Path('/etc/default/dgx-spark-health')
            configuration = common.read(path)
            common.require(configuration.get('owner') == 'AI-Model/dgx-spark-health/v1', 'Unknown health ownership')
            common.require(configuration.get('runtime_root') == target['runtime'], 'Health configuration belongs to another runtime')
            return {'retention_days': configuration.get('retention_days', 30), 'interval': configuration['interval']}
        check('health_configuration', health)
    units = []
    if 'kolibri' in selected: units.append('ai-model-vllm-kolibri-1.service')
    if 'health' in selected: units += ['dgx-spark-health.timer', 'dgx-spark-health-exporter.service']
    if 'maintenance' in selected:
        units += ['ai-model-security-updates.timer', 'ai-model-weekly-updates.timer',
                  'modelbench-toolchain-update.path', 'modelbench-toolchain-update.timer']
    for name in units:
        def unit(name=name):
            path = components.safe(Path('/etc/systemd/system') / name)
            common.require(path.is_file() and path.stat().st_uid == 0 and not path.stat().st_mode & 0o022,
                           'Unit is not a root-owned managed regular file: ' + name)
            marker = ('# managed-by: dgx-spark-health-bootstrap' if name.startswith('dgx-spark-health') else
                      '# Managed by ModelBench toolchain updates v1' if name.startswith('modelbench-toolchain') else
                      '# Managed by AI-Model/dgx-spark-vllm/v1' if name.startswith('ai-model-vllm') else
                      '# Managed by ModelBench bootstrap maintenance v1')
            common.require(path.read_text().startswith(marker), 'Unit ownership marker differs: ' + name)
            code, fragment = observe(['systemctl', 'show', name, '-p', 'FragmentPath', '--value'])
            common.require(code == 0 and fragment == str(path), 'Unit fragment comes from another path')
            code, dropins = observe(['systemctl', 'show', name, '-p', 'DropInPaths', '--value'])
            common.require(code == 0 and not dropins, 'Unreviewed unit drop-ins are present')
            state = {}
            for action in ('is-active', 'is-enabled'):
                code, value = observe(['systemctl', action, name])
                common.require(code == 0, name + ': ' + action + '=' + value)
                state[action] = value
            return state
        check(name, unit, existing=Path('/etc/systemd/system') / name)
    statuses = {row['status'] for row in rows}
    return {'schema_version': 1, 'kind': 'HOST_INSTALLATION_INSPECTION', 'observed_at': common.timestamp(),
            'target': target, 'components': list(selected), 'checks': rows,
            'status': 'PASS' if statuses == {'PASS'} else 'NEEDS_VERIFICATION' if statuses <= {'PASS', 'NEEDS_VERIFICATION'} else 'BLOCKED',
            'live_canaries_executed': False}


def verify(target, selected, output):
    report = inspect_host(target, selected)
    report['kind'] = 'HOST_INSTALLATION_VERIFICATION'
    folder = common.private_directory(output)
    def canary(name, function):
        try:
            details = function()
            report['checks'].append({'check': name, 'status': 'PASS', 'details': details})
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
            report['checks'].append({'check': name, 'status': 'FAILED', 'reason': str(exc)})
        common.save(folder / 'verification.json', report)
    if report['status'] in ('PASS', 'NEEDS_VERIFICATION'):
        if 'kolibri' in selected:
            def model():
                package, _, _ = retained_model(target)
                # A separate controller process prevents module-cache/profile crossover.
                command = common.execute(['/usr/bin/python3', '-B', str(package / 'vllmctl.py'), 'verify', 'kolibri-1'],
                                         folder / 'model', 1800, env=components.environment(target))
                common.require(command.get('exit_code') == 0, 'Model verification failed; inspect private output.log')
                return {'command': 'model/command.json', 'elapsed_seconds': command['elapsed_seconds']}
            canary('model_generation', model)
        if 'playwright' in selected:
            def browser():
                import toolchain_lifecycle as lifecycle
                store = components.safe(Path(target['runtime']) / 'tools/toolchains')
                with lifecycle.locked(store):
                    current = lifecycle.active(store)
                    common.require(current, 'No stable toolchain')
                    proof = lifecycle.qualify(store, lifecycle.policy(ROOT / 'config/toolchain-updates.json'), current['release'])
                for row in report['checks']:
                    if row['check'] == 'toolchain':
                        row['status'] = 'PASS'; row['details']['qualification'] = proof['status']
                return {'release': current['release'], 'qualification': proof['status']}
            canary('browser_model_tool_roundtrip', browser)
        if 'health' in selected:
            def health():
                # Reuse exact ownership/config/boot/freshness checks; no probes execute.
                sys.path.insert(0, str(ROOT / 'scripts'))
                import bootstrap
                module = bootstrap.health_module(ROOT / 'scripts/deploy/dgx-spark-health-bootstrap.sh')
                config = module.settings()
                snapshot = module.read_report(config)
                _, stale = module.exposition(snapshot, config)
                common.require(not stale, 'Health snapshot is stale')
                _, ready = observe(['/usr/bin/curl', '--fail', '--silent', '--max-time', '5', 'http://127.0.0.1:9817/healthz'])
                common.require(ready == 'ready', 'Health HTTP exporter is not ready')
                problems = [{'check': row['check_id'], 'status': row['status']} for row in snapshot['checks'] if row['status'] != 0]
                return {'fresh': True, 'observations': snapshot['checks'], 'non_ok_observations': problems,
                        'all_observations_ok': not problems, 'retention_days': config.get('retention_days', 30)}
            canary('health_snapshot_and_http', health)
        report['live_canaries_executed'] = bool(set(selected) & {'kolibri', 'playwright', 'health'})
    report['status'] = 'PASS' if all(row['status'] == 'PASS' for row in report['checks']) else 'BLOCKED'
    report['scope'] = 'Host installation and functional canaries; coding-worker C00 and benchmark scores are separate'
    common.save(folder / 'verification.json', report)
    return report


def cli(args, selected):
    target = components.account(ROOT, args.runtime_root)
    receipt = None
    if args.verify or args.output:
        prefix = args.output or Path(target['runtime']) / 'tools/bootstrap/verification'
        common.private_directory(prefix)
        receipt = Path(prefix) / (('verify-' if args.verify else 'inspect-') + common.timestamp().replace(':', '-') + '-' + uuid.uuid4().hex[:8])
    if args.verify:
        result = verify(target, selected, receipt)
    else:
        result = inspect_host(target, selected)
        if args.output:
            common.save(common.private_directory(receipt) / 'inspection.json', result)
    if receipt: result['receipt_directory'] = str(receipt.absolute())
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'PASS' else 2
