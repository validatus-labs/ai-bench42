"""Versioned browser-toolchain releases; all acquisition runs as a normal user.

toolchain_lifecycle.py
|-- resolve()            signed APT metadata + npm tags -> exact selection
|-- prepare()            .deb closure + npm lock/cache -> isolated runtime
|-- qualify()            browser/kernel/MCP + real model/tool round-trip
|-- promote()/rollback() atomic stable pointer; preserve previous releases
`-- export/import       bounded, checksum-verified offline recovery bundle

Nothing upgrades native packages, the model engine, weights or an old trial.
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


def host(data):
    release = platform.freedesktop_os_release()
    expected = data['platform']
    require(release.get('ID') == expected['distribution'] and release.get('VERSION_ID') == expected['version'], 'Wrong update target OS')
    arch = output(['dpkg', '--print-architecture']).strip()
    require(arch == expected['architecture'], 'Wrong update target architecture')
    require(shutil.which('bwrap') and shutil.which('dpkg-deb'), 'Install bubblewrap/dpkg prerequisites first')
    return {'distribution': release['ID'], 'version': release['VERSION_ID'], 'architecture': arch}


def environment(home):
    return {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1',
            'npm_config_update_notifier': 'false', 'npm_config_audit': 'false', 'npm_config_fund': 'false'}


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
    platform_id = host(data)
    guard_controller()
    wait_for_apt()
    roots = []
    for name in data['apt_roots']:
        text = output(['apt-cache', 'policy', name])
        match = re.search(r'^\s*Candidate:\s+(\S+)', text, re.M)
        require(match and match[1] != '(none)', 'No signed APT candidate for ' + name)
        roots.append(name + '=' + match[1])
    # Empty status asks APT for the complete runtime dependency closure rather
    # than silently relying on whichever libraries happen to be installed.
    empty = root / 'empty-dpkg-status'
    if not empty.exists(): empty.touch(mode=0o600)
    require(empty.stat().st_size == 0, 'Resolver status file changed')
    args = ['apt-get', '--simulate', '--no-install-recommends', '--no-remove',
            '-o', 'Dir::State::status=' + str(empty), '-o', 'Debug::NoLocking=1',
            '-o', 'APT::Get::AllowUnauthenticated=false', 'install', *roots]
    plan = output(args)
    packages = {}
    for line in plan.splitlines():
        if line.startswith('Inst '):
            match = re.match(r'Inst (\S+)(?: \[[^]]+\])? \((\S+)', line)
            require(match, 'Unrecognised APT plan')
            packages[match[1]] = match[2]
    require(set(data['apt_roots']) <= {n.split(':')[0] for n in packages}, 'Incomplete APT dependency closure')
    package_hashes = {}
    for name, version in packages.items():
        metadata = output(['apt-cache', '--no-all-versions', 'show', name + '=' + version])
        hashes = set(re.findall(r'^SHA256: ([a-f0-9]{64})$', metadata, re.M))
        require(len(hashes) == 1, 'Missing/ambiguous signed package hash for ' + name)
        package_hashes[name] = hashes.pop()
    npm = {name: npm_version(name, tag) for name, tag in sorted(data['npm_dist_tags'].items())}
    selection = {'schema_version': 1, 'platform': platform_id, 'apt': packages, 'apt_sha256': package_hashes, 'npm': npm,
                 'policy_sha256': sha(encoded(data)), 'controller': controller_identity(),
                 'bwrap_sha256': common.digest(Path(shutil.which('bwrap')))}
    # Resolve the ENTIRE npm graph on every check. Looking only at dist tags
    # would miss security updates of transitive packages under unchanged MCP.
    resolver, npm_cli = resolver_runtime(root, data, selection)
    work = Path(tempfile.mkdtemp(prefix='resolve-', dir=root / 'attempts'))
    (work / 'npm').mkdir(mode=0o700)
    atomic(work / 'npm/package.json', {'private': True, 'dependencies': npm})
    output(namespace(resolver, work, ['/usr/bin/node', npm_cli, '--prefix', '/work/npm',
        'install', '--package-lock-only', '--ignore-scripts', '--no-audit', '--no-fund',
        '--registry=' + data['registry']], acquisition=True), timeout=1800, log=work / 'resolve.log')
    lock = read(work / 'npm/package-lock.json', 16 * 1024 * 1024)
    validate_npm_lock(lock, data)
    selection['npm_lock'] = lock
    selection['resolver'] = resolver.name
    selection_id = sha(encoded(selection))
    file = root / 'plans' / (selection_id + '.json')
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


def resolver_runtime(root, data, selection):
    key = sha(encoded({'apt': selection['apt'], 'hashes': selection['apt_sha256'],
                      'recipe': selection['controller']['scripts/deploy/toolchain_lifecycle.py']}))
    destination = root / 'resolvers' / key
    if destination.exists():
        metadata = read(destination / 'resolver.json', 64 * 1024 * 1024)
        require([row for row in inventory(destination) if row[0] != 'resolver.json'] == metadata['inventory'], 'Resolver runtime drifted')
        return destination, metadata['npm_cli']
    require(shutil.disk_usage(root).free >= data['minimum_free_gib'] * 1024 ** 3, 'Insufficient resolver storage')
    stage = Path(tempfile.mkdtemp(prefix='resolver-', dir=root / 'attempts'))
    download_debs(root, stage, selection)
    packages = [{'file': path.name} for path in sorted((stage / 'packages').iterdir())]
    npm_cli = runtime_fs(stage, packages)
    version = output(namespace(stage, stage, ['/usr/bin/node', '--version']), timeout=30).strip()
    require(re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', version) and int(version[1:].split('.')[0]) >= data['minimum_node_major'], 'Resolved Node version is incompatible')
    for log in stage.glob('*.log'): log.unlink()
    atomic(stage / 'resolver.json', {'npm_cli': npm_cli, 'inventory': inventory(stage)})
    common.load_script('install-playwright-mcp.py').publish(stage, destination)
    return destination, npm_cli


def namespace(release, work, argv, acquisition=False, probe=False):
    fs = release / 'rootfs'
    records = {
        'runtime-passwd': f'root:x:0:0:root:/root:/usr/bin/false\nworker:x:{os.getuid()}:{os.getgid()}:ModelBench:/home/worker:/usr/bin/false\n',
        'runtime-group': f'root:x:0:\nworker:x:{os.getgid()}:\n',
        'runtime-hosts': '127.0.0.1 localhost\n::1 localhost\n',
    }
    for name, content in records.items():
        path = common.safe(work / name)
        if path.exists(): require(path.is_file() and path.read_text() == content, 'Runtime account file changed')
        else:
            with path.open('xb') as out: os.fchmod(out.fileno(), 0o600); out.write(content.encode())
    args = [shutil.which('bwrap') or '/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--cap-drop', 'ALL', '--clearenv']
    # Acquisition uses npm's HTTPS registry. Runtime canaries share host net
    # solely to reach the explicitly selected local inference server/fixture.
    # This host-tool launcher is NOT the C00 public-research egress boundary.
    args += ['--share-net', '--ro-bind', str(fs), '/', '--proc', '/proc', '--dev', '/dev',
             '--tmpfs', '/tmp', '--tmpfs', '/home', '--dir', '/home/worker', '--tmpfs', '/run']
    if (release / 'npm').exists(): args += ['--ro-bind', str(release / 'npm'), '/npm']
    args += ['--bind', str(work), '/work']
    for name, destination in (('runtime-passwd', '/etc/passwd'), ('runtime-group', '/etc/group'), ('runtime-hosts', '/etc/hosts')):
        args += ['--ro-bind', str(work / name), destination, '--ro-bind', str(work / name), '/work/' + name]
    resolver = Path('/etc/resolv.conf').resolve(strict=True)
    args += ['--ro-bind', str(resolver), '/etc/resolv.conf']
    args += ['--setenv', 'HOME', '/home/worker', '--setenv', 'USER', 'worker', '--setenv', 'LOGNAME', 'worker', '--setenv', 'PATH', '/usr/bin:/bin',
             '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'TMPDIR', '/tmp',
             '--setenv', 'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD', '1',
             '--setenv', 'npm_config_cache', '/work/npm-cache',
             '--setenv', 'npm_config_update_notifier', 'false',
             '--setenv', 'npm_config_userconfig', '/dev/null',
             '--setenv', 'npm_config_globalconfig', '/dev/null', '--chdir', '/work']
    if probe:
        args += ['--ro-bind', str(HERE / 'toolchain_browser_probe.cjs'), '/checks/browser.cjs']
    return args + ['--', *argv]


def download_debs(root, stage, selection):
    packages = stage / 'packages'; packages.mkdir(mode=0o700)
    result = []
    for number, (name, version) in enumerate(sorted(selection['apt'].items())):
        expected = selection['apt_sha256'][name]
        cached = root / 'objects' / expected
        if cached.exists():
            require(common.digest(cached) == expected, 'Cached APT object changed')
            package = packages / (expected + '.deb'); shutil.copyfile(cached, package)
        else:
            before = set(packages.iterdir())
            output(['apt-get', '-o', 'APT::Get::AllowUnauthenticated=false',
                    '-o', 'Acquire::AllowInsecureRepositories=false', 'download', name + '=' + version],
                   cwd=packages, timeout=600, log=stage / ('apt-' + str(number) + '.log'))
            added = set(packages.iterdir()) - before
            require(len(added) == 1, 'Unexpected package download output')
            package = added.pop()
        facts = output(['dpkg-deb', '-f', package, 'Package', 'Version', 'Architecture'])
        require(re.search(r'^Version: ' + re.escape(version) + '$', facts, re.M), 'Downloaded package version differs')
        require(re.search(r'^Package: ' + re.escape(name.split(':')[0]) + '$', facts, re.M), 'Downloaded package name differs')
        require(re.search(r'^Architecture: (' + re.escape(selection['platform']['architecture']) + r'|all)$', facts, re.M), 'Downloaded package architecture differs')
        require(common.digest(package) == selection['apt_sha256'][name], 'Downloaded package differs from signed APT metadata')
        destination = packages / (expected + '.deb')
        if package != destination: package.rename(destination); package = destination
        package.chmod(0o400)
        if not cached.exists(): shutil.copyfile(package, cached); cached.chmod(0o400)
        result.append({'name': name, 'version': version, 'file': package.name, 'sha256': common.digest(package), 'control': facts})
    return result


def runtime_fs(stage, packages):
    fs = stage / 'rootfs'; fs.mkdir(mode=0o755)
    for package in packages:
        output(['dpkg-deb', '--extract', stage / 'packages' / package['file'], fs], timeout=120)
    for base, dirs, files in os.walk(fs, followlinks=False):
        for name in dirs + files:
            p = Path(base) / name
            if not p.is_symlink(): p.chmod(stat.S_IMODE(p.stat().st_mode) & ~0o6000)
    for name, target in (('bin', 'usr/bin'), ('sbin', 'usr/sbin'), ('lib', 'usr/lib'), ('lib64', 'usr/lib64')):
        p = fs / name
        if not p.exists() and not p.is_symlink(): p.symlink_to(target)
    for name in ('tmp', 'proc', 'dev', 'run', 'home', 'work', 'npm', 'checks', 'etc/ssl/certs'):
        (fs / name).mkdir(parents=True, exist_ok=True)
    for name in ('etc/resolv.conf', 'etc/passwd', 'etc/group', 'etc/hosts', 'checks/browser.cjs'):
        placeholder = fs / name
        if placeholder.is_symlink(): placeholder.unlink()
        if not placeholder.exists(): placeholder.touch(mode=0o644)
    # Package extraction does not run maintainer scripts. Build the CA bundle
    # from the certificates in the verified ca-certificates package itself.
    certificates = sorted((fs / 'usr/share/ca-certificates').rglob('*.crt'))
    require(certificates, 'CA certificates missing from runtime closure')
    (fs / 'etc/ssl/certs/ca-certificates.crt').write_bytes(b'\n'.join(p.read_bytes() for p in certificates))
    require((fs / 'usr/bin/node').is_file() and (fs / 'opt/brave.com/brave/brave').is_file(), 'Runtime package closure has no Node/Brave')
    choices = ('usr/lib/node_modules/npm/bin/npm-cli.js', 'usr/share/nodejs/npm/bin/npm-cli.js')
    npm = next(('/' + p for p in choices if (fs / p).is_file()), None)
    require(npm, 'The selected Node package must supply npm; configure the approved Node 22+ source')
    return npm


def prepare(root, data, selection_id, selection):
    require(controller_identity() == selection['controller'], 'Controller source changed since resolution')
    require(shutil.disk_usage(root).free >= data['minimum_free_gib'] * 1024 ** 3, 'Insufficient free space for retained toolchains')
    index = root / 'plans' / (selection_id + '.release.json')
    if index.exists():
        release_id = read(index)['release']; verify_release(root, release_id)
        return release_id
    attempt = root / 'attempts' / ('prepare-' + uuid.uuid4().hex); attempt.mkdir(mode=0o700)
    try:
        packages = download_debs(root, attempt, selection)
        resolver = root / 'resolvers' / selection['resolver']
        resolver_runtime(root, data, selection)  # Verify cached bytes before copying.
        shutil.copytree(resolver / 'rootfs', attempt / 'rootfs', symlinks=True)
        npm_cli = read(resolver / 'resolver.json', 64 * 1024 * 1024)['npm_cli']
        version = output(namespace(attempt, attempt, ['/usr/bin/node', '--version']), timeout=30).strip()
        require(re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', version) and int(version[1:].split('.')[0]) >= data['minimum_node_major'], 'Candidate Node version is incompatible')
        npm = attempt / 'npm'; npm.mkdir(mode=0o700)
        atomic(npm / 'package.json', {'private': True, 'dependencies': selection['npm']})
        atomic(npm / 'package-lock.json', selection['npm_lock'])
        previous = active(root)
        if previous:
            previous_cache = root / 'releases' / previous['release'] / 'npm-cache'
            if previous_cache.exists(): shutil.copytree(previous_cache, attempt / 'npm-cache', symlinks=True)
        # npm is mounted read-only at /npm but writes via /work/npm while staging.
        for operation in (['ci'],):
            args = ['/usr/bin/node', npm_cli, '--prefix', '/work/npm', *operation,
                    '--ignore-scripts', '--no-audit', '--no-fund', '--registry=' + data['registry']]
            output(namespace(attempt, attempt, args, acquisition=True), timeout=1800,
                   log=attempt / ('npm-' + operation[0] + '.log'))
        lock = read(npm / 'package-lock.json', 16 * 1024 * 1024)
        validate_npm_lock(lock, data)
        require(lock == selection['npm_lock'], 'npm changed the exact pre-resolved dependency graph')
        require((npm / 'node_modules/@playwright/mcp/cli.js').is_file(), 'MCP CLI missing')
        # npm's content-addressed cache enables recovery even after upstream
        # removes a package. Logs and incidental timestamps are not release data.
        cache = attempt / 'npm-cache'
        for p in tuple(cache.iterdir()) if cache.exists() else ():
            if p.name != '_cacache':
                if p.is_dir(): shutil.rmtree(p)
                else: p.unlink()
        for log in attempt.glob('*.log'): log.unlink()
        for name in selection['controller']:
            copy = attempt / 'controller' / name
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, copy)
            require(common.digest(copy) == selection['controller'][name], 'Controller changed during preparation')
        manifest = {'owner': OWNER, 'selection_id': selection_id, 'selection': selection,
                    'policy': data, 'node_version': version, 'packages': packages,
                    'lock_sha256': common.digest(npm / 'package-lock.json'),
                    'inventory': inventory(attempt)}
        release_id = sha(encoded(manifest))
        atomic(attempt / 'manifest.json', manifest)
        destination = root / 'releases' / release_id
        require(not destination.exists(), 'Release appeared concurrently')
        common.load_script('install-playwright-mcp.py').publish(attempt, destination)
        atomic(index, {'release': release_id})
        verify_release(root, release_id)
        return release_id
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
    with activity(root, exclusive=True):
        return _qualify(root, data, release_id)


def _qualify(root, data, release_id):
    guard_controller()
    release, manifest = verify_release(root, release_id)
    require(manifest['selection']['platform'] == host(data), 'Release platform differs from qualification target')
    wait_for_apt()
    require(int(manifest['node_version'][1:].split('.')[0]) >= data['minimum_node_major'], 'Historical Node is below the selected policy minimum')
    folder = root / 'qualifications' / (release_id + '-' + uuid.uuid4().hex); folder.mkdir(mode=0o700)
    previous_proof = root / 'qualifications' / (release_id + '.json')
    if previous_proof.exists(): previous_proof.rename(folder / 'previous-index.json')
    result = {'owner': OWNER, 'release': release_id, 'status': 'RUNNING',
              'host': platform.node(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              'controller': controller_identity(), 'created_unix': time.time(),
              'host_bwrap_sha256': common.digest(Path(shutil.which('bwrap'))),
              'apt_epoch_ns': apt_epoch(),
              'verification_policy': data, 'verification_policy_sha256': sha(encoded(data))}
    try:
        import toolchain_canary
        result['checks'] = toolchain_canary.run(release, folder, data)
        require(controller_identity() == result['controller'], 'Controller changed during qualification')
        require(apt_epoch() == result['apt_epoch_ns'], 'Native packages changed during qualification; qualify again after APT finishes')
        verify_release(root, release_id)
        result.update(status='QUALIFIED_HOST_TOOLCHAIN_NOT_C00', created_unix=time.time())
        result['evidence'] = {}
        for item in sorted(folder.rglob('*')):
            require(not item.is_symlink(), 'Symlink in qualification output refused')
            if item.is_file():
                result['evidence'][str(item.relative_to(folder))] = common.digest(common.safe(item))
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
    require(proof['host_bwrap_sha256'] == common.digest(Path(shutil.which('bwrap'))), 'Host sandbox binary changed; qualify again')
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
