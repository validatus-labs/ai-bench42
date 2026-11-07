"""Public vLLM worker-class extension: attest loaded scales, fail startup closed."""
from pathlib import Path
import os
from vllm.v1.worker.gpu_worker import Worker
from .calibration import check_loaded, validate_manifest
from .common import atomic_json, now


class ObserverExtension:
    """Named RPCs avoid enabling vLLM's insecure callable/pickle fallback."""
    def calibration_begin(self):
        from .calibration import install_observers
        return install_observers(self.model_runner.get_model())

    def calibration_end(self):
        from .calibration import collect_observations
        return collect_observations(self.model_runner.get_model())


class CalibratedWorker(Worker):
    def load_model(self, *, load_dummy_weights=False):
        if load_dummy_weights:
            raise RuntimeError("Dummy weights cannot attest calibration")
        super().load_model(load_dummy_weights=False)
        release = Path.cwd()
        import json
        profile = json.loads((release / "profile.json").read_text())
        spec = profile["model"]["kv_calibration"]
        # Full shard hashing occurs before exec in the launcher; do not page
        # 79GB back into host cache after model allocation inside the worker.
        manifest = validate_manifest(spec["manifest"], spec["sha256"], profile["model"]["revision"], verify_weights=False)
        model = self.model_runner.get_model()
        actual = check_loaded(model, manifest["scales"])
        backend = None
        if manifest.get("scale_scope") == "kv-only-bf16-query":
            import torch
            from types import SimpleNamespace
            from vllm.config import set_current_vllm_config
            from vllm.v1.attention.backends.flashinfer import FlashInferMetadataBuilder
            if torch.cuda.get_device_capability() != (12, 1):
                raise RuntimeError("This KV-only compatibility contract is specific to SM121")
            config = self.vllm_config
            selector = SimpleNamespace(vllm_config=config, model_config=config.model_config,
                                       cache_dtype=config.cache_config.cache_dtype,
                                       kv_cache_spec=SimpleNamespace(dtype=config.model_config.dtype))
            with set_current_vllm_config(config):
                dtypes = {name: str(FlashInferMetadataBuilder.get_q_data_type(selector, phase))
                          for name, phase in (("prefill", True), ("decode", False))}
            if dtypes != {"prefill": "torch.bfloat16", "decode": "torch.bfloat16"}:
                raise RuntimeError("Actual worker query dtype is incompatible with the KV-only export")
            modules = dict(model.named_modules())
            implementations = {type(modules[name].impl).__name__ for name in manifest["scales"]}
            if implementations != {"FlashInferImpl"} or any(
                    modules[name].impl.supports_quant_query_input for name in manifest["scales"]):
                raise RuntimeError("Expected unquantized-query FlashInfer attention")
            backend = {"compute_capability": [12, 1], "scale_scope": "kv-only-bf16-query",
                       "implementations": sorted(implementations), "query_dtype_selector": dtypes,
                       "selector_uses_actual_worker_config_and_platform": True,
                       "forward_tensors_traced": False, "query_and_probability_scales": 1.0}
        atomic_json(release / "loaded-calibration.json", {"observed_at": now(),
                    "manifest_sha256": spec["sha256"], "scales": actual,
                    "status": "ALL_200_SCALES_LOADED", "rank": self.rank,
                    "worker_pid": os.getpid(), "cgroup": Path("/proc/self/cgroup").read_text().strip(),
                    "backend_compatibility": backend})
