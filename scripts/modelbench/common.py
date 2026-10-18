"""Private evidence, pinned inputs and bounded coordinator subprocesses.

modelbench/
|-- common.py       receipts, identities, locks and process supervision
|-- adapters.py     native benchmark integrations and scored adapter contract
|-- pipeline.py     deployment -> verification -> benchmarks -> coding -> report
`-- report.py       one self-contained HTML report and machine-readable summary
"""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import time


class Blocked(RuntimeError):
    pass


class Failed(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise Blocked(message)


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def safe(path):
    path = Path(path).expanduser().absolute()
    require('..' not in path.parts, 'Parent traversal is not allowed')
    for parent in (path,) + tuple(path.parents):
        require(not parent.is_symlink(), 'Symlink in coordinator path: ' + str(parent))
    return path


def read(path, limit=16 * 1024 * 1024):
    path = safe(path)
    require(path.is_file() and path.stat().st_size <= limit, 'Missing/oversized JSON: ' + str(path))
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(Blocked('Non-finite JSON number')))


def private_directory(path):
    path = safe(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.stat()
    require(st.st_uid == os.getuid() and stat.S_IMODE(st.st_mode) == 0o700,
            'Expected account-owned 0700 directory: ' + str(path))
    return path


def atomic_bytes(path, data):
    path = safe(path)
    temporary = path.with_name('.' + path.name + '-' + os.urandom(8).hex())
    try:
        with temporary.open('xb') as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(data); out.flush(); os.fsync(out.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_DIRECTORY | os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if temporary.exists(): temporary.unlink()


def save(path, value):
    atomic_bytes(path, encoded(value))


def pin(spec):
    require(isinstance(spec, dict) and isinstance(spec.get('path'), str), 'Configure an input path and SHA-256')
    require(isinstance(spec.get('sha256'), str) and re.fullmatch('[a-f0-9]{64}', spec['sha256']), 'Configure an exact SHA-256')
    path = safe(spec['path'])
    require(path.is_file() and digest(path) == spec['sha256'], 'Pinned file missing or changed: ' + str(path))
    return path


@contextlib.contextmanager
def locked(path):
    with safe(path).open('a') as stream:
        os.fchmod(stream.fileno(), 0o600)
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def environment(home):
    return {'HOME': str(home), 'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
            'HF_HUB_OFFLINE': '1', 'HF_DATASETS_OFFLINE': '1',
            'HF_HUB_DISABLE_TELEMETRY': '1', 'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1',
            'WANDB_DISABLED': 'true', 'DO_NOT_TRACK': '1'}


def execute(argv, folder, seconds=3600, env=None, stdin=None, max_log_bytes=32 * 1024 * 1024):
    """No shell; stream bounded output, kill the whole process group on any abort."""
    require(isinstance(argv, list) and argv and all(isinstance(x, str) and '\x00' not in x for x in argv), 'Invalid command array')
    require(Path(argv[0]).is_absolute(), 'Executable must be absolute')
    require(type(seconds) is int and 1 <= seconds <= 86400, 'Invalid command timeout')
    folder = private_directory(folder)
    require(not (folder / 'command.json').exists(), 'Command already started; retain evidence and use a new run')
    record = {'argv': argv, 'started_at': timestamp(), 'timeout_seconds': seconds, 'status': 'RUNNING'}
    save(folder / 'command.json', record)
    started = time.monotonic()
    process = None
    try:
        with (folder / 'output.log').open('xb') as out, contextlib.ExitStack() as stack:
            os.fchmod(out.fileno(), 0o600)
            source = stack.enter_context(pin(stdin).open('rb')) if stdin else subprocess.DEVNULL
            process = subprocess.Popen(argv, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       cwd=folder, env=env or environment(Path.home()),
                                       close_fds=True, start_new_session=True)
            selector = stack.enter_context(selectors.DefaultSelector())
            selector.register(process.stdout, selectors.EVENT_READ)
            size = 0
            while selector.get_map():
                if time.monotonic() - started >= seconds:
                    raise Failed('Command exceeded its wall-time budget')
                for key, _ in selector.select(timeout=0.25):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    size += len(chunk)
                    if size > max_log_bytes:
                        raise Failed('Command exceeded its log budget')
                    out.write(chunk); out.flush()
            remaining = max(0.01, seconds - (time.monotonic() - started))
            code = process.wait(timeout=remaining)
            record.update(status='EXITED', exit_code=code, log_sha256=digest(folder / 'output.log'))
    except BaseException as exc:
        record.update(status='INTERRUPTED' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'FAILED',
                      error=str(exc))
        raise
    finally:
        if process is not None:
            # Also reap descendants that kept running after their parent exited.
            with contextlib.suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGTERM)
            if process.poll() is None:
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            with contextlib.suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGKILL)
            if process.stdout is not None: process.stdout.close()
        record.setdefault('exit_code', process.returncode if process is not None else None)
        if (folder / 'output.log').is_file(): record['log_sha256'] = digest(folder / 'output.log')
        record.update(finished_at=timestamp(), elapsed_seconds=time.monotonic() - started)
        save(folder / 'command.json', record)
    return record


def inventory(folder):
    rows = {}
    for path in sorted(Path(folder).rglob('*')):
        require(not path.is_symlink(), 'Symlink in evidence: ' + str(path))
        require(path.is_file() or path.is_dir(), 'Special file in evidence: ' + str(path))
        if path.is_file():
            require(stat.S_ISREG(path.stat().st_mode), 'Special evidence file')
            rows[str(path.relative_to(folder))] = digest(path)
        require(len(rows) <= 50000, 'Evidence inventory exceeds limit')
    return rows
