#!/usr/bin/env python3
"""CPU input preparation and offline GPU observer for the locked calibrate.py job."""
import argparse
import json
from pathlib import Path
from modules.calibration import prompts, scales, digest, export_bf16_scales, export_kv_only_scales
from modules.common import atomic_json, now


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--job", required=True, type=Path)
    ap.add_argument("--prepare", action="store_true", help="Validate all tokenized inputs without loading GPU weights")
    args = ap.parse_args()
    job = json.loads(args.job.read_text())
    spec = job["spec"]
    prepared_path = args.job.parent / "prepared-inputs.json"
    if args.prepare:
        from vllm.plugins import load_general_plugins
        load_general_plugins()
        from vllm.tokenizers import get_tokenizer
        tokenizer = get_tokenizer(job["snapshot"])
        inputs, receipts = [], []
        import hashlib
        for row in prompts(spec):
            ids = tokenizer.apply_chat_template([{"role": "user", "content": row["text"]}],
                                               add_generation_prompt=True, tokenize=True, return_dict=False)
            if not isinstance(ids, list) or len(ids) < spec["input_tokens"] or any(type(i) is not int or i < 0 or i >= len(tokenizer) for i in ids):
                raise RuntimeError("Expected a complete flat token-ID sequence")
            ids = ids[:spec["input_tokens"] - 64] + ids[-64:]
            if len(ids) != spec["input_tokens"]:
                raise RuntimeError("Incomplete calibration prompt")
            inputs.append({"prompt_token_ids": ids})
            receipts.append({"id": row["id"], "language": row["language"], "input_tokens": len(ids),
                             "input_ids_sha256": hashlib.sha256(json.dumps(ids).encode()).hexdigest()})
        atomic_json(prepared_path, {"spec": spec, "inputs": inputs, "receipts": receipts,
                    "tokenizer_class": str(type(tokenizer)), "return_dict": False, "status": "ALL_INPUTS_VALIDATED"})
        print(json.dumps({"status": "ALL_INPUTS_VALIDATED", "inputs": len(inputs), "tokens_each": spec["input_tokens"], "gpu_weights_loaded": False}))
        return
    if digest(prepared_path) != job["prepared_inputs_sha256"]:
        raise RuntimeError("Prepared calibration inputs changed")
    prepared = json.loads(prepared_path.read_text())
    if prepared["spec"] != spec or prepared["status"] != "ALL_INPUTS_VALIDATED" or len(prepared["inputs"]) != spec["samples"]:
        raise RuntimeError("Unvalidated calibration inputs")
    inputs, receipts = prepared["inputs"], prepared["receipts"]
    from vllm import LLM, SamplingParams
    llm = LLM(model=job["snapshot"], max_model_len=262144, max_num_seqs=1,
              kv_cache_dtype="auto", gpu_memory_utilization=0.8,
              max_num_batched_tokens=8192, enforce_eager=True,
              enable_prefix_caching=False, enable_chunked_prefill=True,
              worker_extension_cls="modules.calibration_worker.ObserverExtension")
    # Named methods use secure built-in message serialization.
    llm.collective_rpc("calibration_begin", timeout=120)
    # No hidden benchmark rows, labels, mail or model-generated calibration data.
    for item, receipt in zip(inputs, receipts):
        output = llm.generate([item], SamplingParams(temperature=0, seed=42,
                              max_tokens=spec["output_tokens"], ignore_eos=True), use_tqdm=False)[0]
        receipt["generated_tokens"] = len(output.outputs[0].token_ids)
        if receipt["generated_tokens"] != spec["output_tokens"]:
            raise RuntimeError("Incomplete calibration decode")
        print(json.dumps({"sample": receipt["id"], "generated_tokens": receipt["generated_tokens"]}), flush=True)
    observations = llm.collective_rpc("calibration_end", timeout=120)
    if len(observations) != 1:
        raise RuntimeError("Expected one calibration worker")
    unrounded = scales(observations[0], spec["margin"], spec["fp8_max"])
    exported = export_bf16_scales(unrounded) if spec.get("scale_storage_dtype") == "bfloat16" else unrounded
    if spec.get("scale_scope") == "kv-only-bf16-query":
        exported = export_kv_only_scales(unrounded)
    result = {"observed_at": now(), "spec": spec, "inputs": receipts,
              "observations": observations[0], "scales": exported, "unrounded_scales": unrounded,
              "kv_dtype_during_observation": "auto", "prob_scale_basis": "analytical softmax upper bound 1/448"}
    atomic_json(args.job.parent / "observations.json", result)


if __name__ == "__main__":
    main()
