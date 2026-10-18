#!/usr/bin/env python3
"""Coordinator-owned worker lifecycle. Standard library only; no install or sudo.

tools/
|-- worker.py        prepare -> plan -> isolation probe -> canary / candidate
|-- worker_inner.py  in-namespace HTTP/MCP channel adapters and denial probes
`-- preflight.py     C00 gate; host-owned, fresh and input-bound evidence

The Linux bubblewrap root is an explicitly pinned, credential-free runtime
image. No host directories are shared except this trial's source tree. Only
the candidate package, added tests and build output are writable persistently.
"""
import argparse
import contextlib
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
OWNER = 'ModelBench/worker/v1'
INNER = Path(__file__).with_name('worker_inner.py')
POLICY = {
    'direct_network': 'deny', 'host_home': 'deny', 'git': 'deny',
    'service_workers': 'block', 'research': 'task-scoped-public-https-read-only',
    'browser_channel': 'mcp-json-lines-v1', 'inference_channel': 'http-over-unix-v1',
}
ARTIFACTS = {'kilo', 'brave', 'node', 'mcp_schema', 'dependency_lock',
             'browser_policy', 'agent_instructions'}
TOP_FILES = {'README.md', 'MANIFEST.md', 'AGENTS.md', 'TASKS.md', 'STATE.md', 'pyproject.toml'}
TOP_DIRS = {'melusense', 'tests', 'docs', 'config', 'tools'}


class Blocked(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise Blocked(message)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def pin(value):
    require(isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value), 'Missing/invalid SHA-256 pin')
    return value


def safe(path):
    path = Path(path).expanduser().absolute()
    require('..' not in path.parts, 'Traversal path refused')
    for parent in (path,) + tuple(path.parents):
        require(not parent.is_symlink(), 'Symlink in coordinator path refused')
    return path


def private(path):
    path = safe(path)
    st = path.stat()
    require(st.st_uid == os.getuid() and not st.st_mode & 0o077, 'Expected private coordinator-owned file/directory')
    return path


def write(path, value):
    path = safe(path)
    with path.open('xb') as out:
        os.fchmod(out.fileno(), 0o600)
        out.write(encoded(value)); out.flush(); os.fsync(out.fileno())


def publish(source, destination):
    """Linux atomic no-clobber directory publication, including concurrent runs."""
    libc = ctypes.CDLL(None, use_errno=True)
    operation = getattr(libc, 'renameat2', None)
    require(operation is not None, 'Atomic no-clobber renameat2 is required')
    operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    operation.restype = ctypes.c_int
    if operation(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def read(path, limit=2 * 1024 * 1024):
    path = safe(path)
    require(path.is_file() and path.stat().st_size <= limit, 'Missing/oversized JSON input')
    return json.loads(path.read_text())


def tree(path, limit=40000):
    """Hash names, bytes, modes and non-escaping links; never follow directory links."""
    path = safe(path)
    require(path.is_dir(), 'Missing root filesystem')
    rows = []
    for base, dirs, files in os.walk(path, followlinks=False):
        dirs.sort()
        for name in sorted(dirs + files):
            item = Path(base) / name
            relative = str(item.relative_to(path))
            info = item.lstat()
            require(not info.st_mode & 0o6000, 'Setuid/setgid runtime entry refused')
            if item.is_symlink():
                target = os.readlink(item)
                # Absolute rootfs links are valid inside the new root; validate
                # them lexically, without resolving against the coordinator host.
                parts = [] if target.startswith('/') else list(item.relative_to(path).parent.parts)
                for part in PurePosixPath(target).parts:
                    if part in ('/', '.'):
                        continue
                    if part == '..':
                        require(parts, 'Runtime link escapes root')
                        parts.pop()
                    else:
                        parts.append(part)
                rows.append([relative, 'link', target])
            elif stat.S_ISREG(info.st_mode):
                rows.append([relative, 'file', stat.S_IMODE(info.st_mode), digest(item)])
            elif stat.S_ISDIR(info.st_mode):
                rows.append([relative, 'dir', stat.S_IMODE(info.st_mode)])
            else:
                raise Blocked('Device, socket or special runtime entry refused')
            require(len(rows) <= limit, 'Rootfs inventory limit exceeded')
    require(rows, 'Empty root filesystem')
    return sha(encoded(rows))


def checked_artifact(item):
    require(isinstance(item, dict) and isinstance(item.get('path'), str), 'Artifact path is not configured')
    path = safe(item['path'])
    require(path.is_file() and digest(path) == pin(item.get('sha256')), 'Artifact missing or pin changed')
    return path


def validate_config(path):
    config = read(path)
    require(config.get('schema_version') == 1 and config.get('policy') == POLICY, 'Unsupported toolchain/policy')
    require(set(config.get('artifacts', {})) == ARTIFACTS, 'Incomplete toolchain artifact identities')
    checked_artifact(config['bwrap'])
    root = config.get('rootfs', {})
    require(isinstance(root.get('path'), str), 'Configure a credential-free runtime rootfs')
    require(tree(root['path']) == pin(root.get('tree_sha256')), 'Rootfs tree pin differs')
    require((safe(root['path']) / 'usr/bin/python3').exists(), 'Rootfs requires /usr/bin/python3')
    for artifact in config['artifacts'].values():
        checked_artifact(artifact)
    checked_artifact(config.get('qualification'))
    agent = config['agent']
    for key in ('argv', 'canary_argv'):
        require(isinstance(agent.get(key), list) and agent[key] and all(isinstance(x, str) and '\x00' not in x for x in agent[key]), 'Configure explicit candidate/canary argument arrays')
        require(agent[key][0].startswith('/'), 'Agent executable must be absolute inside rootfs')
        require(agent[key].count('{prompt}') == 1, 'Each agent command requires exactly one literal {prompt} argument')
    require(isinstance(agent.get('environment'), dict), 'Invalid agent environment')
    for key, value in agent['environment'].items():
        require(re.fullmatch('[A-Z][A-Z0-9_]*', key) and isinstance(value, str) and '\x00' not in value, 'Invalid environment entry')
        require(key.startswith(('KILO_', 'MODELBENCH_')), 'Only KILO_/MODELBENCH_ custom environment keys are permitted')
        require(not key.endswith(('_KEY', '_TOKEN', '_PASSWORD')), 'Credentials must stay outside worker configuration')
    destinations = set()
    for item in agent['config_files']:
        checked_artifact(item)
        destination = item.get('destination', '')
        require(destination.startswith('/home/worker/.config/kilo/') and '..' not in PurePosixPath(destination).parts, 'Config file must be inside private Kilo config')
        require(destination not in destinations, 'Duplicate configuration mount')
        destinations.add(destination)
    require(agent['config_files'], 'A pinned Kilo provider/MCP configuration is required')
    model = config['model']
    require(model.get('local_inference_only') is True and all(isinstance(model.get(k), str) and model[k] for k in ('id', 'revision')), 'Pin the exact local model identity')
    pin(model.get('tokenizer_sha256')); pin(model.get('backend_identity_sha256'))
    require(type(model.get('context_tokens')) is int and model['context_tokens'] > 0, 'Missing model context')
    limits = config['limits']
    for key in ('address_space_mib', 'file_size_mib', 'open_files', 'processes'):
        require(type(limits.get(key)) is int and limits[key] > 0, 'Invalid resource limit')
    require(set(config.get('channels', {})) == {'inference', 'browser'}, 'Two separate channels are required')
    for channel in config['channels'].values():
        require(isinstance(channel.get('socket'), str) and type(channel.get('peer_uid')) is int, 'Configure explicit broker sockets/UIDs')
        pin(channel.get('peer_executable_sha256')); pin(channel.get('peer_cmdline_sha256'))
    return config


def peer(channel):
    path = safe(channel['socket'])
    require(stat.S_ISSOCK(path.stat().st_mode), 'Expected a Unix channel socket')
    # Open a fresh connection: do not accept a stale PID in a receipt.
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3); connection.connect(str(path))
        pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        require(uid == channel['peer_uid'], 'Channel peer UID changed')
        require(digest(Path('/proc') / str(pid) / 'exe') == channel['peer_executable_sha256'], 'Channel executable changed')
        require(digest(Path('/proc') / str(pid) / 'cmdline') == channel['peer_cmdline_sha256'], 'Channel command identity changed')
    return {'pid': pid, 'uid': uid, 'executable_sha256': channel['peer_executable_sha256'],
            'cmdline_sha256': channel['peer_cmdline_sha256']}


def frozen_inventory(workspace):
    result = {}
    for path in sorted(workspace.rglob('*')):
        if path.is_symlink():
            raise Blocked('Workspace symlink refused')
        relative = path.relative_to(workspace)
        if not path.is_file() or relative.parts[0] == 'build':
            continue
        if relative.parts[0] == 'melusense':
            continue
        result[str(relative)] = digest(path)
    return result


def candidate_inventory(workspace):
    result = {}
    for directory in ('melusense', 'tests'):
        for path in sorted((workspace / directory).rglob('*')):
            require(not path.is_symlink(), 'Candidate symlink refused before launch')
            if path.is_file():
                result[str(path.relative_to(workspace))] = digest(path)
    return result


def prepare(args):
    require(os.getuid() != 0, 'Run as the normal coordinator, not root')
    require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}', args.run_id), 'Invalid Run-ID')
    require(re.fullmatch('[a-f0-9]{40}', args.source_sha), 'Record a full exact source commit SHA')
    archive = safe(args.package)
    require(digest(archive) == pin(args.package_sha256), 'Package checksum differs')
    config = safe(args.toolchain)
    # Preparation can precede provisioning. C00 validates all runtime pins later.
    require(read(config).get('schema_version') == 1, 'Invalid toolchain schema')
    approval = read(args.rights_record)
    require(approval.get('approved') is True and approval.get('usage') == 'internal-train-only'
            and approval.get('reviewer') and approval.get('legal_basis'), 'Missing completed TRAIN rights review')
    require(args.approve_worker_disclosure, 'Worker disclosure must be explicit')
    bundle = safe(args.train_bundle)
    require(digest(bundle) == pin(args.train_sha256), 'TRAIN checksum differs')
    require(bundle.stat().st_size <= 32 * 1024 * 1024, 'TRAIN bundle exceeds limit')
    rows = [json.loads(line) for line in bundle.read_text().splitlines() if line.strip()]
    budget_member = None
    with tarfile.open(archive, 'r:*') as tar:
        count = 0
        size = 0
        for member in tar:
            count += 1; size += member.size
            require(count <= 10000 and 0 <= size <= 128 * 1024 * 1024, 'Source archive exceeds limits')
            name = PurePosixPath(member.name)
            require(not name.is_absolute() and '..' not in name.parts and not any(x in {'.git', '.env'} for x in name.parts), 'Unsafe source archive path')
            require(member.isfile() or member.isdir(), 'Archive links/devices refused')
            if str(name) == 'config/budget.json':
                budget_member = json.load(tar.extractfile(member))
    require(budget_member is not None and args.seed in budget_member['seeds'], 'Missing budget or unsupported seed')
    require(approval.get('source_revision') == budget_member['hpi_train']['pinned_ref'], 'TRAIN rights revision differs')
    require(len(rows) == budget_member['hpi_train']['pair_count'] and len({r['case_id'] for r in rows}) == len(rows), 'TRAIN count/identities differ')
    for row in rows:
        require(isinstance(row.get('text'), str) and row.get('coordinate_basis') == 'annotated_text_codepoints', 'Invalid TRAIN row')
        for label in row['labels']:
            require(type(label['start']) is int and type(label['end']) is int and 0 <= label['start'] <= label['end'] <= len(row['text']), 'Invalid TRAIN coordinates')
    parent = safe(args.runs)
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    private(parent)
    destination = parent / args.run_id
    identity = {'owner': OWNER, 'run_id': args.run_id, 'source_sha': args.source_sha,
                'package_sha256': args.package_sha256, 'train_sha256': args.train_sha256,
                'toolchain_sha256': digest(config), 'seed': args.seed, 'model': args.model,
                'rights_record_sha256': digest(args.rights_record), 'worker_disclosure_approved': True,
                'launcher_sha256': digest(Path(__file__)), 'inner_sha256': digest(INNER)}
    if destination.exists():
        previous = read(private(destination / 'run.json'))
        require(previous['identity'] == identity, 'Run-ID exists with different inputs; choose a new Run-ID')
        verify_frozen(destination, previous)
        return {'status': 'REUSED_VERIFIED', 'run': str(destination)}
    stage = Path(tempfile.mkdtemp(prefix='.worker-stage-', dir=parent))
    try:
        workspace = stage / 'workspace'; workspace.mkdir(mode=0o700)
        with tarfile.open(archive, 'r:*') as tar:
            seen = set()
            for member in tar:
                name = PurePosixPath(member.name)
                if not name.parts or (name.parts[0] not in TOP_DIRS and str(name) not in TOP_FILES):
                    continue
                require(str(name) not in seen, 'Duplicate source archive entry')
                seen.add(str(name))
                output = workspace.joinpath(*name.parts)
                if member.isdir():
                    output.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    require(output.suffix not in {'.eml', '.mbox', '.ann', '.key', '.pem', '.safetensors', '.gguf'}, 'Private/large payload in source package')
                    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with output.open('xb') as out:
                        os.fchmod(out.fileno(), 0o600)
                        shutil.copyfileobj(tar.extractfile(member), out)
        for required in ('AGENTS.md', 'TASKS.md', 'docs/OFFLINE_AGENT_PROMPT.md', 'melusense/api.py', 'config/budget.json'):
            require((workspace / required).is_file(), 'Missing required task input: ' + required)
        (workspace / 'build').mkdir(mode=0o700)
        (workspace / 'tests').mkdir(exist_ok=True, mode=0o700)
        with (workspace / 'build/hpi-train-visible.jsonl').open('xb') as out:
            os.fchmod(out.fileno(), 0o600); out.write(bundle.read_bytes())
        record = {'identity': identity, 'fingerprint': sha(encoded(identity)),
                  'frozen': frozen_inventory(workspace), 'budget': budget_member,
                  'candidate_initial': candidate_inventory(workspace)}
        write(stage / 'run.json', record)
        # No overwrite on repeat or concurrent preparation.
        require(not destination.exists(), 'Run appeared concurrently')
        publish(stage, destination)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return {'status': 'PREPARED_NOT_READY', 'run': str(destination), 'fingerprint': record['fingerprint']}


def verify_frozen(run, record):
    workspace = run / 'workspace'
    for name, expected in record['frozen'].items():
        require(digest(safe(workspace / name)) == expected, 'Frozen task input changed: ' + name)
    require(digest(safe(workspace / 'build/hpi-train-visible.jsonl')) == record['identity']['train_sha256'], 'TRAIN bundle changed')
    require(record['identity']['launcher_sha256'] == digest(Path(__file__)) and record['identity']['inner_sha256'] == digest(INNER), 'Launcher changed; prepare a new Run-ID')


def load_run(run, toolchain):
    run = private(run)
    record = read(private(run / 'run.json'))
    require(record['identity']['owner'] == OWNER and record['fingerprint'] == sha(encoded(record['identity'])), 'Invalid run identity')
    require(digest(toolchain) == record['identity']['toolchain_sha256'], 'Toolchain changed; use a new Run-ID')
    verify_frozen(run, record)
    if not (run / 'candidate-start.json').exists():
        require(candidate_inventory(run / 'workspace') == record['candidate_initial'], 'Candidate differs from prepared package before C01; use a new Run-ID')
    config = validate_config(toolchain)
    require(config['model']['id'] == record['identity']['model'], 'Model differs from prepared run')
    require(config['model']['context_tokens'] >= record['budget']['context_tokens'], 'Model context is below common budget')
    return run, record, config


@contextlib.contextmanager
def locked(run):
    path = safe(run / 'coordinator.lock')
    with path.open('a') as out:
        os.fchmod(out.fileno(), 0o600)
        try:
            fcntl.flock(out, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked('This Run-ID is already active') from None
        yield


@contextlib.contextmanager
def toolchain_leases(config):
    """Protect managed release consumers from background model canaries.

    Derive stores from pinned artifact/rootfs paths, never from a worker report.
    All descriptors stay in this outer coordinator, not in the namespace.
    """
    stores = set()
    paths = [item['path'] for item in config['artifacts'].values()] + [config['rootfs']['path']]
    for name in paths:
        for parent in Path(name).parents:
            if parent.name != 'releases': continue
            root = safe(parent.parent)
            owner_file = root / 'owner.json'
            if not owner_file.exists(): continue
            owner = read(private(owner_file))
            if owner.get('owner') == 'ModelBench/toolchain-releases/v1':
                require(owner.get('uid') == os.getuid(), 'Toolchain lease belongs to another account')
                stores.add(root)
    with contextlib.ExitStack() as stack:
        for root in sorted(stores):
            for name in ('benchmark.lock', 'activity.lock'):
                out = stack.enter_context(safe(root / name).open('a'))
                os.fchmod(out.fileno(), 0o600)
                try: fcntl.flock(out, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError: raise Blocked('Toolchain update/qualification is active; retry this worker when idle') from None
        yield


def command(run, record, config, mode, challenge=''):
    workspace = run / 'workspace'
    args = [str(safe(config['bwrap']['path'])), '--unshare-user', '--unshare-pid', '--unshare-net',
            '--unshare-ipc', '--unshare-uts', '--unshare-cgroup', '--disable-userns',
            '--die-with-parent', '--new-session', '--cap-drop', 'ALL', '--clearenv',
            '--hostname', 'modelbench-worker', '--ro-bind', str(safe(config['rootfs']['path'])), '/',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--tmpfs', '/run',
            '--tmpfs', '/home', '--dir', '/home/worker', '--tmpfs', '/root',
            '--ro-bind', str(workspace), '/workspace',
            '--bind' if mode in ('agent', 'probe') else '--ro-bind', str(workspace / 'melusense'), '/workspace/melusense',
            '--bind' if mode in ('agent', 'probe') else '--ro-bind', str(workspace / 'tests'), '/workspace/tests',
            '--ro-bind' if mode == 'visible' else '--bind', str(workspace / 'build'), '/workspace/build',
            '--ro-bind', str(INNER), '/opt/modelbench/worker_inner.py',
            '--ro-bind', str(workspace / 'build/hpi-train-visible.jsonl'), '/workspace/build/hpi-train-visible.jsonl']
    for name in record['frozen']:
        if name.startswith('tests/'):
            args += ['--ro-bind', str(workspace / name), '/workspace/' + name]
    for item in config['agent']['config_files'] if mode != 'visible' else []:
        args += ['--ro-bind', str(safe(item['path'])), item['destination']]
    for name, channel in config['channels'].items() if mode != 'visible' else []:
        args += ['--ro-bind', str(safe(channel['socket'])), '/run/' + name + '.sock']
    environment = {'HOME': '/home/worker', 'USER': 'worker', 'LOGNAME': 'worker',
                   'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'TMPDIR': '/tmp',
                   'XDG_CONFIG_HOME': '/home/worker/.config', 'XDG_CACHE_HOME': '/tmp/cache',
                   'PYTHONDONTWRITEBYTECODE': '1', 'MODELBENCH_RUN_ID': record['identity']['run_id'],
                   'MODELBENCH_SEED': str(record['identity']['seed']), 'MODELBENCH_CHALLENGE': challenge,
                   'MODELBENCH_INFERENCE_BASE_URL': 'http://127.0.0.1:18080/v1',
                   'MODELBENCH_BROWSER_COMMAND': '/usr/bin/python3 /opt/modelbench/worker_inner.py mcp'}
    require(not set(environment) & set(config['agent']['environment']), 'Custom environment cannot override sandbox identity/transport')
    environment.update(config['agent']['environment'])
    for key, value in environment.items():
        args += ['--setenv', key, value]
    args += ['--chdir', '/workspace', '--', '/usr/bin/python3', '-B', '/opt/modelbench/worker_inner.py', mode]
    if mode in {'agent', 'canary'}:
        args += config['agent']['canary_argv' if mode == 'canary' else 'argv']
    return args


def restrictions(config, wall):
    def apply():
        os.umask(0o077)
        for name, value in ((resource.RLIMIT_AS, config['limits']['address_space_mib'] * 1024 * 1024),
                            (resource.RLIMIT_FSIZE, config['limits']['file_size_mib'] * 1024 * 1024),
                            (resource.RLIMIT_NOFILE, config['limits']['open_files']),
                            (resource.RLIMIT_NPROC, config['limits']['processes']),
                            (resource.RLIMIT_CPU, wall), (resource.RLIMIT_CORE, 0)):
            _, hard = resource.getrlimit(name)
            ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(name, (ceiling, ceiling))
    return apply


def execute(argv, config, wall, destination, input_data=None, stderr_destination=None):
    """Private bounded logs outside workspace; terminate the entire process group."""
    destination = safe(destination)
    with contextlib.ExitStack() as stack:
        log = stack.enter_context(destination.open('xb'))
        os.fchmod(log.fileno(), 0o600)
        errors = subprocess.STDOUT
        if stderr_destination is not None:
            errors = stack.enter_context(safe(stderr_destination).open('xb'))
            os.fchmod(errors.fileno(), 0o600)
        process = subprocess.Popen(argv, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                                   stdout=log, stderr=errors, close_fds=True, start_new_session=True,
                                   env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                                   preexec_fn=restrictions(config, wall))
        try:
            process.communicate(input_data, timeout=wall)
        except BaseException:
            with contextlib.suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    return process.returncode


def isolation_probe(run, record, config, folder, challenge):
    # Marker is generated by the coordinator, not read from any protected input.
    marker = folder / ('host-only-' + challenge)
    with marker.open('xb') as out:
        os.fchmod(out.fileno(), 0o600); out.write(challenge.encode())
    request = {'challenge': challenge, 'host_marker': str(marker), 'host_home': str(Path.home()),
               'host_home_identity': [Path.home().stat().st_dev, Path.home().stat().st_ino],
               'host_pid_namespace': os.readlink('/proc/self/ns/pid'),
               'host_net_namespace': os.readlink('/proc/self/ns/net'),
               'host_namespaces': {name: os.readlink('/proc/self/ns/' + name) for name in ('user', 'pid', 'net', 'mnt', 'ipc', 'uts', 'cgroup')},
               'expected_train_sha256': record['identity']['train_sha256'],
               'frozen_path': '/workspace/AGENTS.md'}
    log = folder / 'isolation.json'
    code = execute(command(run, record, config, 'probe'), config, 30, log, encoded(request))
    require(code == 0, 'Worker isolation probe failed (private log retained)')
    result = read(log)
    require(result.get('challenge') == challenge and result.get('status') == 'PASS', 'Invalid isolation probe response')
    expected = {'host_marker_denied', 'host_home_denied', 'pid_namespace', 'net_namespace',
                'direct_ipv4_denied', 'direct_ipv6_denied', 'frozen_readonly', 'candidate_writable',
                'train_readonly', 'no_git', 'no_inherited_secrets'}
    expected.update({'namespace_set', 'capabilities_dropped'})
    require(set(result.get('checks', {})) == expected and all(v is True for v in result['checks'].values()), 'Incomplete isolation proof')
    return {'sha256': digest(log), 'checks': result['checks']}


def freeze_candidate(run, record):
    """Publish a coordinator-owned snapshot before any independent assessment."""
    require((run / 'candidate-start.json').is_file(), 'Candidate was not started')
    verify_frozen(run, record)
    files = candidate_inventory(run / 'workspace')
    receipt = run / 'frozen-candidate.json'
    archive = run / 'frozen-candidate.tar'
    if receipt.exists():
        previous = read(private(receipt))
        require(previous['files'] == files and digest(archive) == previous['archive_sha256'], 'Frozen candidate changed')
        return previous
    require(not archive.exists(), 'Incomplete prior freeze; retain it and use a new run')
    with archive.open('xb') as output:
        os.fchmod(output.fileno(), 0o600)
        with tarfile.open(fileobj=output, mode='w') as tar:
            for name, checksum in files.items():
                path = safe(run / 'workspace' / name)
                require(digest(path) == checksum, 'Candidate changed during freeze')
                member = tar.gettarinfo(str(path), arcname=name)
                member.uid = member.gid = member.mtime = 0
                member.uname = member.gname = ''; member.mode = 0o600
                with path.open('rb') as stream: tar.addfile(member, stream)
    require(candidate_inventory(run / 'workspace') == files, 'Candidate changed during freeze')
    result = {'schema_version': 1, 'fingerprint': record['fingerprint'], 'files': files,
              'candidate_tree_sha256': sha(encoded(files)), 'archive_sha256': digest(archive)}
    write(receipt, result)
    return result


def verify_candidate(run, record, config):
    frozen = freeze_candidate(run, record)
    destination = run / 'visible-result.json'
    if destination.exists():
        result = read(private(destination))
        require(result['candidate_tree_sha256'] == frozen['candidate_tree_sha256'], 'Visible assessment belongs to another candidate')
        for key in ('stdout', 'stderr'):
            require(digest(run / result[key]['path']) == result[key]['sha256'], 'Assessment log changed')
        return result
    folder = run / ('visible-' + str(time.time_ns())); folder.mkdir(mode=0o700)
    code = execute(command(run, record, config, 'visible'), config, 300,
                   folder / 'result.json', stderr_destination=folder / 'tests.log')
    assessment = read(folder / 'result.json')
    require(assessment.get('schema_version') == 1 and assessment.get('status') in ('PASS', 'FAILED'), 'Invalid visible assessment')
    require((code == 0) == (assessment['status'] == 'PASS'), 'Test status/exit mismatch')
    require(candidate_inventory(run / 'workspace') == frozen['files'], 'Candidate changed during assessment')
    verify_frozen(run, record)
    result = dict(assessment, exit_code=code, candidate_tree_sha256=frozen['candidate_tree_sha256'])
    for key, path in [('stdout', folder / 'result.json'), ('stderr', folder / 'tests.log')]:
        result[key] = {'path': str(path.relative_to(run)), 'sha256': digest(path)}
    write(destination, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    p = actions.add_parser('prepare')
    for option in ('run-id', 'source-sha', 'package-sha256', 'train-sha256', 'model'):
        p.add_argument('--' + option, required=True)
    for option in ('package', 'train-bundle', 'rights-record', 'toolchain'):
        p.add_argument('--' + option, required=True, type=Path)
    p.add_argument('--approve-worker-disclosure', action='store_true')
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--runs', type=Path, default=ROOT / 'build/runs')
    for name in ('plan', 'probe', 'run', 'freeze', 'verify-candidate'):
        p = actions.add_parser(name); p.add_argument('--run', required=True, type=Path)
        p.add_argument('--toolchain', required=True, type=Path)
    p = actions.add_parser('hash-rootfs'); p.add_argument('path', type=Path)
    p = actions.add_parser('check-toolchain'); p.add_argument('--toolchain', type=Path, required=True)
    args = parser.parse_args()
    try:
        require(os.getuid() != 0, 'Run as the normal coordinator, not root')
        if args.action == 'hash-rootfs':
            print(json.dumps({'tree_sha256': tree(args.path)})); return 0
        if args.action == 'check-toolchain':
            validate_config(args.toolchain)
            print(json.dumps({'status': 'PINS_VALID_NOT_READY', 'toolchain_sha256': digest(args.toolchain)})); return 0
        if args.action == 'prepare':
            print(json.dumps(prepare(args))); return 0
        run, record, config = load_run(args.run, args.toolchain)
        if args.action == 'plan':
            print(json.dumps({'status': 'PLAN_ONLY', 'fingerprint': record['fingerprint'],
                              'argv': command(run, record, config, 'agent')}, indent=2)); return 0
        with locked(run), toolchain_leases(config):
            if args.action in ('freeze', 'verify-candidate'):
                result = freeze_candidate(run, record) if args.action == 'freeze' else verify_candidate(run, record, config)
                print(json.dumps(result))
                return 0 if args.action == 'freeze' or result['status'] == 'PASS' else 1
            folder = run / ('probe-' + str(time.time_ns()))
            folder.mkdir(mode=0o700)
            channels = {name: peer(value) for name, value in config['channels'].items()}
            challenge = os.urandom(16).hex()
            proof = isolation_probe(run, record, config, folder, challenge)
            if args.action == 'probe':
                print(json.dumps({'status': 'ISOLATION_ONLY_NOT_READY', 'proof': proof, 'channels': channels})); return 0
            receipt = read(private(run / 'readiness.json'))
            import preflight
            preflight.verify_ready(receipt, record, run, config)
            # A candidate is started once. Repetition reports state, never reruns
            # a failed/partial/finished candidate under the same identity.
            launch = run / 'candidate-start.json'
            require(not launch.exists(), 'Candidate already started; inspect its retained receipt instead of rerunning')
            write(launch, {'fingerprint': record['fingerprint'], 'started': time.time(), 'isolation_sha256': proof['sha256']})
            code = execute(command(run, record, config, 'agent'), config, record['budget']['wall_seconds'], run / 'candidate.log')
            verify_frozen(run, record)
            write(run / 'candidate-result.json', {'status': 'EXITED', 'exit_code': code, 'fingerprint': record['fingerprint']})
            print(json.dumps({'status': 'EXITED', 'exit_code': code, 'run': str(run)}))
            return code
    except (OSError, ValueError, KeyError, TypeError, Blocked, tarfile.TarError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
