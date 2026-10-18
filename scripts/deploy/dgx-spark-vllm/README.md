# DGX Spark vLLM lifecycle and calibration

This package manages Kolibri/vLLM releases and systemd services on a DGX Spark host. See the [bootstrap guide](../README.md) for host prerequisites,
the complete script tree and original-project inputs missing from this import.
The portable entrypoint is `python3 -B scripts/bootstrap.py --kolibri --calibration on --on`
from the repository root. It generates account-specific profiles and its own
calibration. Direct legacy examples below still refer to the original project.

## Folder tree

```text
dgx-spark-vllm/
|-- README.md
|-- vllmctl.py
|-- calibrate.py
|-- calibrate-worker.py
|-- export-calibration.py
|-- scale-loader-preflight.py
|-- config/
|   |-- defaults.json
|   `-- schema.json
|-- models/
|   |-- kolibri-1.json
|   `-- mistral-small-4.json
|-- modules/
|   |-- profiles.py
|   |-- common.py
|   |-- privileged.py
|   |-- compatibility.py
|   |-- environment.py
|   |-- deployment.py
|   |-- lifecycle.py
|   |-- launch.py
|   |-- verifier.py
|   |-- gpu_probe.py
|   |-- calibration.py
|   `-- calibration_worker.py
|-- scripts/
|   `-- bootstrap.sh
`-- tests/
    |-- test_lifecycle.py
    `-- test_calibration.py
```

## Entrypoints

| Script | What it does | How it is used |
| --- | --- | --- |
| [vllmctl.py](vllmctl.py) | Validates the selected JSON profile, checks account/host/resources and manages the model service. Deployment stages a release before cutover; failures preserve evidence and use the owned rollback transaction. | `deploy`, `start`, `stop`, `restart`, `status`, `verify`, followed by the model ID. `verify --long-context` also sends a full-capacity request. |
| [scripts/bootstrap.sh](scripts/bootstrap.sh) | Small shell shortcut for `vllmctl.py deploy`, defaulting to `kolibri-1`. | `bash .../scripts/bootstrap.sh kolibri-1`; it performs deployment, not just prerequisite checks. |
| [calibrate.py](calibrate.py) | Locks lifecycle/benchmarks, prepares inputs, stops the baseline for GPU observation, creates a retained scale overlay and restores the baseline service. | Advanced operation with `--spec PATH`; requires the original calibration specification, checkpoint and baseline environment. |
| [calibrate-worker.py](calibrate-worker.py) | Prepares/tokenizes synthetic inputs with `--prepare`; otherwise loads vLLM and collects GPU observations through named observer RPCs. | Internal child of `calibrate.py`, with `--job PATH`; normal observation allocates GPU memory and runs inference. |
| [export-calibration.py](export-calibration.py) | Derives a new BF16-exact or KV-only scale overlay from retained observations, verifies the pinned parent and preserves provenance. | Advanced operation with `--spec`, `--source-manifest` and `--source-sha256`. Does not rerun model inference. |
| [scale-loader-preflight.py](scale-loader-preflight.py) | Uses the installed vLLM parameter loader on CPU to verify that all 200 exported scales load exactly. Writes a new receipt. | Run inside the qualified model environment with `--scales PATH --output PATH`; requires installed Torch/vLLM but no GPU weights. |

The public [wrapper](../../bootstrap.py) handles per-account installation and
calibration reuse. The legacy [kolibri.py](../kolibri.py) retains its original
V5/acceptance-helper contract and should be used only with that original project.

## Internal modules

| Module | Responsibility |
| --- | --- |
| [profiles.py](modules/profiles.py) | Strict JSON parsing/schema validation, profile loading and source fingerprints. |
| [privileged.py](modules/privileged.py) | Inherited socket transport for bounded root requests during the wrapper job; model/package subprocesses do not inherit it. |
| [common.py](modules/common.py) | Owned runtime paths, identity, environment, lifecycle lock, atomic records and bounded subprocesses. |
| [compatibility.py](modules/compatibility.py) | Host/architecture, physical RAM, GPU, dependency and model metadata checks. |
| [environment.py](modules/environment.py) | Release virtualenv/dependencies, pinned model download, shard validation and retained source. Calibrated releases reuse the pinned baseline environment. |
| [deployment.py](modules/deployment.py) | Deployment staging, journaled service cutover, recovery and rollback. |
| [lifecycle.py](modules/lifecycle.py) | Service ownership, port checks, unit installation and server arguments. |
| [launch.py](modules/launch.py) | Systemd-launched model server process. |
| [verifier.py](modules/verifier.py) | HTTP health, model/context identity, short semantic completion and optional full-context verification. |
| [gpu_probe.py](modules/gpu_probe.py) | Executes a compiled Triton GPU kernel before expensive model loading. |
| [calibration.py](modules/calibration.py) | Synthetic prompts, scale calculation/export, manifest checks and observer helpers. |
| [calibration_worker.py](modules/calibration_worker.py) | vLLM observer extension and calibrated worker attestation of loaded scales. |

## Profiles and target

[defaults.json](config/defaults.json) selects `validatus`, `spark-a922`, ARM64
and `/home/validatus/workspace/AI-Model/runtime/spark-a922`.
[schema.json](config/schema.json) validates the profiles.
[kolibri-1.json](models/kolibri-1.json) enables the pinned Kolibri checkpoint
with 262,144 tokens, one sequence, FP8 weights and FP8 KV. It points to the
original sealed V5 calibration manifest and retained baseline release; neither
asset is included in this archive.
[mistral-small-4.json](models/mistral-small-4.json) is disabled. It does not
configure or replace the existing AMD/ROCm llama-server endpoint.

Generated releases, locks and journals live under
`runtime/spark-a922/build/dgx-spark-vllm/`; model snapshots under
`runtime/spark-a922/models/huggingface/`; logs under
`runtime/spark-a922/logs/dgx-spark-vllm/`. A virtualenv isolates Python packages;
coding-worker filesystem and network isolation are separate benchmark controls.

## Commands on the matching Spark

Run as `validatus` from `/home/validatus/workspace/AI-Model`. Standalone legacy controller calls use noninteractive sudo. Through the new
wrapper, the controller instead uses the already authenticated root supervisor;
it still runs under the selected normal account. Use the approved persistent remote session.

```bash
python3 -B scripts/deploy/dgx-spark-vllm/vllmctl.py status kolibri-1
```

```bash
python3 -B scripts/deploy/kolibri.py deploy
```

```bash
python3 -B scripts/deploy/dgx-spark-vllm/vllmctl.py verify kolibri-1
```

```bash
python3 -B scripts/deploy/dgx-spark-vllm/vllmctl.py verify kolibri-1 --long-context
```

`status` reads state; `verify` sends requests and writes evidence. The long
check requests 262,112 input tokens plus 32 output tokens. Capacity verification
does not establish parser accuracy. `start`, `stop` and `restart` act on the
owned service. The direct controller does not enable boot persistence; the portable wrapper
enables the owned model service for `--on` and disables it for `--off`.

The [lifecycle tests](tests/test_lifecycle.py) and
[calibration tests](tests/test_calibration.py) exercise offline fixtures and
mock service/GPU behavior; see the parent guide for local test commands.
