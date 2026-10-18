"""Static Q/K/V absmax calibration; no vendor edits or benchmark input access.

The observer sees post-normalization/post-RoPE tensors entering Attention.
This is a project calibration method, not an llm-compressor qualification.
"""
import hashlib
import json
import math
import struct
from pathlib import Path
from .profiles import ContractError, read_json


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prompts(spec):
    """Authored synthetic development inputs; no evaluation or private data."""
    themes = {
        "en": "Summarize the following fictional engineering records and explain consistency checks.",
        "de": "Fasse die folgenden erfundenen technischen Datensätze zusammen und erkläre Konsistenzprüfungen.",
        "fr": "Résume les données techniques fictives suivantes et explique les contrôles de cohérence.",
        "code": "Review these synthetic Python records. Explain validation, types and error handling."
    }
    result = []
    for n in range(spec["samples"]):
        lang = spec["languages"][n % 4]
        rows = [json.dumps({"record": j, "batch": n, "value": (j * 37 + n * 19) % 997,
                            "unit": "milliseconds", "valid": j % 7 != 0,
                            "description": "fictional calibration observation, not personal data"}, sort_keys=True)
                for j in range(128)]
        result.append({"id": "synthetic-" + lang + "-" + str(n), "language": lang,
                       "text": themes[lang] + "\n" + "\n".join(rows)})
    return result


def scales(observations, margin, fp8_max):
    if len(observations) != 50 or not 1 <= margin <= 2 or fp8_max != 448:
        raise ContractError("Wrong layer count or scale policy")
    result = {}
    for name, row in observations.items():
        if not name.startswith("model.layers.") or not name.endswith(".self_attn.attn"):
            raise ContractError("Unexpected attention path")
        if row["calls"] < 32 or row["tokens"] < 32 * 2048:
            raise ContractError("Incomplete observed attention coverage")
        result[name] = {}
        for field in ("q", "k", "v"):
            value = row["absmax"][field]
            if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                raise ContractError("Invalid activation maximum")
            result[name][field + "_scale"] = value * margin / fp8_max
        # Softmax probabilities have the mathematical bound [0,1]. This is
        # an analytical bound, explicitly not a measured probability maximum.
        result[name]["prob_scale"] = 1.0 / fp8_max
    if all(row["k_scale"] == 1 and row["v_scale"] == 1 for row in result.values()):
        raise ContractError("Calibration did not change any KV scale")
    return result


def export_bf16_scales(values):
    """Round positive scales upward to BF16; keep the headroom/probability bound."""
    result = {}
    for name, row in values.items():
        result[name] = {}
        for field, value in row.items():
            if not math.isfinite(value) or value <= 0:
                raise ContractError("Invalid scale export")
            bits = struct.unpack(">I", struct.pack(">f", value))[0] >> 16
            rounded = struct.unpack(">f", struct.pack(">I", bits << 16))[0]
            if rounded < value:
                bits += 1
                rounded = struct.unpack(">f", struct.pack(">I", bits << 16))[0]
            if not math.isfinite(rounded) or rounded < value or rounded / value > 1.008:
                raise ContractError("Unrepresentable BF16 calibration scale")
            result[name][field] = rounded
    return result


def export_kv_only_scales(values):
    """BF16 queries/probabilities are not FP8 operands: retain their unit scales.

    K/V retain exactly the same upward-rounded observed ranges. This changes
    the export scope, never the observations, headroom or evaluation inputs.
    """
    if len(values) != 50 or any(set(row) != {"q_scale", "k_scale", "v_scale", "prob_scale"}
                                for row in values.values()):
        raise ContractError("Incomplete KV-only scale export")
    exported = export_bf16_scales(values)
    for row in exported.values():
        row.update(q_scale=1.0, prob_scale=1.0)
    return exported


def install_observers(model):
    import torch
    from vllm.model_executor.layers.attention import Attention
    names = []
    for name, module in model.named_modules():
        if not isinstance(module, Attention):
            continue
        module._calibration_maxima = torch.zeros(3, device="cuda", dtype=torch.float32)
        module._calibration_calls = module._calibration_tokens = 0

        def observe(layer, args):
            q, k, v = args[:3]
            values = torch.stack([x.detach().abs().amax().float() for x in (q, k, v)])
            layer._calibration_maxima.copy_(torch.maximum(layer._calibration_maxima, values))
            layer._calibration_calls += 1
            layer._calibration_tokens += int(q.shape[0])
        module.register_forward_pre_hook(observe)
        names.append(name)
    if len(names) != 50:
        raise RuntimeError("Expected 50 attention observers, got " + str(len(names)))
    return names


def collect_observations(model):
    result = {}
    for name, module in model.named_modules():
        if hasattr(module, "_calibration_maxima"):
            result[name] = {"absmax": dict(zip(("q", "k", "v"), module._calibration_maxima.cpu().tolist())),
                            "calls": module._calibration_calls, "tokens": module._calibration_tokens}
    return result


def check_loaded(model, expected):
    modules = dict(model.named_modules())
    actual = {}
    for name, values in expected.items():
        layer = modules[name]
        actual[name] = {}
        for field, value in values.items():
            observed = float(getattr(layer, "_" + field).item())
            if not math.isclose(observed, value, rel_tol=1e-6, abs_tol=1e-9):
                raise RuntimeError("Loaded calibration mismatch: " + name + "." + field +
                                   " expected=" + repr(value) + " actual=" + repr(observed))
            actual[name][field] = observed
        # Triton/other attention backends can consume the CPU copies.
        for field in ("k", "v", "q"):
            observed = float(getattr(layer, "_" + field + "_scale_float"))
            if not math.isclose(observed, values[field + "_scale"], rel_tol=1e-6, abs_tol=1e-9):
                raise RuntimeError("Host scale copy mismatch: " + name)
    if len(actual) != 50:
        raise RuntimeError("Incomplete loaded scale attestation")
    return actual


def validate_manifest(path, expected_sha, revision, verify_weights=True):
    path = Path(path)
    if path.is_symlink() or digest(path) != expected_sha:
        raise ContractError("Calibration manifest changed")
    result = read_json(path)
    if result["revision"] != revision or result["status"] != "CALIBRATED" or len(result["scales"]) != 50:
        raise ContractError("Calibration identity/status mismatch")
    if result.get("scale_scope") == "kv-only-bf16-query":
        if result["spec"].get("scale_scope") != "kv-only-bf16-query" or any(
                row.get("q_scale") != 1.0 or row.get("prob_scale") != 1.0 for row in result["scales"].values()):
            raise ContractError("BF16-query export must retain unit Q/probability scales")
    root = path.parent.resolve()
    snapshot = Path(result["snapshot"])
    if snapshot.parent.resolve() != root or snapshot.is_symlink():
        raise ContractError("Calibration snapshot outside owned artifact")
    for rel, checksum in result["files"].items():
        target = root / rel
        target.resolve().relative_to(root)
        if target.is_symlink() or digest(target) != checksum:
            raise ContractError("Calibration artifact changed: " + rel)
    source = Path(result["source_snapshot"]).resolve()
    expected_source = path.resolve().parents[4] / "models/huggingface/hub/models--Aleph-Alpha--Kolibri-1/snapshots" / revision
    if source != expected_source:
        raise ContractError("Calibration source is not the pinned Kolibri snapshot")
    links = result["linked_files"]
    for member in snapshot.iterdir():
        if member.name not in ("model.safetensors.index.json", "calibration.safetensors"):
            if not member.is_symlink() or member.resolve() != (source / member.name).resolve():
                raise ContractError("Unexpected overlay member")
    for name, row in links.items():
        if Path(name).name != name:
            raise ContractError("Invalid checkpoint member")
        link = snapshot / name
        if not link.is_symlink() or link.resolve() != Path(row["target"]) or link.resolve() != (source / name).resolve():
            raise ContractError("Original checkpoint link diverged")
        if (verify_weights or not row["weight_shard"]) and digest(link) != row["sha256"]:
            raise ContractError("Original checkpoint bytes changed")
    return result
