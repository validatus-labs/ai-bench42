"""Root-only installation of the event hook and normal-user update service.

APT hook -> root-owned pending marker -> systemd.path -> unprivileged updater.
Only owned files are migrated; old bytes are backed up before replacement.
No npm or repository checkout code executes as root through the hook.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import time
import hashlib
import uuid
import stat

import bootstrap_components as common

PREFIX = Path('/usr/local/libexec/modelbench-toolchains')
STATE = Path('/var/lib/modelbench-toolchain-updates')
POLICY = Path('/etc/modelbench-toolchain-updates.json')
MARKER = '# Managed by ModelBench toolchain updates v1\n'
UNITS = ('modelbench-toolchain-update.service', 'modelbench-toolchain-update.path', 'modelbench-toolchain-update.timer')
SOURCES = ('scripts/toolchain.py', 'scripts/deploy/toolchain_lifecycle.py', 'scripts/deploy/toolchain_canary.py',
           'scripts/deploy/toolchain_browser_probe.cjs', 'scripts/deploy/bootstrap_components.py',
           'scripts/deploy/install-playwright-mcp.py', 'scripts/deploy/toolchain_native.py', 'config/toolchain-updates.json')


def submit(target, source, activate=False):
    """Explicit updater-only sudo boundary; retain a source-bound private job."""
    common.validate_target(target)
    if os.geteuid() == 0 or target['uid'] != os.geteuid():
        raise RuntimeError('Submit updater installation as the target normal account')
    source = common.safe(Path(source))
    folder = common.safe(Path(target['runtime']) / 'tools/updater-install')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.stat().st_uid != os.getuid() or folder.stat().st_mode & 0o077:
        raise RuntimeError('Expected private updater installation storage')
    names = (*SOURCES, 'config/bootstrap/98modelbench-toolchain-events')
    job = {'target': target, 'source': str(source), 'activate': activate,
           'files': {name: common.digest(common.safe(source / name)) for name in names}}
    path = folder / ('job-' + uuid.uuid4().hex + '.json')
    common.atomic(path, job)
    return subprocess.run(['sudo', '-n', '/usr/bin/python3', '-B', str(source / 'scripts/deploy/toolchain_native.py'),
                           '--job', str(path)], check=False).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0: raise RuntimeError('Root updater installer required')
    path = common.safe(args.job)
    state = path.stat()
    if not stat.S_ISREG(state.st_mode) or stat.S_IMODE(state.st_mode) != 0o600:
        raise RuntimeError('Expected a private regular installation job')
    job = json.loads(path.read_text())
    if set(job) != {'target', 'source', 'activate', 'files'} or type(job['activate']) is not bool:
        raise RuntimeError('Unexpected updater job fields')
    common.validate_target(job['target'])
    if state.st_uid != job['target']['uid']:
        raise RuntimeError('Updater job owner differs from target account')
    source = common.safe(Path(job['source']))
    if source != Path(__file__).resolve().parents[2] or str(source) != job['target']['project']:
        raise RuntimeError('Updater source identity differs')
    names = (*SOURCES, 'config/bootstrap/98modelbench-toolchain-events')
    if set(job['files']) != set(names) or any(common.digest(common.safe(source / name)) != job['files'][name] for name in names):
        raise RuntimeError('Updater source changed after submission')
    print(json.dumps(install(job['target'], source, activate=job['activate']), indent=2))
    return 0


def replace(path, data, mode=0o644):
    temporary = path.with_name(path.name + '.modelbench-' + str(time.time_ns()))
    with temporary.open('xb') as out:
        os.fchmod(out.fileno(), mode); out.write(data); out.flush(); os.fsync(out.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)


def reset_failed_units():
    # Fresh inactive units need not be loaded yet; reset-failed rejects them.
    # Querying loads/validates the owned unit and reset only an actual failure.
    for unit in UNITS:
        state = subprocess.run(['systemctl', 'show', unit, '-p', 'ActiveState', '--value'],
                               check=True, capture_output=True, text=True, timeout=30)
        if state.stdout.strip() == 'failed':
            subprocess.run(['systemctl', 'reset-failed', unit], check=True, timeout=30)


def recover():
    journal = common.safe(STATE / 'pending-install.json')
    if not journal.exists(): return
    data = json.loads(journal.read_text())
    registry = PREFIX / 'installed.json'
    current = json.loads(registry.read_text()) if registry.exists() else None
    if current not in (data['old_registry'], data['new_registry']):
        raise RuntimeError('Interrupted native install has divergent registry; preserve for review')
    complete = current == data['new_registry'] and all(Path(name).is_file() and common.digest(Path(name)) == value['sha256']
        for name, value in data['new_registry']['files'].items())
    if not complete:
        for item in data['prior']:
            path = common.safe(Path(item['path']))
            allowed = path.is_relative_to(PREFIX) or path == POLICY or path == Path('/etc/apt/apt.conf.d/98modelbench-toolchain-events') or path in {Path('/etc/systemd/system') / name for name in UNITS}
            if not allowed: raise RuntimeError('Invalid interrupted native target')
            accepted = {data['new_registry']['files'][str(path)]['sha256']}
            if item['existed']:
                backup = common.safe(Path(item['backup']))
                if not backup.is_relative_to(STATE) or common.digest(backup) != item['old_sha256']:
                    raise RuntimeError('Native recovery backup changed')
                accepted.add(item['old_sha256'])
            if path.exists() and common.digest(path) not in accepted:
                raise RuntimeError('Native file changed after interruption; preserve for review')
        for item in reversed(data['prior']):
            path = Path(item['path'])
            if item['existed']: replace(path, Path(item['backup']).read_bytes())
            elif path.exists(): path.unlink()
        if data['old_registry'] is None:
            if registry.exists(): registry.unlink()
        else: common.atomic(registry, data['old_registry'])
    journal.unlink()
    flag = PREFIX / 'transaction-pending'
    if flag.exists(): flag.unlink()


def install(target, source, activate=True):
    if os.geteuid() != 0:
        raise RuntimeError('Native update integration requires the root bootstrap supervisor')
    common.validate_target(target)
    for path in (PREFIX, STATE, POLICY): common.safe(path)
    PREFIX.mkdir(parents=True, exist_ok=True, mode=0o755)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in (PREFIX, STATE):
        if path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise RuntimeError('Native update directories must be root-owned and non-writable')
    # Only empty event-marker metadata is public. Backups/journals below this
    # directory remain mode 0700/0600 and cannot be read by the update account.
    STATE.chmod(0o755)
    recover()
    registry_path = common.safe(PREFIX / 'installed.json')
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else None
    if registry is None and any(p.is_file() or p.is_symlink() for p in PREFIX.rglob('*')):
        raise RuntimeError('Refuse an unmanaged nonempty native updater directory')
    PREFIX.chmod(0o755)
    identity = {'uid': target['uid'], 'runtime': target['runtime']}
    if registry and registry['target'] != identity:
        raise RuntimeError('Another account/runtime owns native update integration')
    if registry:
        for name, item in registry['files'].items():
            path = common.safe(Path(name))
            if (not path.is_file() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022
                    or common.digest(path) != item['sha256']):
                raise RuntimeError('Native update file drift; preserve for review: ' + name)
        flag = PREFIX / 'transaction-pending'
        if flag.exists(): flag.unlink()
    for unit in UNITS:
        if registry is None:
            loaded = subprocess.run(['systemctl', 'show', unit, '-p', 'LoadState', '--value'], capture_output=True, text=True)
            if loaded.stdout.strip() not in ('', 'not-found'):
                raise RuntimeError('Refuse unmanaged existing update unit: ' + unit)
        result = subprocess.run(['systemctl', 'show', unit, '-p', 'DropInPaths', '--value'], capture_output=True, text=True)
        if result.stdout.strip(): raise RuntimeError('Unexpected update service drop-ins')
    files = {PREFIX / name: ((source / name).read_bytes(), 0o644) for name in SOURCES}
    files[POLICY] = ((source / 'config/toolchain-updates.json').read_bytes(), 0o644)
    files[Path('/etc/apt/apt.conf.d/98modelbench-toolchain-events')] = ((source / 'config/bootstrap/98modelbench-toolchain-events').read_bytes(), 0o644)
    group = __import__('grp').getgrgid(target['gid']).gr_name
    if not re.fullmatch('[a-zA-Z0-9_-]+', target['user']) or not re.fullmatch('[a-zA-Z0-9_-]+', group):
        raise RuntimeError('Unsupported unit account/group name')
    command = '/usr/bin/python3 -B ' + str(PREFIX / 'scripts/toolchain.py')
    command += ' --runtime-root ' + target['runtime'] + ' --project-root ' + target['project']
    command += ' --policy ' + str(POLICY) + ' scheduled'
    service = MARKER + '''[Unit]
Description=Resolve and qualify a new ModelBench browser toolchain
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
'''
    service += 'User=' + target['user'] + '\nGroup=' + group + '\n'
    service += 'Environment=HOME=' + target['home'] + '\n'
    service += 'ExecCondition=+/usr/bin/test ! -e ' + str(STATE / 'pending-install.json') + '\n'
    service += 'ExecCondition=+/usr/bin/test ! -e ' + str(PREFIX / 'transaction-pending') + '\n'
    service += 'ExecStartPre=+/usr/bin/rm -f ' + str(STATE / 'pending') + '\nExecStart=' + command + '\n'
    service += '''TimeoutStartSec=6h
KillMode=control-group
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
'''
    writable = [target['runtime'], str(STATE)]
    temporary = json.loads((source / 'config/toolchain-updates.json').read_text()).get('browser_temporary_root')
    if temporary is not None:
        temporary_path = common.safe(Path(temporary))
        info = temporary_path.stat()
        if not temporary_path.is_dir() or info.st_uid != target['uid'] or stat.S_IMODE(info.st_mode) != 0o700 or any(c.isspace() for c in temporary):
            raise RuntimeError('Untrusted configured browser temporary root')
        writable.append(temporary)
    service += 'ReadWritePaths=' + ' '.join(writable) + '\nMemoryMax=6G\nTasksMax=1024\n'
    path_unit = MARKER + '[Unit]\nDescription=Queue toolchain checks after APT transactions\n[Path]\nPathExists=' + str(STATE / 'pending') + '\nUnit=' + UNITS[0] + '\n[Install]\nWantedBy=multi-user.target\n'
    timer = MARKER + '''[Unit]
Description=Catch up toolchain checks daily at 06:00 UTC
[Timer]
OnBootSec=5min
OnCalendar=*-*-* 06:00:00 UTC
Persistent=true
RandomizedDelaySec=0
Unit=modelbench-toolchain-update.service
[Install]
WantedBy=timers.target
'''
    for name, text in zip(UNITS, (service, path_unit, timer)):
        files[Path('/etc/systemd/system') / name] = (text.encode(), 0o644)
    changed = []
    backup = STATE / ('install-' + str(time.time_ns()))
    for path, (data, mode) in files.items():
        common.safe(path)
        if path.exists():
            if not registry or str(path) not in registry['files']:
                raise RuntimeError('Refuse unmanaged native update target: ' + str(path))
            if path.read_bytes() == data: continue
        changed.append(path)
    if changed:
        backup.mkdir(mode=0o700)
        if registry: common.atomic(backup / 'previous-registry.json', registry)
        prior = []
        for number, path in enumerate(changed):
            item = {'path': str(path), 'existed': path.exists()}
            if path.exists():
                snapshot = backup / (str(number) + '.before'); snapshot.write_bytes(path.read_bytes()); snapshot.chmod(0o600)
                item['backup'] = str(snapshot)
                item['old_sha256'] = common.digest(snapshot)
            prior.append(item)
        common.atomic(backup / 'prior.json', prior)
        desired_registry = {'owner': 'ModelBench/toolchain-updates/v1', 'target': identity,
            'files': {str(path): {'sha256': hashlib.sha256(data).hexdigest()} for path, (data, _) in files.items()}}
        common.atomic(STATE / 'pending-install.json', {'old_registry': registry, 'new_registry': desired_registry, 'prior': prior})
        (PREFIX / 'transaction-pending').touch(mode=0o600)
        if registry:
            for unit in UNITS:
                subprocess.run(['systemctl', 'stop', unit], check=True, timeout=180)
        try:
            for path in changed:
                data, mode = files[path]
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                if path.is_relative_to(PREFIX):
                    for parent in (path.parent, *path.parent.parents):
                        if parent == PREFIX: break
                        if not parent.is_relative_to(PREFIX): break
                        if parent.stat().st_uid != 0 or parent.stat().st_mode & 0o022:
                            raise RuntimeError('Unsafe native updater code directory')
                        parent.chmod(0o755)
                replace(path, data, mode)
            subprocess.run(['systemd-analyze', 'verify', *[str(Path('/etc/systemd/system') / name) for name in UNITS]], check=True, timeout=30)
            common.atomic(registry_path, desired_registry)
            (STATE / 'pending-install.json').unlink()
            (PREFIX / 'transaction-pending').unlink()
        except BaseException:
            recover()
            subprocess.run(['systemctl', 'daemon-reload'], check=False, timeout=30)
            if registry:
                for unit in UNITS[1:]: subprocess.run(['systemctl', 'start', unit], check=False, timeout=30)
            raise
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
    # The runtime exists before enabling User= jobs. The event hook performs
    # only touch; package-manager locks are never held by the updater.
    runtime = common.safe(Path(target['runtime']))
    if not runtime.exists():
        runtime.mkdir(parents=True, mode=0o700); os.chown(runtime, target['uid'], target['gid'])
    reset_failed_units()
    if activate:
        for unit in UNITS[1:]: subprocess.run(['systemctl', 'enable', '--now', unit], check=True, timeout=30)
    return {'status': 'UPDATED' if changed else 'UNCHANGED', 'files_changed': len(changed), 'activation_requested': activate}


if __name__ == '__main__':
    raise SystemExit(main())
