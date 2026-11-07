"""Bounded host observations and before/after native vLLM counters.

telemetry.py
|-- sample()      MemAvailable, swap and optional nvidia-smi (host-wide)
|-- counters()    read native Prometheus counters without generation
`-- Monitor      sampled min/max, raw evidence, explicit unknowns
"""
import contextlib
import math
import re
import subprocess
import threading
import time
import urllib.request

from . import common as c


def counters(model):
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(model['base_url'].removesuffix('/v1') + '/metrics', timeout=4) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        c.require(len(raw) <= 2 * 1024 * 1024, 'Oversized metrics response')
        rows = {}
        for line in raw.decode().splitlines():
            match = re.fullmatch(r'(vllm:[a-zA-Z0-9_:]+(?:\{[^\n]*\})?)\s+([-+0-9.eE]+)(?:\s+\d+)?', line)
            if match and any(key in match[1] for key in ('prompt_tokens', 'generation_tokens', 'prefix_cache', 'num_requests_waiting', 'num_requests_running')):
                value = float(match[2])
                if math.isfinite(value): rows[match[1]] = value
                c.require(len(rows) <= 2000, 'Too many metric series')
        return {'status': 'OBSERVED' if rows else 'UNAVAILABLE', 'native_series': rows}
    except (OSError, ValueError, RuntimeError) as exc:
        return {'status': 'UNAVAILABLE', 'reason': type(exc).__name__}


def sample():
    rows = {'timestamp': time.time()}
    try:
        memory = {}
        for line in open('/proc/meminfo'):
            key, value = line.split(':', 1); memory[key] = int(value.split()[0]) * 1024
        rows.update(mem_available_bytes=memory['MemAvailable'], swap_used_bytes=memory['SwapTotal'] - memory['SwapFree'])
    except (OSError, ValueError, KeyError):
        rows['memory_status'] = 'UNAVAILABLE'
    try:
        result = subprocess.run(['/usr/bin/nvidia-smi', '--query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw',
                                 '--format=csv,noheader,nounits'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, timeout=3, text=True, env={'PATH': '/usr/bin:/bin', 'LANG': 'C'})
        if result.returncode == 0:
            values = result.stdout.splitlines()[0].split(',')
            for key, value in zip(('gpu_utilization_percent', 'gpu_memory_used_mib', 'gpu_temperature_c', 'gpu_power_w'), values):
                with contextlib.suppress(ValueError):
                    observed = float(value)
                    if math.isfinite(observed): rows[key] = observed
    except (OSError, IndexError, subprocess.SubprocessError):
        rows['gpu_status'] = 'UNAVAILABLE'
    return rows


class Monitor:
    def __init__(self, folder, model):
        self.folder, self.model = folder, model
        self.done = threading.Event()
        self.rows = []
        self.summary = {}

    def __enter__(self):
        self.before = counters(self.model)
        self.rows.append(sample())
        def collect():
            while not self.done.wait(5):
                if len(self.rows) < 20000: self.rows.append(sample())
        self.thread = threading.Thread(target=collect, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.done.set(); self.thread.join(timeout=4)
        self.rows.append(sample())
        after = counters(self.model)
        measurements = {}
        for key, mode, unit in [('mem_available_bytes', min, 'bytes'), ('swap_used_bytes', max, 'bytes'),
                                ('gpu_memory_used_mib', max, 'MiB'), ('gpu_temperature_c', max, 'C'),
                                ('gpu_power_w', max, 'W'), ('gpu_utilization_percent', max, '%')]:
            values = [row[key] for row in self.rows if key in row]
            if values:
                measurements[('minimum_' if mode is min else 'sampled_peak_') + key] = {'value': mode(values), 'unit': unit}
        deltas = {}
        for key, before in self.before.get('native_series', {}).items():
            # Gauges and unknown semantics are retained raw, never called cached tokens.
            if '_total' not in key: continue
            value = after.get('native_series', {}).get(key)
            if value is not None and value >= before: deltas[key] = value - before
        self.summary = {'metrics': measurements, 'samples': len(self.rows), 'interval_seconds': 5,
                        'scope': 'sampled host-wide observations; peaks may occur between samples; power is not energy',
                        'native_counter_deltas': deltas,
                        'cache_reuse_percent': None,
                        'cache_note': 'Native counter units depend on the pinned server; no token reuse percentage is inferred.'}
        c.save(self.folder / 'telemetry.json', {'summary': self.summary, 'samples': self.rows,
                                               'counters_before': self.before, 'counters_after': after})
