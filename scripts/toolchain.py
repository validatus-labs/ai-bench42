#!/usr/bin/env python3
"""Browser-toolchain updates and offline recovery. Run as your normal account.

scripts/toolchain.py
|-- check / prepare / qualify / promote  exact, independently retained releases
|-- update / scheduled                  automatic canaries and stable promotion
|-- rollback / export / import          recovery without changing older releases
`-- status / exec-mcp                   inspect or use a fixed selected release
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/deploy'))
import bootstrap_components as common
import toolchain_lifecycle as lifecycle


def cli():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--project-root', type=Path, default=ROOT)
    parser.add_argument('--policy', type=Path, default=ROOT / 'config/toolchain-updates.json')
    actions = parser.add_subparsers(dest='action', required=True)
    for name in ('check', 'prepare', 'update', 'scheduled', 'status'):
        actions.add_parser(name)
    for name in ('qualify', 'promote', 'rollback', 'unhold'):
        p = actions.add_parser(name); p.add_argument('--release', required=True)
    p = actions.add_parser('export'); p.add_argument('--release', required=True); p.add_argument('--output', required=True, type=Path)
    for name in ('import', 'restore'):
        p = actions.add_parser(name); p.add_argument('--archive', required=True, type=Path); p.add_argument('--sha256', required=True)
    p = actions.add_parser('exec-mcp'); p.add_argument('--release', default='stable')
    p = actions.add_parser('client'); p.add_argument('--release', required=True); p.add_argument('--output', required=True, type=Path)
    p = actions.add_parser('lease'); p.add_argument('command', nargs=argparse.REMAINDER)
    return parser


def client_fragment(target, release_id):
    argv = ['/usr/bin/python3', '-B', str(Path(__file__).resolve()), '--runtime-root', target['runtime'],
            '--project-root', target['project'], 'exec-mcp', '--release', release_id]
    return {'mcp': {'playwright': {'type': 'local', 'command': argv, 'enabled': True, 'timeout': 60000}}}


def publish_client(target, root, release_id):
    # The normal-client entrypoint stays constant. Only active.json switches.
    # Frozen benchmark clients use the separate `client --release ID` command.
    fragment = client_fragment(target, 'stable')
    lifecycle.atomic(root / 'client.json', fragment)
    lifecycle.atomic(Path(target['runtime']) / 'tools/bootstrap/kilo.json', fragment)


def exec_mcp(root, release_id):
    lifecycle.guard_controller()
    if release_id == 'stable':
        current = lifecycle.active(root)
        lifecycle.require(current, 'No qualified stable toolchain; run update first')
        release_id = current['release']
    release, manifest = lifecycle.verify_release(root, release_id)
    # Runtime use keeps an approved immutable release usable during long
    # sessions. Promotion/renewal has the TTL; boot/code/package drift always
    # invalidates it. No inference is triggered by opening an MCP connection.
    lifecycle.qualification(root, None, release_id, enforce_age=False)
    # Existing sessions keep their own namespace and exact release. Promotion
    # only changes the pointer for subsequent sessions; no package is replaced.
    folder = root / 'sessions' / ('mcp-' + uuid.uuid4().hex); folder.mkdir(mode=0o700)
    argv = lifecycle.namespace(release, folder, ['/usr/bin/node', '/npm/node_modules/@playwright/mcp/cli.js',
        '--headless', '--isolated', '--sandbox', '--block-service-workers',
        '--executable-path', '/opt/brave.com/brave/brave', '--output-dir', '/tmp/output'])
    with lifecycle.activity(root):
        child = subprocess.Popen(argv, env=lifecycle.environment(folder), close_fds=True)
        try: return child.wait()
        finally:
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: child.kill(); child.wait()


def main(argv=None):
    args = cli().parse_args(argv)
    root = None
    try:
        target = common.account(args.project_root, args.runtime_root)
        root = lifecycle.store(target)
        if args.action == 'exec-mcp':
            return exec_mcp(root, args.release)
        if args.action == 'lease':
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            lifecycle.require(command, 'Pass the coordinator command after lease --')
            with lifecycle.activity(root, kind='benchmark'), lifecycle.activity(root):
                return subprocess.call(command)
        data = lifecycle.policy(args.policy)
        gate = lifecycle.activity(root, exclusive=True, kind='benchmark') if args.action in ('check', 'prepare', 'export', 'import', 'restore') else contextlib.nullcontext()
        with lifecycle.locked(root), gate:
            if args.action == 'status':
                pointer = lifecycle.active(root)
                result = {'status': 'ACTIVE' if pointer else 'NO_STABLE_RELEASE', 'active': pointer,
                          'store': str(root), 'releases': sorted(p.name for p in (root / 'releases').iterdir())}
            elif args.action == 'check':
                selection_id, selection = lifecycle.resolve(root, data)
                current = lifecycle.active(root)
                unchanged = current and lifecycle.verify_release(root, current['release'])[1]['selection_id'] == selection_id
                result = {'status': 'UP_TO_DATE' if unchanged else 'UPDATE_AVAILABLE', 'selection': selection_id,
                          'apt': selection['apt'], 'npm': selection['npm']}
            elif args.action == 'prepare':
                selection_id, selection = lifecycle.resolve(root, data)
                release_id = lifecycle.prepare(root, data, selection_id, selection)
                result = {'status': 'PREPARED_NOT_QUALIFIED', 'release': release_id}
            elif args.action in ('update', 'scheduled'):
                if args.action == 'scheduled':
                    stamp = root / 'last-scheduled.json'
                    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                    if stamp.exists():
                        previous = lifecycle.read(stamp)
                        interval = min(3600, data['check_interval_seconds']) if previous.get('status') == 'FAILED' else data['check_interval_seconds']
                        if previous.get('boot_id') == boot and 0 <= time.time() - previous['started_unix'] < interval:
                            fresh = previous.get('status') == 'FAILED'
                            if not fresh:
                                current = lifecycle.active(root)
                                if current:
                                    try: lifecycle.qualification(root, data, current['release']); fresh = True
                                    except (RuntimeError, OSError): pass
                            if fresh:
                                print(json.dumps({'status': 'DEFERRED_UNTIL_NEXT_CHECK_INTERVAL'})); return 0
                    lifecycle.atomic(stamp, {'started_unix': time.time(), 'boot_id': boot, 'status': 'RUNNING'})
                publish_client(target, root, None)
                result = lifecycle.update(root, data, data['automatic_promotion'])
                if args.action == 'scheduled':
                    lifecycle.atomic(stamp, {'started_unix': time.time(), 'boot_id': boot, 'status': 'COMPLETED'})
            elif args.action == 'qualify':
                proof = lifecycle.qualify(root, data, args.release)
                result = {'status': proof['status'], 'release': args.release}
            elif args.action in ('promote', 'rollback'):
                publish_client(target, root, None)
                previous = lifecycle.active(root)
                if args.action == 'rollback':
                    # Old bytes are retained, but the older browser must still
                    # work with today's host/model before becoming stable again.
                    lifecycle.qualify(root, data, args.release)
                if args.action == 'rollback' and previous and previous['release'] != args.release:
                    _, old = lifecycle.verify_release(root, previous['release'])
                    held_path = root / 'held.json'
                    held = lifecycle.read(held_path) if held_path.exists() else {}
                    held[old['selection_id']] = {'release': previous['release'], 'created_unix': time.time(), 'reason': 'rollback'}
                    lifecycle.atomic(held_path, held)
                result = lifecycle.promote(root, data, args.release, args.action)
            elif args.action == 'unhold':
                _, manifest = lifecycle.verify_release(root, args.release)
                path = root / 'held.json'; held = lifecycle.read(path) if path.exists() else {}
                held.pop(manifest['selection_id'], None); lifecycle.atomic(path, held)
                result = {'status': 'UNHELD', 'release': args.release}
            elif args.action == 'export':
                result = lifecycle.export_release(root, args.release, args.output)
            elif args.action in ('import', 'restore'):
                result = lifecycle.import_release(root, args.archive, args.sha256)
                if args.action == 'restore':
                    lifecycle.qualify(root, data, result['release'])
                    publish_client(target, root, None)
                    result = lifecycle.promote(root, data, result['release'], 'restore')
            elif args.action == 'client':
                lifecycle.verify_release(root, args.release)
                path = common.safe(args.output.absolute())
                lifecycle.require(not path.exists(), 'Pinned client output exists; refuse overwrite')
                lifecycle.atomic(path, client_fragment(target, args.release))
                result = {'status': 'PINNED_CLIENT_EXPORTED', 'release': args.release, 'path': str(path)}
            else:
                raise RuntimeError('Unsupported action')
        print(json.dumps(result, indent=2))
        return 0
    except lifecycle.Deferred as exc:
        if root is not None:
            lifecycle.atomic(root / 'last-deferred.json', {'status': 'DEFERRED_ACTIVE_WORKLOAD', 'reason': str(exc), 'created_unix': time.time()})
        print(json.dumps({'status': 'DEFERRED_ACTIVE_WORKLOAD', 'reason': str(exc)}), file=sys.stderr)
        return 0 if args.action == 'scheduled' else 2
    except BlockingIOError:
        print(json.dumps({'status': 'BUSY', 'reason': 'Another toolchain operation owns the lock'}), file=sys.stderr); return 1
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
        if root is not None:
            with contextlib.suppress(OSError):
                if args.action == 'scheduled':
                    lifecycle.atomic(root / 'last-scheduled.json', {'started_unix': time.time(),
                        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'status': 'FAILED'})
                lifecycle.atomic(root / 'last-failure.json', {'status': 'FAILED', 'action': args.action,
                    'reason': str(exc), 'created_unix': time.time()})
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
