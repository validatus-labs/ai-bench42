"""One inherited socket for bounded root requests from the bootstrap controller.

The model server and package-install subprocesses do not inherit this descriptor.
Standalone lifecycle commands retain their existing sudo behaviour.
"""
import json
import os
import socket
import threading

LOCK = threading.Lock()
KEY = 'MODEL_BENCH_PRIVILEGE_FD'


def request(argv, timeout=180):
    if KEY not in os.environ:
        return None
    with LOCK:
        connection = socket.socket(fileno=os.dup(int(os.environ[KEY])))
        try:
            connection.settimeout(timeout + 30)
            connection.sendall((json.dumps({'argv': list(map(str, argv)), 'timeout': timeout}) + '\n').encode())
            data = bytearray()
            while not data.endswith(b'\n'):
                block = connection.recv(4096)
                if not block:
                    raise RuntimeError('Bootstrap privilege channel closed')
                data.extend(block)
                if len(data) > 65536:
                    raise RuntimeError('Oversized privilege response')
            reply = json.loads(data)
            if reply['returncode']:
                raise RuntimeError('Owned service operation failed: ' + reply['output'])
            return reply['output']
        finally:
            connection.close()
