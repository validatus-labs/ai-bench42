#!/usr/bin/env python3
"""Verify a fresh coordinator package without installing or starting a model.

verify-package.py
|-- source identity    all package files, excluding Git/build/cache
|-- test suites        independent processes; no import-order contamination
|-- starter contract  untouched scaffold; not a claimed parser implementation
`-- receipt/reuse     checked logs and source hashes; no hidden retries

Use Python3.12 as the normal account. Socket tests need native execution.
This is package acceptance, not a model score or a Phase4 readiness certificate.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from modelbench import common as c

ROOT = Path(__file__).resolve().parents[1]
SUITES = [
    ('tests', 'test_scaffold.py'), ('tests', 'test_greenfield.py'),
    ('scripts/deploy', 'test_portable_bootstrap.py'),
    ('scripts/deploy', 'test_health.py'),
    ('scripts/deploy/dgx-spark-vllm/tests', 'test_lifecycle.py'),
    ('scripts/deploy/dgx-spark-vllm/tests', 'test_calibration.py'),
    ('scripts/deploy', 'test_kolibri.py'),
    ('scripts/deploy', 'test_playwright_installer.py'),
    ('scripts/deploy', 'test_bootstrap_spark.py'),
    ('scripts/deploy', 'test_adopt_existing.py'),
    ('scripts/deploy', 'test_requalification.py'),
    ('scripts/modelbench', 'test_kolibri_benchmark.py'),
    ('scripts/modelbench', 'test_execution.py'),
    ('scripts/modelbench', 'test_official_adapters.py'),
    ('scripts/modelbench', 'test_native_namespace.py'),
    ('scripts/modelbench', 'test_native_gui.py'),
    ('scripts/modelbench', 'test_native_inspection.py'),
    ('scripts/modelbench', 'test_native_session.py'),
    ('scripts/modelbench', 'test_native_controls.py'),
    ('scripts/modelbench', 'test_native_visible.py'),
    ('scripts/modelbench', 'test_native_readiness.py'),
    ('scripts/modelbench', 'test_native_candidate.py'),
    ('scripts/modelbench', 'test_native_candidate_resume.py'),
    ('scripts/modelbench', 'test_native_assessment.py'),
    ('scripts/modelbench', 'test_native_pipeline.py'),
    ('scripts/modelbench', 'test_native_runtime.py'),
    ('scripts/modelbench', 'test_native_browser.py'),
    ('scripts/modelbench', 'test_native_transport.py'),
    ('scripts/modelbench', 'test_inference_transport.py'),
    ('scripts/modelbench', 'test_assignment.py'),
    ('scripts/deploy', 'test_bootstrap_adoption.py'),
    ('scripts/deploy', 'test_prometheus_bootstrap.py'),
    ('scripts/deploy', 'test_toolchain_updates.py'),
    ('scripts/modelbench', 'test_resume.py'),
    ('scripts/modelbench', 'test_experiment_configuration.py'),
    ('scripts/modelbench', 'test_heldout_adapter.py'),
]


def sources(root):
    result = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(part in {'.git', 'build', '__pycache__'} for part in relative.parts): continue
        c.require(not path.is_symlink(), 'Unexpected source symlink: ' + str(relative))
        if path.is_file(): result[str(relative)] = c.digest(path)
    return result


def run(root, output):
    c.require(sys.version_info >= (3, 12), 'Package acceptance requires Python3.12+')
    root = c.safe(root); folder = c.private_directory(output)
    identity = {'source': sources(root), 'python': sys.version, 'executable_sha256': c.digest(sys.executable), 'suites': SUITES}
    # Normalize tuples to their serialized JSON form before comparing receipts.
    identity = json.loads(json.dumps(identity))
    with c.locked(folder / 'acceptance.lock'):
        file = folder / 'receipt.json'
        if file.exists():
            result = c.read(file)
            c.require(result['identity'] == identity, 'Package acceptance inputs changed; retain this receipt and choose a new output path')
            c.require(result['status'] in ('PASS', 'FAILED'), 'Previous package check was interrupted; no silent replay')
            for row in result['checks']:
                c.require(c.digest(folder / row['log']) == row['sha256'], 'Package acceptance log changed')
            return dict(result, reused=True)
        receipt = {'schema_version': 1, 'status': 'RUNNING', 'identity': identity, 'started_at': c.timestamp(), 'checks': [],
                   'scope': 'Offline coordinator package tests; no live model/candidate acceptance', 'reused': False}
        c.save(file, receipt)
        started = time.monotonic()
        commands = [('suite-' + str(i), [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', base, '-p', pattern, '-v'])
                    for i, (base, pattern) in enumerate(SUITES)]
        commands += [('scaffold-integrity', [sys.executable, '-B', 'tools/verify_scaffold.py']),
                     ('kolibri-profile', [sys.executable, '-B', 'scripts/kolibri-benchmark.py', 'plan'])]
        for name, argv in commands:
            result = subprocess.run(argv, cwd=root, stdin=subprocess.DEVNULL, capture_output=True, timeout=180)
            data = result.stdout + result.stderr
            c.require(len(data) <= 4 * 1024 * 1024, 'Acceptance log budget exceeded')
            log = name + '.log'; c.atomic_bytes(folder / log, data)
            match = re.search(rb'Ran (\d+) tests?', data)
            skipped = re.search(rb'skipped=(\d+)', data)
            row = {'name': name, 'argv': argv, 'exit_code': result.returncode, 'log': log,
                   'sha256': c.digest(folder / log), 'tests': int(match[1]) if match else None,
                   'skipped': int(skipped[1]) if skipped else 0}
            receipt['checks'].append(row); c.save(file, receipt)
        c.require(sources(root) == identity['source'], 'Source changed while testing')
        receipt.update(status='PASS' if all(r['exit_code'] == 0 and r['skipped'] == 0 for r in receipt['checks']) else 'FAILED',
                       finished_at=c.timestamp(), elapsed_seconds=time.monotonic() - started,
                       tests=sum(r['tests'] or 0 for r in receipt['checks']))
        c.save(file, receipt)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/package-acceptance')
    args = parser.parse_args()
    try:
        result = run(ROOT, args.output)
        print(json.dumps({key: result[key] for key in ('status', 'tests', 'reused', 'scope')}))
        return 0 if result['status'] == 'PASS' else 2
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr); return 2


if __name__ == '__main__': sys.exit(main())
