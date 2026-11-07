"""Actual bounded partial-header sockets; no model or browser access."""
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_gui_inner as inner
import inference_transport as inference


class TransportTests(unittest.TestCase):
    def exercise(self,cls,handler,tcp=False):
        with tempfile.TemporaryDirectory() as tmp:
            address=('127.0.0.1',0) if tcp else str(Path(tmp)/'test.sock')
            with cls(address,handler) as server:
                server.idle_timeout=.05
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    client=socket.socket(socket.AF_INET if tcp else socket.AF_UNIX)
                    try:
                        client.settimeout(2);client.connect(server.server_address)
                        client.sendall(b'GET / HTTP/1.1\r\nX-Partial:')
                        self.assertEqual(client.recv(1),b'')
                    finally:client.close()
                finally:server.shutdown();thread.join(timeout=2)

    def test_inner_ui_partial_header_expires(self):self.exercise(inner.Server,inner.Relay)
    def test_inference_unix_partial_header_expires(self):self.exercise(inference.UnixServer,inference.Handler)
    def test_inference_loopback_partial_header_expires(self):self.exercise(inference.LocalServer,inference.Handler,True)
