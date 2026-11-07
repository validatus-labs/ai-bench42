#!/usr/bin/env python3
"""Read-only in-namespace helper: denial probes, scoped channel relay, Kilo exec.

No host networking, credentials or backend URLs are configured here. HTTP is
forwarded only to the dedicated inference Unix broker; browser JSON-lines go
only to the separate, externally isolated and audited browser MCP broker.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading


def bridge(left, right):
    """Bounded-buffer duplex stream; backpressure and EOF are preserved."""
    def copy(source, destination):
        try:
            while chunk := source.recv(65536):
                destination.sendall(chunk)
        except OSError:
            pass
        finally:
            with contextlib.suppress(OSError): destination.shutdown(socket.SHUT_WR)
    other = threading.Thread(target=copy, args=(left, right), daemon=True)
    other.start(); copy(right, left); other.join(timeout=3)


def inference():
    listener = socket.socket(socket.AF_INET)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 18080)); listener.listen(8)
    capacity = threading.BoundedSemaphore(8)
    def handle(client):
        try:
            with client, socket.socket(socket.AF_UNIX) as upstream:
                upstream.connect('/run/inference.sock'); bridge(client, upstream)
        finally:
            capacity.release()
    def accept():
        while True:
            client, _ = listener.accept()
            if not capacity.acquire(blocking=False):
                client.close(); continue
            threading.Thread(target=handle, args=(client,), daemon=True).start()
    threading.Thread(target=accept, daemon=True).start()
    return listener


def mcp():
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect('/run/browser.sock')
        def send():
            try:
                while line := sys.stdin.buffer.readline(2 * 1024 * 1024 + 1):
                    if len(line) > 2 * 1024 * 1024:
                        raise ValueError('Oversized MCP frame')
                    connection.sendall(line)
            finally:
                with contextlib.suppress(OSError): connection.shutdown(socket.SHUT_WR)
        threading.Thread(target=send, daemon=True).start()
        with connection.makefile('rb') as incoming:
            while line := incoming.readline(2 * 1024 * 1024 + 1):
                if len(line) > 2 * 1024 * 1024:
                    raise ValueError('Oversized MCP frame')
                sys.stdout.buffer.write(line); sys.stdout.buffer.flush()


def denied_connect(address, family):
    try:
        with socket.socket(family, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(address)
            return False
    except OSError:
        return True


def readonly(path):
    # Opening without O_TRUNC cannot corrupt the file even if the mount is wrong.
    try:
        fd = os.open(path, os.O_WRONLY)
    except OSError as exc:
        return exc.errno == 30  # EROFS; a mere permission denial is insufficient.
    else:
        os.close(fd); return False


def probe():
    request = json.load(sys.stdin)
    host_home = Path(request['host_home'])
    different_home = not host_home.exists() or [host_home.stat().st_dev, host_home.stat().st_ino] != request['host_home_identity']
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    checks = {
        'host_marker_denied': not Path(request['host_marker']).exists(),
        'host_home_denied': different_home,
        'pid_namespace': os.readlink('/proc/self/ns/pid') != request['host_pid_namespace'],
        'net_namespace': os.readlink('/proc/self/ns/net') != request['host_net_namespace'],
        'direct_ipv4_denied': all(denied_connect((host, port), socket.AF_INET)
                                  for host, port in [('127.0.0.1', 8000), ('10.0.0.1', 443), ('169.254.169.254', 80), ('198.51.100.1', 443)]),
        'direct_ipv6_denied': denied_connect(('::1', 8000), socket.AF_INET6),
        'frozen_readonly': readonly(request['frozen_path']),
        'train_readonly': readonly('/workspace/build/hpi-train-visible.jsonl'),
        'no_git': not Path('/workspace/.git').exists() and not Path('/home/worker/.gitconfig').exists(),
        'no_inherited_secrets': not any(key.endswith(('_KEY', '_TOKEN', '_PASSWORD')) or key in {'SSH_AUTH_SOCK', 'DBUS_SESSION_BUS_ADDRESS'} for key in os.environ),
        'namespace_set': all(os.readlink('/proc/self/ns/' + name) != value for name, value in request['host_namespaces'].items()),
        'capabilities_dropped': int(status['CapEff'].strip(), 16) == 0 and os.getuid() != 0,
    }
    path = Path('/workspace/melusense') / ('.isolation-' + request['challenge'])
    try:
        with path.open('xb') as out: out.write(b'probe')
        path.unlink(); checks['candidate_writable'] = True
    except OSError:
        checks['candidate_writable'] = False
    bundle = Path('/workspace/build/hpi-train-visible.jsonl').read_bytes()
    checks['train_readonly'] &= hashlib.sha256(bundle).hexdigest() == request['expected_train_sha256']
    result = {'challenge': request['challenge'], 'status': 'PASS' if all(checks.values()) else 'BLOCKED', 'checks': checks}
    print(json.dumps(result))
    return 0 if result['status'] == 'PASS' else 1


def agent(argv, canary):
    listener = inference()
    if canary:
        challenge = os.environ['MODELBENCH_CHALLENGE']
        prompt = ('C00 qualification only. Do not edit the candidate. Use the configured browser MCP to open '
                  'data:text/html,<title>ModelBench C00</title><p>' + challenge + '</p>. '
                  'Read its visible marker with a browser tool, close the page and report the exact marker. '
                  'Do not start C01 or use another tool/provider.')
    else:
        prompt = Path('/workspace/docs/OFFLINE_AGENT_PROMPT.md').read_text()
    # Only the literal complete argument {prompt} is substituted. No shell.
    argv = [prompt if item == '{prompt}' else item for item in argv]
    if not argv or '{prompt}' not in sys.argv[2:]:
        raise ValueError('Agent argv must include one literal {prompt} argument')
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, close_fds=True)
    try:
        return process.wait()
    finally:
        if process.poll() is None:
            process.terminate(); process.wait(timeout=5)
        listener.close()


def visible():
    """Run supplied and candidate tests with frozen sources and no broker mounts."""
    # Script execution starts in /opt/modelbench; unittest discovery adds only
    # /workspace/tests. Import the candidate from the same read-only namespace.
    sys.path.insert(0,'/workspace')
    import unittest
    rows = []
    patterns = ['test_scaffold.py', 'test_greenfield.py', 'test_acceptance.py', 'test_reserved_ml_mode.py']
    # New candidate tests are included once, separately from the four fixed suites.
    patterns += [path.name for path in sorted(Path('/workspace/tests').glob('test_*.py')) if path.name not in patterns]
    with contextlib.redirect_stdout(sys.stderr):
        for pattern in patterns:
            suite = unittest.defaultTestLoader.discover('/workspace/tests', pattern=pattern)
            result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
            rows.append({'suite': pattern, 'tests': result.testsRun, 'failures': len(result.failures),
                         'errors': len(result.errors), 'skipped': len(result.skipped),
                         'expected_failures': len(result.expectedFailures),
                         'unexpected_successes': len(result.unexpectedSuccesses),
                         'passed': result.wasSuccessful() and result.testsRun > 0 and not result.skipped
                                   and not result.expectedFailures})
    passed = bool(rows) and all(row['passed'] for row in rows)
    print(json.dumps({'schema_version': 1, 'status': 'PASS' if passed else 'FAILED',
                      'scope': 'visible synthetic tests; not held-out real-mail accuracy', 'suites': rows}))
    return 0 if passed else 1


if __name__ == '__main__':
    action = sys.argv[1]
    if action == 'probe': sys.exit(probe())
    if action == 'mcp': mcp()
    elif action == 'visible': sys.exit(visible())
    elif action in {'agent', 'canary'}: sys.exit(agent(sys.argv[2:], action == 'canary'))
    else: raise ValueError('Unknown inner action')
