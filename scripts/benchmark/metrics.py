#!/usr/bin/env python3
"""Expose host memory and active Run-ID on 127.0.0.1:9199, as validatus.

Input: --runtime; read active-run.json and model cgroup, no secrets or mail.
Run: python3 -B metrics.py --runtime /.../tools/benchmark
Flow: GET /metrics -> current host/cgroup observations + optional run info.
Missing model counters are omitted; unavailable GPU VRAM is never fabricated.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path


def exposition(base):
    lines = []
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        mem[key] = int(value.split()[0]) * 1024
    for name in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree"):
        lines.append("benchmark_host_" + name.lower() + "_bytes " + str(mem[name]))
    cg = Path("/sys/fs/cgroup/system.slice/ai-model-vllm-kolibri-1.service")
    for filename, metric in [("memory.current", "memory_bytes"), ("memory.swap.current", "swap_bytes")]:
        p = cg / filename
        if p.exists():
            lines.append("benchmark_model_" + metric + '{model_id="kolibri-1"} ' + p.read_text().strip())
    p = base / "active-run.json"
    if p.exists():
        d = json.loads(p.read_text())
        labels = ",".join(k + "=" + json.dumps(str(d[k])) for k in ("run_id", "model_id", "phase", "concurrency"))
        lines.append("benchmark_run_info{" + labels + "} 1")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runtime", required=True, type=Path)
    base = ap.parse_args().runtime

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/metrics":
                self.send_error(404)
                return
            try:
                data = exposition(base).encode()
            except Exception:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("127.0.0.1", 9199), Handler).serve_forever()


if __name__ == "__main__":
    main()
