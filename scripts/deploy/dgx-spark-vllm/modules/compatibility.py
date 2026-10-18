"""Fail closed on account, host, RAM, disk, CUDA, plugin and model mismatch."""
import json
import os
import platform
import shutil
import stat
import sys
import sysconfig
from pathlib import Path
from .common import run, safe_path
from .profiles import ContractError


def memory_info(path=Path("/proc/meminfo")):
    return {line.split(":")[0]: int(line.split()[1]) * 1024
            for line in path.read_text().splitlines() if len(line.split()) >= 2}


def check_memory(model, mem):
    gib = float(1024 ** 3)
    budget = model["memory"]
    estimate = sum(budget[k] for k in ("weights_gib", "kv_estimate_gib", "overhead_gib", "host_reserve_gib"))
    required = max(budget["minimum_available_gib"], estimate)
    swap_used = mem["SwapTotal"] - mem["SwapFree"]
    swap_cached = mem.get("SwapCached", 0)
    nonresident_swap = max(0, swap_used - swap_cached)
    if mem["MemAvailable"] / gib < required:
        raise ContractError("Available RAM {:.2f} GiB < required {:.2f} GiB; context stays {}".format(
            mem["MemAvailable"] / gib, required, model["server"]["max_model_len"]))
    allocation = mem["MemTotal"] / gib * model["server"]["gpu_memory_utilization"]
    resident_estimate = sum(budget[k] for k in ("weights_gib", "kv_estimate_gib", "overhead_gib"))
    if allocation < resident_estimate:
        raise ContractError("Configured GPU budget {:.2f} GiB < estimated model/KV/runtime {:.2f} GiB".format(allocation, resident_estimate))
    if allocation + budget["host_reserve_gib"] > mem["MemAvailable"] / gib:
        raise ContractError("GPU allocation would consume reserved host RAM")
    return {"available_gib": mem["MemAvailable"] / gib, "required_gib": required,
            "gpu_target_gib": allocation, "target_context": model["server"]["max_model_len"],
            "host_swap_used_bytes": swap_used, "host_swap_cached_bytes": swap_cached,
            "host_nonresident_swap_bytes": nonresident_swap,
            "host_swap_warning": bool(nonresident_swap),
            "capacity_proven": False}


def reclaim_owned_cache(ctx):
    """Evict clean pages of this component's files, without global cache/swap changes."""
    count = total = 0
    for root in (ctx.base, ctx.root / "models/huggingface", ctx.root / "tmp/vllm-cache/pip"):
        safe_path(root)
        if not root.exists():
            continue
        for directory, dirs, names in os.walk(str(root), followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
            for name in names:
                path = Path(directory) / name
                if path.is_symlink() or path.stat().st_size < 1024 ** 2:
                    continue
                fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
                        continue
                    os.fdatasync(fd)
                    os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                    count += 1
                    total += info.st_size
                finally:
                    os.close(fd)
    return {"files_advised": count, "file_bytes": total, "method": "POSIX_FADV_DONTNEED", "contents_modified": False}


def host(ctx, starting=False):
    ctx.identity()
    d, m = ctx.defaults, ctx.model
    if not m["enabled"]:
        raise ContractError("Profile blocked: " + m["blocked_reason"])
    if platform.node() != d["hostname"] or platform.machine() != d["architecture"]:
        raise ContractError("Profile host/architecture does not match this machine")
    if sys.version_info[:2] < tuple(map(int, m["compatibility"]["python_min"].split("."))):
        raise ContractError("Deployment interpreter is too old")
    if not (Path(sysconfig.get_path("include")) / "Python.h").is_file() or not shutil.which("gcc"):
        raise ContractError("Triton requires gcc and matching Python development headers (Python.h); install reviewed host prerequisites before deploy")
    if shutil.disk_usage(str(ctx.root)).free < m["memory"]["minimum_disk_gib"] * 1024 ** 3:
        raise ContractError("Insufficient free runtime disk space")
    driver = run(["nvidia-smi", "--query-gpu=name,compute_cap,driver_version", "--format=csv,noheader"], env=ctx.environment()).strip()
    if m["compatibility"]["compute_capability"] not in [x.strip() for x in driver.split(",")]:
        raise ContractError("Unsupported GPU compute capability: " + driver)
    result = {"hostname": platform.node(), "architecture": platform.machine(), "gpu": driver}
    if starting:
        result["cache_advice"] = reclaim_owned_cache(ctx)
        result["memory"] = check_memory(m, memory_info())
    return result


def environment(ctx, python):
    code = '''import importlib.metadata as md, json, sys, torch
import vllm
plugins = [p.name for p in md.entry_points(group="vllm.general_plugins")]
from vllm.plugins import load_general_plugins
load_general_plugins()
from vllm.model_executor.models import ModelRegistry
assert sys.argv[1] in ModelRegistry.get_supported_archs(), "Model architecture is not registered"
import vllm._C_stable_libtorch
import vllm._moe_C_stable_libtorch
from triton.runtime import driver
target = driver.active.get_current_target()  # compiles/loads the native CUDA helper
x = torch.ones((16,16), device="cuda"); y = x @ x; torch.cuda.synchronize()
print(json.dumps({"vllm": md.version("vllm"), "torch": torch.__version__,
 "cuda": torch.version.cuda, "capability": ".".join(map(str,torch.cuda.get_device_capability())),
 "plugins":plugins,"matmul":float(y[0,0]),"triton_target":str(target)}))'''
    run([Path(python).parent / "ninja", "--version"], timeout=30, env=ctx.environment(python))
    output = run([python, "-B", "-c", code, ctx.model["architecture_name"]], timeout=180, env=ctx.environment(python),
                 log=None)
    facts = json.loads(output.strip().splitlines()[-1])
    c = ctx.model["compatibility"]
    if facts["vllm"] != c["vllm_version"] or not facts["cuda"] or int(facts["cuda"].split(".")[0]) != c["torch_cuda_major"] or facts["capability"] != c["compute_capability"] or facts["matmul"] != 16:
        raise ContractError("Installed backend compatibility probe failed: " + json.dumps(facts))
    if ctx.id == "kolibri-1" and "aleph_alpha_inference" not in facts["plugins"]:
        raise ContractError("Kolibri vLLM plugin entrypoint is missing")
    jit = run([python, "-B", ctx.package / "modules/gpu_probe.py"], timeout=180,
              env=ctx.environment(python))
    facts["jit_probe"] = json.loads(jit.strip().splitlines()[-1])
    return facts


def cuda_budget(ctx, python):
    code = "import torch,json; print(json.dumps(dict(zip(['free','total'],torch.cuda.mem_get_info()))))"
    facts = json.loads(run([python, "-B", "-c", code], timeout=120, env=ctx.environment(python)).strip().splitlines()[-1])
    required = facts["total"] * ctx.model["server"]["gpu_memory_utilization"]
    if facts["free"] < required:
        raise ContractError("CUDA free memory {:.2f} GiB < requested allocation {:.2f} GiB; context remains {}".format(
            facts["free"] / 1024 ** 3, required / 1024 ** 3, ctx.model["server"]["max_model_len"]))
    return dict(facts, required_bytes=required)


def model_config(ctx, config):
    m = ctx.model
    if m["architecture_name"] not in config.get("architectures", []):
        raise ContractError("Downloaded architecture differs from pinned profile")
    if config.get("max_position_embeddings", 0) < m["server"]["max_model_len"]:
        raise ContractError("Checkpoint does not support requested context; no automatic reduction")
    if config.get("quantization_config", {}).get("quant_method") != m["quantization"]:
        raise ContractError("Checkpoint quantization differs from profile")
