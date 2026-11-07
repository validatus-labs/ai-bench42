#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Probe actual Triton compilation/execution in the selected release virtualenv.

Run as the deployment user with controller-supplied runtime cache environment:
<release>/venv/bin/python -B <source>/modules/gpu_probe.py
No model inputs; effects are a tiny GPU allocation and owned compiler caches.
  Python headers + compiler -> Triton CUDA JIT -> add-one kernel -> JSON / fail
"""
import json
import torch
import triton
import triton.language as tl


@triton.jit
def _add_one(source, destination, count: tl.constexpr, block: tl.constexpr):
    offsets = tl.program_id(0) * block + tl.arange(0, block)
    values = tl.load(source + offsets, offsets < count, other=0)
    tl.store(destination + offsets, values + 1, offsets < count)


def main():
    source = torch.ones(1024, device="cuda", dtype=torch.float32)
    destination = torch.empty_like(source)
    _add_one[(4,)](source, destination, source.numel(), block=256)
    torch.cuda.synchronize()
    if not bool(torch.all(destination == 2).item()):
        raise RuntimeError("Triton JIT kernel returned an incorrect result")
    print(json.dumps({"triton_jit": True, "elements": 1024, "expected": 2.0,
                      "observed": float(destination[0].item())}))


if __name__ == "__main__":
    main()
