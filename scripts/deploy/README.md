# Bootstrap tools: one wrapper

For **deployment → standard benchmarks → coding task → one report**, use the
[experiment controller](../../docs/PIPELINE.md). The commands below also work
independently when you only want host setup or installation verification.

Use [scripts/bootstrap.py](../bootstrap.py) to select the tools you want. Start
it as your existing normal account. It reads the account name, UID, primary
and supplementary groups and home directory from the operating system;
`$USER` and a particular account name are not required.

Preview first, from the repository root:

```bash
python3 -B scripts/bootstrap.py --brave --playwright --maintenance --health --kolibri --calibration on --plan
```

Run the installation on the **Ubuntu 24.04 ARM64 NVIDIA DGX Spark OEM host**:

```bash
python3 -B scripts/bootstrap.py --brave --playwright --maintenance --health --kolibri --calibration on --on
```

Run a long installation in the approved persistent screen session. The wrapper
requests sudo once to start a root-owned systemd supervisor. That supervisor
survives a terminal disconnect. Its user phase drops to the original account;
package installs in model virtualenvs, npm, browser tools and inference run as
that user. A temporary inherited socket accepts only bounded operations for
`ai-model-vllm-kolibri-1.service`. Inference/package subprocesses do not inherit
that socket. No password is stored, no sudo timestamp refresh loop is needed,
and no passwordless sudoers rule or new user is created.

Without sudo rights, `--plan` still works. `--on`/`--off` require permission to
start the root supervisor. An authentication failure leaves only the private
job request. Existing systemd root-command restrictions may require an
administrator to authorize this installation command.

## Flags and examples

The [health monitoring guide](HEALTH-README.md) explains why the health
endpoint exists, its 16 checks, `/healthz` versus `/metrics`, and daily use.

Inspect a partial installation or verify the running stack:

```bash
python3 -B scripts/bootstrap.py --inspect
python3 -B scripts/bootstrap.py --verify --output build/installation-check
```

`--inspect` reads current state without installation or inference. `--verify`
adds real generation and browser/model tool canaries, writes private evidence,
and renews tool qualification. Both use the installed configuration. Without
component flags they select the complete stack; use the original
`--runtime-root` for custom paths. Missing or incompatible components produce
exit 2. Health warning/unknown/critical observations remain visible; `/healthz`
freshness alone is not model health. Details are in the
[pipeline guide](../../docs/PIPELINE.md#3-inspect-an-existing-or-partial-installation).

| Flag | `--on` | `--off` |
| --- | --- | --- |
| `--brave` | Install native Brave if absent; retain an existing installation. | Keep the browser package; no uninstall or process termination. |
| `--playwright` | Build or reuse a qualified Brave/Node/MCP release and write a Kilo client fragment. The selected local model must be available for qualification. | Disable the generated client fragment for future client sessions; keep the tool and existing sessions. |
| `--maintenance` | Install/enable security/weekly APT timers plus the separate toolchain update hook, service/path/timer. | Stop/disable owned maintenance and update jobs. Existing packages, releases and APT policy remain. |
| `--health` | Install/enable the 16-check health timer and loopback exporter. | Stop the checker/exporter and disable the timer/exporter. Retain observations and configuration. |
| `--retention 7\|30\|90\|180\|365\|forever` | With `--health`, set local history retention; default 30 days on first installation, otherwise preserve the saved setting. `never` and `--never` mean `forever`. | Not combined with `--off`; stopped monitoring preserves history. |
| `--vllm` | Prepare and verify the pinned engine environment without downloading/loading model weights. | Stop/disable an owned Kolibri service, if present; retain the engine and models. |
| `--kolibri` | Deploy the pinned FP8 Kolibri checkpoint and enable its service at boot. Includes the required engine setup. | Stop/disable the owned model service. |
| `--calibration on` | With `--kolibri`, observe and validate KV scales once for the selected baseline, then reuse the verified artifact. | Selects the requested calibration mode; use `--off` to stop the model. |
| `--calibration off` | With `--kolibri`, use FP8 checkpoint weights and FP8 KV cache without the project calibration overlay. This is the default. | Existing calibration artifacts remain available. |
| `--runtime-root /absolute/path` | Choose a user-owned data directory instead of the default `~/.modelbench/<hostname>/`. | Use the same runtime path as the installation being disabled. |

For version discovery and updates, use these separate actions:

```bash
python3 -B scripts/bootstrap.py --check-updates
python3 -B scripts/bootstrap.py --update
```

The [update and recovery guide](UPDATES-README.md) covers exact releases,
complete npm/native dependency locks, automatic canaries, rollback and offline
archives. The updater selects a new release; it never rewrites an old run's pins.

Preview is the default when neither `--on` nor `--off` is supplied. Select at
least one component. `--calibration on` requires `--kolibri`. The generated
source profiles enforce the detected account, host and selected runtime path.

Only browser tools and health monitoring:

```bash
python3 -B scripts/bootstrap.py --brave --playwright --health --on
```

Only the engine, without a model download:

```bash
python3 -B scripts/bootstrap.py --vllm --on
```

Kolibri with calibration disabled:

```bash
python3 -B scripts/bootstrap.py --kolibri --calibration off --on
```

Stop the model and monitoring, preserving their files:

```bash
python3 -B scripts/bootstrap.py --kolibri --health --off
```

## What repeating the command means

The wrapper converges matching state. It retains source/profile hashes,
dependency locks, service ownership and calibration evidence. Unchanged engine
and npm environments are checked and reused. An unchanged healthy model is
checked without repeating deployment, generation or calibration. New jobs may
write new receipts. Changed or incomplete owned state is preserved and reported
instead of being silently reset or overwritten.

Changing `--calibration on` to `off`, or back again, is an explicit configuration
change and can deploy a new retained release. Failed/incomplete calibration is
not automatically rerun. A completed calibration is reused only for its exact
baseline and checksum. These are project KV scale observations, not a new
BF16-to-INT8 weight quantization. The checkpoint already uses **FP8 weights**. With calibration off, vLLM uses its default KV scales;
this mode is not a claim of equal accuracy to the calibrated profile. See
the [vLLM 0.29 KV-cache documentation](https://docs.vllm.ai/en/v0.29.0/features/quantization/quantized_kvcache/).

This behaviour is covered by local tests including 100 unchanged model-source
preparations and 100 healthy model-reuse calls for each calibration mode, with
installation/inference mocked. It is not a claim of 100 live Spark installations. Direct maintenance,
verification and recalibration commands below have their own effects and are
not equivalent to repeating the wrapper's `--on`.

The earlier bootstrap implementation passed 66 local tests across wrapper,
health, lifecycle and calibration suites. The new release-update path has
syntax/CLI checks; live target qualification remains outstanding.

## Prerequisites, generated inputs and records

The host must already have the NVIDIA OEM driver/CUDA, native systemd, Python
3.12+, GPU access for the invoking account, and the existing Ubuntu Brave
AppArmor attachment. A signed native APT source offering Node 22+ is required
when Node is absent; an incompatible existing Node installation is reported
rather than upgraded implicitly. Model deployment retains the fixed 262,144
context and hardware/memory checks. No driver, SSH or firewall setup is done.

Portable native input templates are in [config/bootstrap/](../../config/bootstrap/).
They provide Brave APT configuration and maintenance units/policy. Security
maintenance is scheduled daily at **04:00 UTC**, weekly maintenance Sunday at
**05:00 UTC**. Automatic reboot is disabled. Selecting other components does
not enable maintenance. `--maintenance` replaces distribution APT timers with
these owned timers; `--off` disables the owned timers and does not restore a
previous timer policy. Review the templates before first installation.

New Playwright installations use the [release policy](../../config/toolchain-updates.json)
and a complete, retained npm lock, native runtime and recovery artifacts.
Existing releases are reused unchanged. Updates independently resolve the full
dependency graph and must pass browser/MCP/model canaries before activation.
The old `PACKAGES` constants and `legacy_playwright()` remain only for the
historical native layout; native browser updates are not silently repinned.
Browser/model-to-tool worker qualification remains part of the
[benchmark runbook](../../docs/RUNBOOK.md).
The [isolated worker guide](../../docs/WORKERS.md) covers the separate launcher,
toolchain template, channel integration and C00 gate.

The wrapper does not depend on the omitted original Spark orchestration
configuration. Legacy direct entrypoints still refer to the original project;
their historic V5 calibration/venv is not renamed or adopted. The portable
Kolibri path builds its own baseline and calibration under the selected account.
The unrelated AMD/ROCm Mistral endpoint is not changed.

```text
~/.modelbench/<hostname>/                # Default generated data; not Git
|-- tools/
|   |-- bootstrap/
|   |   |-- jobs/<job-id>/               # Request, systemd log and receipt
|   |   |-- native-source/               # Rendered native inputs
|   |   |-- model-source/<fingerprint>/  # Per-account vLLM source/profile
|   |   |-- calibration.json             # Pinned KV manifest and loader proof
|   |   |-- selected-model.json          # Active model/configuration identity
|   |   `-- kilo.json                    # Generated MCP client fragment
|   |-- toolchains/                      # Versioned runtime, locks, canaries, archives
|   |-- playwright/                      # Historical npm layout, retained if present
|   `-- playwright-tool/                 # Historical launcher/client records
|-- build/dgx-spark-vllm/                # Engines, releases, calibration, locks
|-- models/huggingface/                  # Pinned checkpoint cache
|-- tmp/                                 # Private temporary/cache files
`-- logs/dgx-spark-vllm/                 # Native model evidence
```

The wrapper prints the exact systemd unit, receipt and log paths. Submission
alone is not completion: inspect the printed `receipt.json` for `COMPLETED` or
`FAILED`, and `systemctl status UNIT_NAME` while it is running. The single
host-wide lock prevents parallel bootstrap jobs. A different account, project path or runtime
cannot take over existing owned host services automatically.

## Source folder tree

```text
scripts/
|-- bootstrap.py                         # Public component wrapper
|-- toolchain.py                         # Updates, releases and offline recovery
`-- deploy/
    |-- README.md                        # This guide
    |-- HEALTH-README.md                 # Health endpoint purpose and operation
    |-- UPDATES-README.md                # Update policy, canaries and recovery
    |-- toolchain_lifecycle.py           # Full APT/npm resolution and releases
    |-- toolchain_canary.py              # Real MCP/model qualification
    |-- toolchain_browser_probe.cjs      # Brave/kernel sandbox canary
    |-- toolchain_native.py              # APT event and systemd integration
    |-- bootstrap_components.py          # Portable account, tools/model phases
    |-- verify_installation.py           # Read-only inventory / live acceptance
    |-- test_portable_bootstrap.py       # Wrapper/repetition/privilege tests
    |-- bootstrap-spark.py               # Legacy whole-stack coordinator
    |-- bootstrap-host.py                # Native packages and maintenance
    |-- bootstrap-playwright-deps.py     # Legacy sealed npm acquisition
    |-- install-spark-brave.py           # Native Brave installer
    |-- install-playwright-mcp.py        # Managed stdio browser tool
    |-- dgx-spark-health-bootstrap.sh    # Health timer and exporter
    |-- spark-apt-maintenance.sh         # Scheduled APT operations
    |-- kolibri.py                       # Legacy calibrated deployment owner
    |-- test_bootstrap_spark.py
    |-- test_health.py
    |-- test_playwright_installer.py
    |-- test_kolibri.py
    `-- dgx-spark-vllm/
        |-- README.md
        |-- vllmctl.py                   # Model lifecycle controller
        |-- calibrate.py                 # Baseline observation/restoration
        |-- calibrate-worker.py          # Token preparation and observation
        |-- export-calibration.py        # Advanced retained-scale export
        |-- scale-loader-preflight.py    # Actual CPU vendor scale loader
        |-- config/
        |   |-- defaults.json
        |   `-- schema.json
        |-- models/
        |   |-- kolibri-1.json
        |   `-- mistral-small-4.json
        |-- modules/
        |   |-- common.py
        |   |-- profiles.py
        |   |-- compatibility.py
        |   |-- environment.py
        |   |-- deployment.py
        |   |-- lifecycle.py
        |   |-- launch.py
        |   |-- verifier.py
        |   |-- gpu_probe.py
        |   |-- calibration.py
        |   |-- calibration_worker.py
        |   `-- privileged.py            # Bounded inherited privilege transport
        |-- scripts/
        |   `-- bootstrap.sh
        `-- tests/
            |-- test_lifecycle.py
            `-- test_calibration.py
```

## What each implementation script does

| Script | Responsibility |
| --- | --- |
| [bootstrap.py](../bootstrap.py) | Selects components, resolves the OS account, seals the job inputs, starts one sudo/systemd supervisor, runs root phases and drops privileges for user phases. |
| [bootstrap_components.py](bootstrap_components.py) | Generates retained account-specific model profiles, installs/reuses npm and engine environments, handles model deployment and reusable KV calibration. |
| [toolchain.py](../toolchain.py) | Checks/builds/qualifies releases, atomically selects stable, rolls back, exports/imports recovery bundles and starts a fixed MCP release. |
| [toolchain_lifecycle.py](toolchain_lifecycle.py) | Resolves full native/npm graphs, verifies caches/runtime bytes and manages release/qualification/archive state. |
| [toolchain_canary.py](toolchain_canary.py) | Runs the real browser MCP and two local model requests to prove the tool-result round-trip. |
| [toolchain_browser_probe.cjs](toolchain_browser_probe.cjs) | Checks Brave namespace/seccomp, live renderer status and a fresh visible marker. |
| [toolchain_native.py](toolchain_native.py) | Installs/migrates owned root files, event-only APT hooks and normal-user scheduled updates with backups/recovery journal. |
| [bootstrap-host.py](bootstrap-host.py) | Adds missing native prerequisites without upgrading existing packages. When maintenance is selected, installs its timers/policy and user lingering. |
| [install-spark-brave.py](install-spark-brave.py) | Verifies vendor signing keys and the OEM AppArmor attachment, prepares Brave APT inputs and optionally installs the browser. `--prepare` also changes APT files and downloads packages. |
| [install-playwright-mcp.py](install-playwright-mcp.py) | Seals native browser/dependency identity and atomically publishes the managed MCP launcher. Explicit `verify` invokes the browser and writes new evidence. |
| [dgx-spark-health-bootstrap.sh](dgx-spark-health-bootstrap.sh) | Installs 16 bounded observational checks, timer and cached loopback exporter on port 9817. Its installed copy keeps the selected runtime in its root-owned configuration. |
| [spark-apt-maintenance.sh](spark-apt-maintenance.sh) | Runs serialized security/weekly maintenance. Its explicit `--dry-run` still refreshes package lists and writes records; it does not reboot. |
| [bootstrap-spark.py](bootstrap-spark.py) | Original Spark coordinator, still tied to the original complete-project configuration and nested sudo design. Use the new wrapper for portable account/privilege handling. |
| [bootstrap-playwright-deps.py](bootstrap-playwright-deps.py) | Original npm installer requiring the original exact lock/module seal and Playwright configuration. The wrapper has its own first-install lock acquisition and reuse path. |
| [kolibri.py](kolibri.py) | Original single-model owner tied to the original V5 assets and acceptance helpers. The wrapper uses the model lifecycle/calibration modules directly. |

[The vLLM guide](dgx-spark-vllm/README.md) describes each lifecycle/calibration
script and internal module. Test entrypoints:

| Test script | Scope |
| --- | --- |
| [test_portable_bootstrap.py](test_portable_bootstrap.py) | Account selection, repeated source/model reuse, component selection and privilege protocol. |
| [test_health.py](test_health.py) | Health configuration, freshness, file ownership, rollback and HTTP behavior. |
| [test_lifecycle.py](dgx-spark-vllm/tests/test_lifecycle.py) | Model profiles, resource/port checks, source preservation and cutover/rollback. |
| [test_calibration.py](dgx-spark-vllm/tests/test_calibration.py) | Synthetic input preparation, scale handling and baseline environment reuse. |
| [test_playwright_installer.py](test_playwright_installer.py) | Legacy MCP tests requiring original `config/playwright-mcp.json`. |
| [test_bootstrap_spark.py](test_bootstrap_spark.py) | Legacy coordinator tests requiring original configuration and metrics source. |
| [test_kolibri.py](test_kolibri.py) | Legacy owner tests requiring original policies, calibration and acceptance helpers. |

Run the self-contained local tests without installing anything:

```bash
python3 -B scripts/deploy/test_portable_bootstrap.py
python3 -B scripts/deploy/test_health.py
python3 -B scripts/deploy/dgx-spark-vllm/tests/test_lifecycle.py
python3 -B scripts/deploy/dgx-spark-vllm/tests/test_calibration.py
```

The original `deploy.tar.xz` remains unchanged as import evidence (SHA-256
`b67ef63e746976d3aad80c7d18c6d4aa21ad87924d09a4fda39ac48afcacd1b6`). The
portable wrapper, templates and integration changes were added after import;
the current source is not a byte-identical copy of that archive. No live Spark
installation or calibration was executed as part of this local integration.
