#!/usr/bin/env python3
"""Derive a BF16-exact scale overlay from immutable completed observations.

Run as validatus: python3 -B export-calibration.py --spec /.../config/kolibri-calibration.json
--source-manifest /.../manifest.json --source-sha256 HEX.
Flow: owned lifecycle lock -> verify parent/unchanged observation policy -> retain
raw inputs/ranges/source -> round scales upward -> new overlay/manifest. No model
stop, inference, dependency install, data overwrite or benchmark access.
"""
import argparse
import fcntl
import json
from pathlib import Path
import re
import shutil
import subprocess
from modules.common import Context, atomic_json, now
from modules.profiles import ContractError, load, read_json
from modules.calibration import digest, scales, export_bf16_scales, export_kv_only_scales, validate_manifest
from modules import lifecycle, verifier
from calibrate import create_overlay


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--spec', type=Path, required=True)
    ap.add_argument('--source-manifest', type=Path, required=True)
    ap.add_argument('--source-sha256', required=True)
    args = ap.parse_args()
    package = Path(__file__).resolve().parent
    ctx = Context(package, load(package, 'kolibri-1'))
    spec = read_json(args.spec)
    if spec != read_json(package.parents[2] / 'config/kolibri-calibration.json'):
        raise ContractError('Use the maintained export specification')
    if not re.fullmatch('[a-z0-9-]+', spec['experiment']) or spec.get('scale_storage_dtype') != 'bfloat16' or spec.get('scale_rounding') != 'toward_positive_infinity':
        raise ContractError('Unsupported scale export policy')
    parent_spec = ctx.model['kv_calibration']
    if str(args.source_manifest) != parent_spec['manifest'] or args.source_sha256 != parent_spec['sha256']:
        raise ContractError('Use the pinned parent calibration')
    with ctx.locked(), (ctx.root / 'tools/benchmark/benchmark.lock').open('a') as benchmark_lock:
        fcntl.flock(benchmark_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (ctx.root / 'tools/benchmark/active-run.json').exists():
            raise ContractError('Review an active/interrupted benchmark before export')
        parent = validate_manifest(args.source_manifest, args.source_sha256, ctx.model['revision'], verify_weights=False)
        strip = lambda x: {k: v for k, v in x.items() if k not in (
            'experiment', 'scale_storage_dtype', 'scale_rounding', 'scale_scope', 'backend_compatibility')}
        if strip(spec) != strip(parent['spec']):
            raise ContractError('Observation policy drift; export cannot change inputs or budgets')
        previous = lifecycle.managed(ctx)
        if previous != parent['baseline'] or lifecycle.service_state(ctx)['ActiveState'] != 'active':
            raise ContractError('Wait for verified original-service recovery')
        verifier.health(ctx)
        source = args.source_manifest.parent
        observations = read_json(source / 'observations.json')
        raw = scales(observations['observations'], spec['margin'], spec['fp8_max'])
        if parent['scales'] not in (raw, export_bf16_scales(raw)) or raw != observations['scales']:
            raise ContractError('Parent does not match original observed ranges')
        exported = export_bf16_scales(raw)
        diagnostic_path = None
        if spec.get('scale_scope') == 'kv-only-bf16-query':
            evidence = spec['backend_compatibility']
            diagnostic_path = Path(evidence['path'])
            if diagnostic_path.is_symlink() or digest(diagnostic_path) != evidence['sha256']:
                raise ContractError('Backend diagnostic changed')
            backend = read_json(diagnostic_path)
            if (backend['status'] != 'BF16_QUERY_NONUNITY_SCALE_PREFILL_MISMATCH'
                    or backend['query_dtype_replay']['121'] != {'prefill': 'torch.bfloat16', 'decode': 'torch.bfloat16'}
                    or backend['cuda_initialized'] or backend['gpu_weights_loaded']):
                raise ContractError('Expected the retained CPU-only SM121 compatibility proof')
            original_venv = (Path(parent['baseline']['release']) / 'venv').resolve()
            for name, row in backend['files'].items():
                target = Path(name)
                target.resolve().relative_to(original_venv)
                if digest(target) != row['sha256'] or target.stat().st_size != row['bytes']:
                    raise ContractError('Installed backend changed after compatibility diagnosis')
            exported = export_kv_only_scales(raw)
        elif spec.get('scale_scope') is not None:
            raise ContractError('Unknown scale export scope')
        folder = ctx.base / 'calibration' / spec['experiment']
        folder.mkdir(mode=0o700, exist_ok=False)
        for name in ('inputs.json', 'prepared-inputs.json', 'observations.json'):
            shutil.copy2(source / name, folder / name)
        diagnostic = ctx.base / 'calibration/scale-dtype-preflight-v1.log'
        if not diagnostic.is_file() or 'CPU_VENDOR_PARAMETER_ROUNDING_REPRODUCED' not in diagnostic.read_text():
            raise ContractError('Retained native loader preflight required')
        shutil.copy2(diagnostic, folder / 'loader-preflight.log')
        if diagnostic_path:
            shutil.copy2(diagnostic_path, folder / 'backend-compatibility.json')
        job = read_json(source / 'job.json')
        job.update(spec=spec, derived_at=now(), derived_from={'manifest': str(args.source_manifest), 'sha256': args.source_sha256})
        shutil.copytree(package, folder / 'source', ignore=shutil.ignore_patterns('tests', '__pycache__', '*.pyc'))
        job['source_sha256'] = {p.relative_to(folder / 'source').as_posix(): digest(p) for p in (folder / 'source').rglob('*') if p.is_file()}
        atomic_json(folder / 'job.json', job)
        atomic_json(folder / 'export-derivation.json', {'parent': job['derived_from'], 'observations_sha256': digest(folder / 'observations.json'),
            'raw_scales': raw, 'exported_scales': exported, 'storage_dtype': 'bfloat16', 'rounding': 'toward_positive_infinity',
            'additional_inference_requests': 0, 'scale_scope': spec.get('scale_scope', 'qkv-prob'),
            'reason': ('SM121 uses BF16 queries; retain Q/probability unit scales and unchanged observed K/V ranges.'
                       if diagnostic_path else 'Installed vLLM creates scale parameters under the model BF16 default dtype.')})
        python = Path(previous['release']) / 'venv/bin/python'
        atomic_json(folder / 'scales.json', exported)
        subprocess.run([str(python), '-B', str(folder / 'source/scale-loader-preflight.py'),
                        '--scales', str(folder / 'scales.json'), '--output', str(folder / 'loader-exact-preflight.json')],
                       env=ctx.environment(python), check=True, timeout=120)
        create_overlay(folder, job, {'scales': exported}, python, ctx.environment(python))
        print(json.dumps({'manifest': str(folder / 'manifest.json'), 'sha256': digest(folder / 'manifest.json'),
                          'status': 'DERIVED_KV_ONLY_BF16_EXACT_SCALES' if diagnostic_path else 'DERIVED_BF16_EXACT_SCALES',
                          'additional_inference_requests': 0}))


if __name__ == '__main__':
    main()
