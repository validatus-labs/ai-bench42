#!/usr/bin/env python3
"""Install official ARM64 Brave using the existing Ubuntu AppArmor profile.

Identity: root on spark-a922. Inputs: --prepare or --install, versioned APT files.
Effects: scoped APT key/source/pin, root-owned backups, native Brave package.
No existing package upgrade/removal, custom AppArmor policy or sysctl change.
Run as a durable systemd job: sudo python3 -B scripts/deploy/install-spark-brave.py --prepare
Flow: identity -> lock -> backup -> verified vendor key -> APT config/update
      -> non-upgrading plan + downloaded package -> [--install] -> verification.
Failure: stop and retain evidence/configuration backups; no automatic rollback.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare', action='store_true')
    mode.add_argument('--install', action='store_true')
    parser.add_argument('--project-root', type=Path, default=Path('/home/validatus/workspace/AI-Model'))
    parser.add_argument('--hostname', default='spark-a922')
    args = parser.parse_args()
    if os.geteuid() != 0 or platform.node() != args.hostname or platform.machine() != 'aarch64':
        parser.error('requires root on ARM64 spark-a922')
    os.umask(0o077)
    os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin', LC_ALL='C',
                      DEBIAN_FRONTEND='noninteractive', NEEDRESTART_MODE='l')
    state = Path('/var/lib/ai-model-apt-maintenance')
    state.mkdir(mode=0o700, exist_ok=True)
    lock = (state / 'maintenance.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run = state / 'brave' / stamp
    run.mkdir(parents=True, mode=0o700)
    project = args.project_root.resolve()
    report = {'started': stamp, 'mode': 'install' if args.install else 'prepare', 'run': str(run)}

    def save():
        (run / 'result.json').write_text(json.dumps(report, indent=2) + '\n')

    def command(argv):
        process = subprocess.run(argv, cwd=run, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        name = str(len(list(run.glob('command-*.log'))))
        (run / ('command-' + name + '.log')).write_text(process.stdout)
        if process.returncode:
            raise RuntimeError('{} failed; see command-{}.log'.format(argv[0], name))
        return process.stdout

    def package_versions():
        text = command(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\t${db:Status-Status}\n'])
        return {row.split('\t')[0]: row.split('\t')[1] for row in text.splitlines()
                if row.endswith('\tinstalled')}

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def converge(path, content):
        if path.is_symlink():
            raise RuntimeError('refusing symlink: ' + str(path))
        if path.exists():
            if path.read_bytes() != content:
                raise RuntimeError('preserve divergent existing file: ' + str(path))
            return
        path.write_bytes(content)
        path.chmod(0o644)

    try:
        profile = Path('/etc/apparmor.d/brave')
        report['profile_sha256_before'] = digest(profile)
        report['apparmor_files_before'] = {p.name: digest(p) for p in Path('/etc/apparmor.d').iterdir() if p.is_file()}
        assert 'profile brave /opt/brave.com/brave/brave flags=(unconfined)' in profile.read_text()
        assert 'brave (unconfined)' in Path('/sys/kernel/security/apparmor/profiles').read_text().splitlines()
        assert Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns').read_text().strip() == '1'
        targets = [Path('/usr/share/keyrings/brave-browser-archive-keyring.gpg'),
                   Path('/etc/apt/sources.list.d/ai-model-brave.sources'),
                   Path('/etc/apt/preferences.d/ai-model-brave'),
                   Path('/etc/dpkg/dpkg.cfg.d/ai-model-brave')]
        # Preserve exact prior files before any writes, including an absence record.
        report['prior_files'] = []
        for target in targets:
            entry = {'path': str(target), 'existed': target.exists()}
            if target.is_symlink():
                raise RuntimeError('refusing symlink: ' + str(target))
            if target.exists():
                backup = run / (target.name + '.before')
                backup.write_bytes(target.read_bytes())
                entry['backup'] = str(backup)
            report['prior_files'].append(entry)
        save()
        key = run / 'release.gpg'
        with urllib.request.urlopen('https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg', timeout=60) as response:
            key.write_bytes(response.read(1048576))
        gnupg = run / 'gnupg'
        gnupg.mkdir(mode=0o700)
        keys = command(['gpg', '--homedir', str(gnupg), '--batch', '--show-keys', '--with-colons', str(key)])
        primary, expect_fingerprint = [], False
        for row in keys.splitlines():
            fields = row.split(':')
            if fields[0] == 'pub':
                expect_fingerprint = True
            elif fields[0] == 'fpr' and expect_fingerprint:
                primary.append(fields[9]); expect_fingerprint = False
        expected = {'DBF1A116C220B8C7164F98230686B78420038257',
                    '47D32A74E9A9E013A4B4926C68D513D36A73CD96',
                    'B2A3DCA350E67256740DF904DE4EC67BE4B0DCA0'}
        assert primary and set(primary).issubset(expected), 'unexpected Brave release key'
        report['key_fingerprints'] = primary
        converge(targets[0], key.read_bytes())
        converge(targets[1], (project / 'config/brave-browser.sources').read_bytes())
        converge(targets[2], (project / 'config/brave-browser.preferences').read_bytes())
        converge(targets[3], (project / 'config/brave-dpkg.cfg').read_bytes())
        before = package_versions()
        command(['apt-get', '-o', 'DPkg::Lock::Timeout=1800', '-o', 'APT::Update::Error-Mode=any', 'update'])
        policy = command(['apt-cache', 'policy', 'brave-browser'])
        candidate = re.search(r'^\s*Candidate: (\S+)', policy, re.M).group(1)
        assert candidate != '(none)'
        report['candidate'] = candidate
        install = ['apt-get', '-o', 'DPkg::Lock::Timeout=1800', '-o', 'Dpkg::Options::=--force-confold',
                   '--no-upgrade', '--no-remove', '--no-install-recommends']
        plan = command(install + ['--simulate', 'install', 'brave-browser=' + candidate])
        assert not re.search(r'^Remv ', plan, re.M)
        planned = re.findall(r'^Inst (\S+)(?: \[([^\]]+)\])?', plan, re.M)
        assert not any(old for _, old in planned), 'refusing existing-package upgrade'
        report['planned_new_packages'] = [name for name, _ in planned]
        report['plan'] = plan
        if 'brave-browser' not in before:
            command(['apt-get', 'download', 'brave-browser=' + candidate])
            package = next(run.glob('brave-browser_*.deb'))
            report['download'] = {'path': str(package), 'sha256': digest(package)}
            control = run / 'control'
            command(['dpkg-deb', '--control', str(package), str(control)])
            report['package_apparmor_members'] = [s for s in command(['dpkg-deb', '--contents', str(package)]).splitlines() if '/apparmor' in s]
        if args.install:
            alternatives = {}
            for name in ['x-www-browser', 'gnome-www-browser']:
                query = command(['update-alternatives', '--query', name])
                alternatives[name] = re.search(r'^Value: (.+)$', query, re.M).group(1)
            report['default_browsers_before'] = alternatives
            command(install + ['--yes', 'install', 'brave-browser=' + candidate])
            # Native package postinst registers a high-priority browser; preserve
            # the prior effective desktop browser (auto groups become manual).
            for name, value in alternatives.items():
                query = command(['update-alternatives', '--query', name])
                if re.search(r'^Value: (.+)$', query, re.M).group(1) != value:
                    command(['update-alternatives', '--set', name, value])
            report['default_browsers_after'] = {name: command(['update-alternatives', '--query', name]) for name in alternatives}
        after = package_versions()
        report['packages_added'] = {k: v for k, v in after.items() if k not in before}
        report['packages_changed'] = {k: [v, after.get(k)] for k, v in before.items() if after.get(k) != v}
        assert not report['packages_changed']
        report['profile_sha256_after'] = digest(profile)
        assert report['profile_sha256_before'] == report['profile_sha256_after']
        report['apparmor_files_after'] = {p.name: digest(p) for p in Path('/etc/apparmor.d').iterdir() if p.is_file()}
        assert report['apparmor_files_before'] == report['apparmor_files_after'], 'AppArmor files changed unexpectedly'
        assert Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns').read_text().strip() == '1'
        if args.install:
            binary = Path('/opt/brave.com/brave/brave')
            assert binary.is_file() and binary.stat().st_uid == 0
            report['version'] = command([str(binary), '--version']).strip()
            report['dpkg_verify'] = command(['dpkg', '--verify', 'brave-browser'])
            expected_missing = 'missing     /opt/brave.com/brave/apparmor.d/brave-browser-stable'
            assert all(line.strip() == expected_missing for line in report['dpkg_verify'].splitlines()), 'unexpected package integrity difference'
            report['expected_integrity_exception'] = 'Excluded duplicate vendor AppArmor template only'
        report['passed'] = True
    except Exception as error:
        report['passed'] = False
        report['error'] = str(error)
        raise
    finally:
        report['completed'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save()
        print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
