#!/usr/bin/env python3
"""CPU-only test of installed vLLM scale loading before a costly model restart.

Run in the qualified model venv: --scales /.../scales.json --output /.../receipt.json
Flow: positive BF16-exact scales -> real vendor parameter loader/postprocessing
for50CPU layers -> compare200scales and host copies -> new receipt, or fail.
No GPU allocation, model weights, service change, inference or package mutation.
"""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from modules.calibration import check_loaded, digest
from modules.common import atomic_json, now


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--scales', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    if args.output.exists():
        raise RuntimeError('Existing loader proof is preserved')
    import torch
    import vllm.model_executor.layers.quantization.kv_cache as vendor
    values = json.loads(args.scales.read_text())
    modules = []
    torch.set_default_dtype(torch.bfloat16)
    for name, row in values.items():
        layer = torch.nn.Module()
        layer.kv_cache_dtype = 'fp8'
        for field in ('q', 'k', 'v', 'prob'):
            setattr(layer, '_' + field + '_scale', torch.tensor(1., dtype=torch.float32, device='cpu'))
        layer._k_scale_cpu = torch.tensor(1., dtype=torch.float32, device='cpu')
        layer._v_scale_cpu = torch.tensor(1., dtype=torch.float32, device='cpu')
        method = vendor.BaseKVCacheMethod(None)
        with torch.device('cpu'):
            method.create_weights(layer)
        for field, value in row.items():
            parameter = getattr(layer, field)
            if parameter.dtype != torch.bfloat16:
                raise RuntimeError('Unexpected vendor scale parameter dtype')
            vendor.KVCacheScaleParameter.weight_loader(parameter, torch.tensor(value, dtype=torch.float32, device='cpu'))
        method.process_weights_after_loading(layer)
        if float(layer._k_scale_cpu) != row['k_scale'] or float(layer._v_scale_cpu) != row['v_scale']:
            raise RuntimeError('Vendor CPU scale copy differs')
        modules.append((name, layer))
    actual = check_loaded(SimpleNamespace(named_modules=lambda: modules), values)
    atomic_json(args.output, {'status': 'ALL_200_VENDOR_CPU_SCALES_EXACT', 'observed_at': now(),
                'scales_sha256': digest(args.scales), 'vendor_file_sha256': digest(vendor.__file__),
                'parameter_dtype': 'torch.bfloat16', 'layers': len(actual), 'gpu_weights_loaded': False})
    print(json.dumps({'status': 'ALL_200_VENDOR_CPU_SCALES_EXACT', 'layers': len(actual), 'gpu_weights_loaded': False}))


if __name__ == '__main__':
    main()
