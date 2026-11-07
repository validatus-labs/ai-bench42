"""Versioned npm toolchains using native Brave --sandbox; no outer namespace helper.

toolchain_lifecycle.py
|-- resolve()            native hashes + npm tags -> exact selection
|-- prepare()            npm lock/cache -> separate retained modules
|-- qualify()            native browser sandbox/MCP + real model/tool round-trip
|-- promote()/rollback() atomic stable pointer; preserve previous releases
`-- export/import       bounded, checksum-verified offline recovery bundle

Native Brave/Node remain APT-maintained and hash-bound. This is not worker isolation.
"""
import contextlib
import datetime
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request
import uuid

import bootstrap_components as common

OWNER = 'ModelBench/toolchain-releases/v1'
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ID = re.compile('[a-f0-9]{64}')


class Deferred(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def read(path, limit=8 * 1024 * 1024):
    path = common.safe(Path(path))
    require(path.is_file() and path.stat().st_size <= limit, 'Missing/oversized state: ' + str(path))
    return json.loads(path.read_text())


def atomic(path, value):
    common.atomic(path, value)


def private(path):
    path = common.safe(Path(path))
    require(path.stat().st_uid == os.getuid() and not path.stat().st_mode & 0o077, 'Expected private account-owned storage')
    return path


def policy(path):
    data = read(path)
    require(data['schema_version'] == 1 and data['registry'] == 'https://registry.npmjs.org/', 'Unsupported update policy/registry')
    require(data['scope'] == 'HOST_BROWSER_TOOLCHAIN_NOT_C00_OR_MODEL_ENGINE_UPGRADE', 'Unsupported update scope')
    require(data.get('runtime_backend') == 'native-brave-sandbox/v1', 'Explicit native Brave sandbox backend required')
    require({'brave-browser', 'nodejs', 'ca-certificates'} <= set(data['apt_roots']), 'Missing browser/runtime roots')
    require('@playwright/mcp' in data['npm_dist_tags'], 'Playwright MCP must be selected')
    for name in data['apt_roots']:
        require(re.fullmatch('[a-z0-9][a-z0-9+.-]*', name), 'Invalid APT package')
    for name, tag in data['npm_dist_tags'].items():
        require(re.fullmatch('(@[a-z0-9_-]+/)?[a-z0-9_.-]+', name) and re.fullmatch('[a-zA-Z0-9_.-]+', tag), 'Invalid npm tag selector')
    for name in ('minimum_node_major', 'minimum_free_gib', 'check_interval_seconds', 'qualification_max_age_seconds'):
        require(type(data[name]) is int and data[name] > 0, 'Invalid policy limit')
    require(type(data['automatic_promotion']) is bool, 'Invalid promotion policy')
    model_endpoint(data['model_canary'])
    return data


def model_endpoint(model):
    url = urllib.parse.urlsplit(model['base_url'])
    require(url.scheme in {'http', 'https'} and url.path == '/v1' and not url.query and not url.fragment
            and not url.username and not url.password and isinstance(model['model'], str) and model['model'], 'Invalid local canary endpoint')
    host = url.hostname
    if host != 'localhost':
        address = ipaddress.ip_address(host)
        require((address.is_private or address.is_loopback) and not address.is_link_local and not address.is_multicast, 'Canary inference must stay on the explicit local/private endpoint')
    require(type(model['timeout_seconds']) is int and 1 <= model['timeout_seconds'] <= 1800, 'Invalid canary timeout')
    return url


@contextlib.contextmanager
def external_benchmark(data):
    """Respect an existing host benchmark coordinator, in addition to store leases."""
    value = data.get('external_benchmark_lock')
    if value is None:
        yield
        return
    path = common.safe(Path(value))
    require(path.is_file() and path.stat().st_uid == os.getuid(), 'Missing/untrusted external benchmark lock')
    with path.open('r') as stream:
        try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise Deferred('Existing host benchmark is active; no canary inference') from None
        yield


def host(data):
    release = platform.freedesktop_os_release(); expected = data['platform']
    require(release.get('ID') == expected['distribution'] and release.get('VERSION_ID') == expected['version'], 'Wrong update target OS')
    arch = output(['dpkg', '--print-architecture']).strip()
    require(arch == expected['architecture'], 'Wrong update target architecture')
    return {'distribution': release['ID'], 'version': release['VERSION_ID'], 'architecture': arch}


def native_identity(data):
    paths = {'browser': Path('/opt/brave.com/brave/brave'), 'node': Path('/usr/bin/node')}
    result = {'backend': 'native-brave-sandbox/v1'}
    for name, path in paths.items():
        common.safe(path); st = path.stat()
        require(path.is_file() and st.st_uid == 0 and not st.st_mode & 0o022 and os.access(path, os.X_OK), 'Untrusted native ' + name)
        result[name] = {'path': str(path), 'sha256': common.digest(path), 'version': output([path, '--version']).strip()}
    version = result['node']['version']
    require(re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', version) and int(version[1:].split('.')[0]) >= data['minimum_node_major'], 'Incompatible native Node')
    choices = ('/usr/lib/node_modules/npm/bin/npm-cli.js', '/usr/share/nodejs/npm/bin/npm-cli.js')
    npm = next((Path(value) for value in choices if Path(value).is_file()), None)
    require(npm is not None, 'Native Node package must supply npm')
    common.safe(npm); st = npm.stat()
    require(st.st_uid == 0 and not st.st_mode & 0o022, 'Untrusted native npm')
    result['npm_cli'] = str(npm)
    result['npm_tree_sha256'] = sha(encoded(inventory(npm.parents[1])))
    packages = output(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${Architecture}\n'])
    result['installed_packages_sha256'] = sha(packages.encode())
    roots = output(['dpkg-query', '-W', '-f=${Package} ${Version}\n', *data['apt_roots']])
    result['apt_roots'] = dict(line.split(' ', 1) for line in roots.splitlines())
    return result




def environment(home, browser_tmp=None):
    home = Path(home)
    result = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1',
            'npm_config_update_notifier': 'false', 'npm_config_audit': 'false', 'npm_config_fund': 'false',
            'npm_config_userconfig': '/dev/null'}
    if home.is_dir():
        for role in ('user', 'global'):
            config = common.safe(home / ('npm-empty-' + role + '.conf'))
            if config.exists():
                require(config.is_file() and config.stat().st_uid == os.getuid() and config.stat().st_size == 0 and stat.S_IMODE(config.stat().st_mode) == 0o600, 'Unexpected npm empty configuration')
            else:
                with config.open('xb') as stream: os.fchmod(stream.fileno(), 0o600)
            result['npm_config_' + role + 'config'] = str(config)
    if browser_tmp is not None:
        temp = common.safe(Path(browser_tmp)); st = temp.stat()
        require(temp.is_dir() and st.st_uid == os.getuid() and stat.S_IMODE(st.st_mode) == 0o700, 'Untrusted browser temporary root')
        require(len(str(temp)) <= 72, 'Browser temporary path exceeds Unix-socket budget')
        result['TMPDIR'] = str(temp)
    return result


def output(argv, cwd=None, env=None, timeout=120, log=None):
    result = subprocess.run([str(x) for x in argv], cwd=cwd, env=env or environment('/nonexistent'),
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, text=True)
    require(len(result.stdout) + len(result.stderr) <= 16 * 1024 * 1024, 'Command output limit exceeded')
    if log is not None:
        with Path(log).open('x') as stream:
            os.fchmod(stream.fileno(), 0o600); stream.write(result.stdout); stream.write(result.stderr)
    require(result.returncode == 0, 'Command failed: ' + Path(str(argv[0])).name + ' (private log retained when available)')
    return result.stdout


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def npm_version(name, tag):
    url = 'https://registry.npmjs.org/' + urllib.parse.quote(name, safe='') + '/' + urllib.parse.quote(tag, safe='')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=30) as response:
        body = response.read(2 * 1024 * 1024 + 1)
    require(len(body) <= 2 * 1024 * 1024, 'Oversized registry response')
    metadata = json.loads(body)
    version = metadata['version']
    require(metadata['name'] == name and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?', version), 'Invalid registry package identity')
    require(tag != 'latest' or '-' not in version, 'The latest tag points to a prerelease; select an explicit reviewed tag')
    return version


def wait_for_apt(timeout=1800):
    """APT's fcntl locks and flock are different; observe actual kernel locks.

    Waiting happens in the normal-user service, never inside the APT hook.
    No root lock file is opened or changed by this process.
    """
    deadline = time.monotonic() + timeout
    while True:
        targets = set()
        for name in ('/var/lib/apt/lists/lock', '/var/lib/dpkg/lock', '/var/lib/dpkg/lock-frontend'):
            p = Path(name)
            if p.exists():
                st = p.stat(); targets.add((st.st_dev, st.st_ino))
        busy = False
        for line in Path('/proc/locks').read_text().splitlines():
            for token in line.split():
                match = re.fullmatch(r'([a-fA-F0-9]+):([a-fA-F0-9]+):([0-9]+)', token)
                if match and (os.makedev(int(match[1], 16), int(match[2], 16)), int(match[3])) in targets:
                    busy = True
        if not busy: return
        require(time.monotonic() < deadline, 'APT/dpkg is still busy; leave the active release unchanged')
        time.sleep(5)


def apt_epoch():
    path = Path('/var/lib/modelbench-toolchain-updates/last-package-event')
    return path.stat().st_mtime_ns if path.exists() else 0


def store(target):
    root = common.safe(Path(target['runtime']) / 'tools/toolchains')
    root.mkdir(parents=True, exist_ok=True, mode=0o700); private(root)
    for name in ('plans', 'releases', 'attempts', 'resolvers', 'qualifications', 'objects', 'events', 'sessions'):
        path = root / name; path.mkdir(exist_ok=True, mode=0o700); private(path)
    identity = {'owner': OWNER, 'uid': target['uid'], 'runtime': target['runtime']}
    marker = root / 'owner.json'
    if marker.exists(): require(read(marker) == identity, 'Different account/runtime owns this release store')
    else: atomic(marker, identity)
    return root


@contextlib.contextmanager
def locked(root, wait_seconds=0):
    path = common.safe(root / 'controller.lock')
    with path.open('a') as stream:
        os.fchmod(stream.fileno(), 0o600)
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise
                time.sleep(1)
        yield


@contextlib.contextmanager
def activity(root, exclusive=False, kind='activity'):
    require(kind in ('activity', 'benchmark'), 'Unknown workload lease')
    path = common.safe(root / (kind + '.lock'))
    with path.open('a') as stream:
        os.fchmod(stream.fileno(), 0o600)
        try:
            fcntl.flock(stream, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Deferred('Active ' + kind + ' lease: preserve the current workload and retry when idle') from None
        yield


def controller_identity():
    names = ('scripts/toolchain.py', 'scripts/deploy/toolchain_lifecycle.py',
             'scripts/deploy/toolchain_canary.py', 'scripts/deploy/toolchain_browser_probe.cjs',
             'scripts/deploy/bootstrap_components.py', 'scripts/deploy/install-playwright-mcp.py')
    return {name: common.digest(ROOT / name) for name in names}


def guard_controller():
    prefix = Path('/usr/local/libexec/modelbench-toolchains')
    if not prefix.exists(): return
    require(not (prefix / 'transaction-pending').exists() and not Path('/var/lib/modelbench-toolchain-updates/pending-install.json').exists(),
            'Native updater migration is pending; reapply --maintenance --on')
    expected = controller_identity()
    require(all((prefix / name).is_file() and common.digest(prefix / name) == value for name, value in expected.items()),
            'Checkout and installed updater versions differ; reapply --maintenance --on before using this controller')


def resolve(root, data):
    platform_id = host(data); guard_controller(); wait_for_apt()
    native = native_identity(data)
    npm = {name: npm_version(name, tag) for name, tag in sorted(data['npm_dist_tags'].items())}
    work = Path(tempfile.mkdtemp(prefix='resolve-native-', dir=root / 'attempts'))
    (work / 'npm').mkdir(mode=0o700)
    atomic(work / 'npm/package.json', {'private': True, 'dependencies': npm})
    env = environment(work); env['npm_config_cache'] = str(work / 'npm-cache')
    output([native['node']['path'], native['npm_cli'], '--prefix', work / 'npm',
            'install', '--package-lock-only', '--ignore-scripts', '--no-audit', '--no-fund',
            '--registry=' + data['registry']], cwd=work, env=env, timeout=1800, log=work / 'resolve.log')
    lock = read(work / 'npm/package-lock.json', 16 * 1024 * 1024); validate_npm_lock(lock, data)
    require(native_identity(data) == native, 'Native runtime changed during npm resolution')
    selection = {'schema_version': 1, 'backend': native['backend'], 'platform': platform_id,
                 'native': native, 'apt': native['apt_roots'], 'npm': npm, 'npm_lock': lock,
                 'policy_sha256': sha(encoded(data)), 'controller': controller_identity()}
    selection_id = sha(encoded(selection)); file = root / 'plans' / (selection_id + '.json')
    if file.exists(): require(read(file) == selection, 'Selection identity collision')
    else: atomic(file, selection)
    atomic(root / 'last-check.json', {'checked_unix': time.time(), 'selection': selection_id})
    return selection_id, selection


def inventory(root):
    rows = []
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        for name in sorted(dirs + files):
            item = Path(base) / name; st = item.lstat(); relative = str(item.relative_to(root))
            require(not st.st_mode & 0o6000, 'setuid/setgid entry in release')
            if item.is_symlink():
                link = os.readlink(item)
                parts = [] if link.startswith('/') else list(item.relative_to(root).parent.parts)
                for part in PurePosixPath(link).parts:
                    if part in ('/', '.'): continue
                    if part == '..':
                        require(parts, 'Release link escapes root'); parts.pop()
                    else: parts.append(part)
                rows.append([relative, 'link', link])
            elif stat.S_ISDIR(st.st_mode): rows.append([relative, 'dir', stat.S_IMODE(st.st_mode)])
            elif stat.S_ISREG(st.st_mode): rows.append([relative, 'file', stat.S_IMODE(st.st_mode), common.digest(item)])
            else: raise RuntimeError('Special file in release')
            require(len(rows) <= 200000, 'Release inventory exceeds limit')
    return rows


def validate_npm_lock(lock, data):
    require(lock.get('lockfileVersion') in (2, 3) and isinstance(lock.get('packages'), dict), 'Unsupported npm lock format')
    for name, item in lock['packages'].items():
        if name:
            require(item.get('resolved', '').startswith(data['registry']) and item.get('integrity', '').startswith('sha512-'), 'Non-registry dependency or missing npm integrity')




def command_args(release, work, argv, acquisition=False, probe=False):
    """Host launcher with native Brave --sandbox; not a worker OS sandbox."""
    release = common.safe(Path(release)); work = common.safe(Path(work))
    result = []
    for value in argv:
        value = str(value)
        if value == '/checks/browser.cjs': value = str(HERE / 'toolchain_browser_probe.cjs')
        elif value.startswith('/npm/'): value = str(release / value.lstrip('/'))
        elif value.startswith('/work/'): value = str(work / value[len('/work/'):])
        elif value == '/tmp/output': value = str(work / 'output')
        result.append(value)
    require(result and result[0] == '/usr/bin/node', 'Only the native Node launcher is supported')
    if probe: result.append(str(release / 'npm'))
    return result






def prepare(root, data, selection_id, selection):
    require(controller_identity() == selection['controller'], 'Controller changed since resolution')
    require(selection['native'] == native_identity(data), 'Native runtime changed since resolution')
    require(shutil.disk_usage(root).free >= data['minimum_free_gib'] * 1024 ** 3, 'Insufficient retained-toolchain storage')
    index = root / 'plans' / (selection_id + '.release.json')
    if index.exists():
        release_id = read(index)['release']; verify_release(root, release_id); return release_id
    attempt = Path(tempfile.mkdtemp(prefix='prepare-native-', dir=root / 'attempts'))
    try:
        npm = attempt / 'npm'; npm.mkdir(mode=0o700)
        atomic(npm / 'package.json', {'private': True, 'dependencies': selection['npm']})
        atomic(npm / 'package-lock.json', selection['npm_lock'])
        previous = active(root)
        if previous:
            cache = root / 'releases' / previous['release'] / 'npm-cache'
            if cache.exists(): shutil.copytree(cache, attempt / 'npm-cache', symlinks=True)
        env = environment(attempt); env['npm_config_cache'] = str(attempt / 'npm-cache')
        output(['/usr/bin/node', selection['native']['npm_cli'], '--prefix', npm, 'ci',
                '--ignore-scripts', '--no-audit', '--no-fund', '--registry=' + data['registry']],
                cwd=attempt, env=env, timeout=1800, log=attempt / 'npm-ci.log')
        lock = read(npm / 'package-lock.json', 16 * 1024 * 1024); validate_npm_lock(lock, data)
        require(lock == selection['npm_lock'], 'npm changed the exact resolved graph')
        require((npm / 'node_modules/@playwright/mcp/cli.js').is_file(), 'MCP CLI missing')
        cache = attempt / 'npm-cache'
        for item in tuple(cache.iterdir()) if cache.exists() else ():
            if item.name != '_cacache':
                if item.is_dir(): shutil.rmtree(item)
                else: item.unlink()
        for log in attempt.glob('*.log'): log.unlink()
        for name in selection['controller']:
            copy = attempt / 'controller' / name; copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, copy)
            require(common.digest(copy) == selection['controller'][name], 'Controller changed during staging')
        require(native_identity(data) == selection['native'], 'Native runtime changed during staging')
        manifest = {'owner': OWNER, 'backend': selection['backend'], 'selection_id': selection_id,
                    'selection': selection, 'policy': data, 'node_version': selection['native']['node']['version'],
                    'native': selection['native'], 'lock_sha256': common.digest(npm / 'package-lock.json'),
                    'inventory': inventory(attempt)}
        release_id = sha(encoded(manifest)); atomic(attempt / 'manifest.json', manifest)
        destination = root / 'releases' / release_id; require(not destination.exists(), 'Concurrent release appeared')
        common.load_script('install-playwright-mcp.py').publish(attempt, destination)
        atomic(index, {'release': release_id}); verify_release(root, release_id); return release_id
    except BaseException as exc:
        atomic(attempt / 'failure.json', {'status': 'FAILED', 'reason': str(exc), 'created_unix': time.time()})
        raise


def verify_release(root, release_id):
    require(isinstance(release_id, str) and ID.fullmatch(release_id), 'Invalid release ID')
    release = common.safe(root / 'releases' / release_id)
    manifest = read(release / 'manifest.json', 64 * 1024 * 1024)
    require(manifest.get('owner') == OWNER and sha(encoded(manifest)) == release_id, 'Release manifest identity differs')
    # The manifest is the only file not included in its own inventory.
    rows = [row for row in inventory(release) if row[0] != 'manifest.json']
    require(rows == manifest['inventory'], 'Retained release drifted; preserve and investigate')
    require(common.digest(release / 'npm/package-lock.json') == manifest['lock_sha256'], 'npm lock changed')
    return release, manifest


def qualify(root, data, release_id):
    with activity(root, exclusive=True), external_benchmark(data):
        return _qualify(root, data, release_id)


def _qualify(root, data, release_id):
    guard_controller()
    release, manifest = verify_release(root, release_id)
    require(manifest.get('backend') == 'native-brave-sandbox/v1' and manifest['native'] == native_identity(data), 'Native runtime differs; prepare a new host-bound release')
    require(manifest['selection']['controller'] == controller_identity(), 'Controller differs; prepare a new release')
    require(manifest['selection']['platform'] == host(data), 'Release platform differs from qualification target')
    wait_for_apt()
    require(int(manifest['node_version'][1:].split('.')[0]) >= data['minimum_node_major'], 'Historical Node is below the selected policy minimum')
    folder = root / 'qualifications' / (release_id + '-' + uuid.uuid4().hex); folder.mkdir(mode=0o700)
    previous_proof = root / 'qualifications' / (release_id + '.json')
    if previous_proof.exists(): previous_proof.rename(folder / 'previous-index.json')
    result = {'owner': OWNER, 'release': release_id, 'status': 'RUNNING',
              'host': platform.node(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'controller': controller_identity(), 'created_unix': time.time(),
              'host_native_sha256': sha(encoded(native_identity(data))),
              'apt_epoch_ns': apt_epoch(),
              'verification_policy': data, 'verification_policy_sha256': sha(encoded(data))}
    try:
        import toolchain_canary
        result['checks'] = toolchain_canary.run(release, folder, data)
        require(controller_identity() == result['controller'], 'Controller changed during qualification')
        require(manifest['native'] == native_identity(data), 'Native runtime changed during qualification')
        require(apt_epoch() == result['apt_epoch_ns'], 'Native packages changed during qualification; qualify again after APT finishes')
        verify_release(root, release_id)
        result.update(status='QUALIFIED_HOST_TOOLCHAIN_NOT_C00', created_unix=time.time())
        result['evidence'] = {}
        # Seal controlled top-level receipts and MCP traces. Browser-created
        # HOME caches/configuration contain transient names and are not evidence.
        for item in sorted(folder.iterdir()):
            require(not item.is_symlink(), 'Symlink in qualification output refused')
            if item.is_file() and not item.name.startswith('.'):
                result['evidence'][item.name] = common.digest(common.safe(item))
        atomic(folder / 'receipt.json', result)
        atomic(root / 'qualifications' / (release_id + '.json'), {'path': str(folder / 'receipt.json'), 'sha256': common.digest(folder / 'receipt.json')})
        return result
    except BaseException as exc:
        result.update(status='FAILED', reason=str(exc)); atomic(folder / 'receipt.json', result)
        raise


def qualification(root, data, release_id, enforce_age=True):
    index = read(root / 'qualifications' / (release_id + '.json'))
    path = common.safe(Path(index['path']))
    require(path.is_relative_to(root / 'qualifications') and common.digest(path) == index['sha256'], 'Qualification evidence changed')
    proof = read(path)
    if data is None: data = proof['verification_policy']
    require(proof['verification_policy_sha256'] == sha(encoded(data)) and proof['verification_policy'] == data, 'Qualification settings changed')
    require(proof['status'] == 'QUALIFIED_HOST_TOOLCHAIN_NOT_C00' and proof['release'] == release_id
            and proof['host'] == platform.node() and proof['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            and proof['controller'] == controller_identity(), 'Qualification is not valid on this runtime/boot')
    require(proof['host_native_sha256'] == sha(encoded(native_identity(data))), 'Native Brave/Node changed; prepare and qualify a new release')
    require(proof['apt_epoch_ns'] == apt_epoch(), 'Native packages changed; qualify again')
    age = time.time() - proof['created_unix']
    require(age >= 0 and (not enforce_age or age <= data['qualification_max_age_seconds']), 'Qualification expired; run qualify again')
    for key, name in (('schema_sha256', 'schema.json'), ('browser_evidence_sha256', 'browser.json'), ('model_evidence_sha256', 'model.json')):
        require(common.digest(path.parent / name) == proof['checks'][key], 'Qualification attachment changed')
    for name in ('browser_sandbox', 'browser_fixture', 'mcp_tools', 'service_workers_flag', 'model_tool_round_trip'):
        require(proof['checks'][name] is True, 'Missing qualification gate: ' + name)
    for name, expected in proof['evidence'].items():
        relative = PurePosixPath(name)
        require(relative.parts and not relative.is_absolute() and '..' not in relative.parts, 'Invalid evidence reference')
        require(common.digest(common.safe(path.parent.joinpath(*relative.parts))) == expected, 'Qualification trace changed')
    return index


def active(root):
    file = root / 'active.json'
    if not file.exists(): return None
    pointer = read(file)
    require(pointer.get('owner') == OWNER, 'Unknown active toolchain owner')
    verify_release(root, pointer['release'])
    return pointer


def promote(root, data, release_id, reason='update'):
    release, manifest = verify_release(root, release_id)
    held = read(root / 'held.json') if (root / 'held.json').exists() else {}
    require(manifest['selection_id'] not in held, 'This selection was held after rollback; explicitly unhold it before promotion')
    proof = qualification(root, data, release_id)
    previous = active(root)
    if previous and previous['release'] == release_id:
        return {'status': 'UNCHANGED', 'release': release_id}
    event = {'owner': OWNER, 'release': release_id, 'previous': previous['release'] if previous else None,
             'reason': reason, 'qualification': proof, 'created_unix': time.time()}
    # Write the history first; an interrupted promotion never destroys the old
    # active pointer. The pointer itself is one atomic JSON replacement.
    atomic(root / 'events' / (str(time.time_ns()) + '.json'), event)
    atomic(root / 'active.json', event)
    return {'status': 'PROMOTED', 'release': release_id, 'previous': event['previous']}


def update(root, data, promote_after=True):
    # Timed workers block the whole background operation, including resolver
    # downloads/CPU/disk load. Ordinary MCP sessions only block model canaries.
    with activity(root, exclusive=True, kind='benchmark'):
        return _update(root, data, promote_after)


def _update(root, data, promote_after=True):
    current = active(root)
    if current:
        # Renew a retained runtime after reboot/host changes BEFORE contacting
        # package servers. Offline vendor access must not strand a healthy,
        # cached toolchain whose local model is available.
        try: qualification(root, data, current['release'], enforce_age=False)
        except (RuntimeError, OSError):
            try: qualify(root, data, current['release'])
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                atomic(root / 'baseline-renewal.json', {'status': 'DEFERRED' if isinstance(exc, Deferred) else 'FAILED',
                    'release': current['release'], 'reason': str(exc), 'created_unix': time.time()})
                # A newer candidate may fix an old runtime incompatibility;
                # keep the old failure and continue the normal update gates.
    selection_id, selection = resolve(root, data)
    held = read(root / 'held.json') if (root / 'held.json').exists() else {}
    if selection_id in held:
        return {'status': 'HELD_AFTER_ROLLBACK', 'selection': selection_id, 'release': held[selection_id]['release']}
    current = active(root)
    if current:
        _, manifest = verify_release(root, current['release'])
        if manifest['selection_id'] == selection_id:
            # Check again after a host reboot/update or receipt expiry, without
            # resolving dependencies or rebuilding unchanged release bytes.
            try: qualification(root, data, current['release'])
            except (RuntimeError, OSError): qualify(root, data, current['release'])
            return {'status': 'UNCHANGED', 'release': current['release']}
    release_id = prepare(root, data, selection_id, selection)
    qualify(root, data, release_id)
    if promote_after: return promote(root, data, release_id)
    return {'status': 'QUALIFIED_NOT_PROMOTED', 'release': release_id}


def export_release(root, release_id, destination):
    release, _ = verify_release(root, release_id)
    destination = common.safe(Path(destination))
    require(not destination.exists(), 'Export destination exists; refuse overwrite')
    with destination.open('xb') as out:
        os.fchmod(out.fileno(), 0o600)
        with tarfile.open(fileobj=out, mode='w:xz', dereference=False) as archive:
            for base, dirs, files in os.walk(release, followlinks=False):
                dirs.sort()
                for name in sorted(dirs + files):
                    path = Path(base) / name
                    info = archive.gettarinfo(str(path), arcname=str(path.relative_to(release)))
                    info.uid = info.gid = 0; info.uname = info.gname = ''; info.mtime = 0
                    if info.isreg() or info.islnk():
                        # Never emit hardlinks referring to files outside the bundle.
                        info.type = tarfile.REGTYPE; info.linkname = ''; info.size = path.stat().st_size
                        with path.open('rb') as source: archive.addfile(info, source)
                    else: archive.addfile(info)
    return {'status': 'EXPORTED', 'release': release_id, 'path': str(destination), 'sha256': common.digest(destination)}


def import_release(root, archive_path, checksum):
    archive_path = common.safe(Path(archive_path))
    require(ID.fullmatch(checksum) and common.digest(archive_path) == checksum, 'Recovery archive checksum differs')
    stage = Path(tempfile.mkdtemp(prefix='import-', dir=root / 'attempts'))
    try:
        count = total = 0; links = []; directories = []
        with tarfile.open(archive_path, 'r:xz') as archive:
            seen = set()
            for item in archive:
                name = PurePosixPath(item.name)
                require(name.parts and not name.is_absolute() and '..' not in name.parts and str(name) not in seen, 'Unsafe/duplicate recovery path')
                seen.add(str(name)); count += 1; total += item.size
                require(count <= 200002 and 0 <= item.size <= total <= 12 * 1024 ** 3 and not item.mode & 0o6000, 'Recovery archive limit exceeded')
                destination = stage.joinpath(*name.parts)
                if item.issym(): links.append((destination, item.linkname)); continue
                require(item.isdir() or item.isfile(), 'Recovery device/hardlink refused')
                destination.parent.mkdir(parents=True, exist_ok=True)
                if item.isdir():
                    destination.mkdir(exist_ok=True); directories.append((destination, item.mode))
                else:
                    with destination.open('xb') as out:
                        os.fchmod(out.fileno(), item.mode); shutil.copyfileobj(archive.extractfile(item), out)
        # Create links only after all regular files: no link can redirect an
        # extraction write outside staging. inventory validates every target.
        for destination, target in links:
            destination.parent.mkdir(parents=True, exist_ok=True); destination.symlink_to(target)
        for directory, mode in reversed(directories): directory.chmod(mode)
        manifest = read(stage / 'manifest.json', 64 * 1024 * 1024)
        require(manifest.get('owner') == OWNER, 'Unknown recovery manifest owner/version')
        release_id = sha(encoded(manifest))
        require([row for row in inventory(stage) if row[0] != 'manifest.json'] == manifest['inventory'], 'Recovery inventory differs')
        target = root / 'releases' / release_id
        if target.exists():
            verify_release(root, release_id); shutil.rmtree(stage)
        else: common.load_script('install-playwright-mcp.py').publish(stage, target)
        verify_release(root, release_id)
        return {'status': 'IMPORTED_NOT_QUALIFIED', 'release': release_id}
    except BaseException:
        # Preserve a failed recovery input for diagnosis, never publish it.
        raise
