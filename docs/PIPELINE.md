# One experiment, one report

The coordinator command combines host setup, installation acceptance, standard
benchmarks and the Melusense coding task. Run it on the supported **Ubuntu
24.04 ARM64 NVIDIA DGX Spark OEM host**, as your existing normal account, in
the approved persistent screen session.

After preparing the target configuration, one command runs the experiment:

```bash
python3 -B scripts/benchmark.py run --config build/coordinator/benchmark.json --run-id spark-kolibri-001
```

The result to open is:

```text
build/experiments/spark-kolibri-001/report.html
```

It is a self-contained HTML report with a JSON companion and private evidence.
It is updated after each phase, including failures and missing measurements.
No upload or publication is performed.

Deployment uses the native bootstrap supervisor directly, preserving the
terminal for its single sudo prompt. Headless execution needs existing sudo
authorization; it never records a password or changes sudoers. If host setup
was completed interactively, `deployment.enabled: false` selects verification
and the experiment without submitting another installation.

## 1. Prepare and preview

From the repository root:

```bash
mkdir -p build/coordinator
chmod 700 build/coordinator
cp config/benchmark.example.json build/coordinator/benchmark.json
chmod 600 build/coordinator/benchmark.json
python3 -B scripts/benchmark.py plan --config build/coordinator/benchmark.json
```

Fill the copy with actual target paths and SHA-256 values. The plan lists the
phases and missing inputs without installing software or generating tokens.
The example intentionally has no invented tool versions, dataset hashes or
approvals. It is a setup template, not a qualified experiment.

The current complete deployment profile is Kolibri FP8 on Spark. The model
revision, 262,144-token context, quantization and KV dtype must match the live
deployment. A model catalog entry alone is insufficient. Generalizing this
controller to another serving platform requires its deployment/acceptance
adapter; it does not silently substitute a model or smaller context.

| Configuration | What to supply |
| --- | --- |
| `runtime_root` | The existing installation's absolute runtime path, or `null` for the account default. |
| `deployment.enabled` | `true` to converge the installation first; `false` to use and verify an existing installation. |
| `deployment.calibration` | Explicit `on` or `off`; retain the installed mode when reusing a baseline. |
| `deployment.retention` | Local health-history days, fresh default `30`, or `forever`. |
| `benchmarks.aiperf` | Pinned tool environment, materialized local tokenizer and data manifest. |
| `benchmarks.lm_eval` | Pinned environment, local tokenizer, prepared offline HF cache and reviewed task bundle. |
| `benchmarks.bfcl`, `swe_bench` | Pinned official-suite generation/scoring adapters for the selected local backend. |
| `coding.package` / `source_sha` | The approved Git-free source archive, its SHA-256 and full commit SHA. |
| `coding.train_bundle` / `rights_record` | The identical approved TRAIN bundle and its completed review record. |
| `coding.toolchain` | Filled, pinned worker configuration from [WORKERS.md](WORKERS.md). |
| `coding.evaluator` | Independent scorer adapter with its separate runtime and qualified held-out data. |

The source archive must contain the intended files. `git archive` excludes
uncommitted and untracked work. Development commits are not approved benchmark
baselines: select the reviewed source commit after target acceptance, before a
scored trial. See [QUICKSTART.md](QUICKSTART.md).

## 2. What the command does

```text
Host inventory
    |
    v
Optional idempotent bootstrap -> real installation verification
    |
    +-- P1: AIPerf / clients 1, 2, 4 / three repetitions each
    +-- P2: lm-eval / IFEval, MMLU-Pro, BBH
    +-- P3: official BFCL and SWE-bench generation + scoring
    |
    v
P4: three independent coding seeds
    |-- verify approved source / TRAIN / model / toolchain identities
    |-- prepare isolated worker -> fresh C00 -> run Kilo coding task
    |-- freeze code + tests -> run visible tests without broker mounts
    `-- independent held-out assessment, bound to frozen candidate hash
    |
    v
One HTML report + numeric JSON + hashed phase evidence
```

Standard-suite failures do not erase their evidence or prevent collecting
other independent measurements. Installation acceptance gates subsequent
inference. Missing coding prerequisites block that coding attempt. Failure in
one seed does not replace it or suppress the other seeds.

`PASS` means an execution and its result validation completed. Its actual
quality score can be low. Agent exit 0 alone is not a coding PASS: the
separately invoked visible tests must pass. Skips, expected failures and empty
suites do not establish acceptance. Held-out scoring remains independent.

The default lm-eval example requests **full tasks** (`limit: null`). A deliberate
positive `limit`, such as `10`, is a smoke subset and is labelled as such in
the report. Full suites can take hours; configured timeouts remain visible.
BFCL/SWE-bench adapters declare their selected scope and actual case count.
No results are substituted when a backend or platform is unsupported.
`lm_eval.cli_style` explicitly selects `run` for the current subcommand CLI or
`legacy` for a pinned older direct CLI; it never upgrades the installed tool.

## 3. Inspect an existing or partial installation

```bash
# Read existing state; no installation, repair or inference.
python3 -B scripts/bootstrap.py --inspect

# Perform model generation, browser/model MCP canary and health acceptance.
python3 -B scripts/bootstrap.py --verify --output build/installation-check
```

Pass the original `--runtime-root` for a custom installation. Component flags
can narrow the inspection, for example `--health --inspect`. Omitting them
selects the whole stack. The current full workflow uses all five public
components; `--kolibri` includes its vLLM engine.

Each direct inspection/verification with `--output` writes a new named receipt
directory beneath that prefix, so repeating the command preserves earlier
checks. The printed JSON gives its exact path. `NEEDS_VERIFICATION` means
artifact bytes are intact but a live qualification must be renewed, for
example after reboot. `--verify` can renew it; inspection itself does not.

Inspection distinguishes missing components and an unsupported platform from
observed matching state. Verification does not install or repair components;
it writes acceptance evidence and renews the browser-tool qualification with
a real model/tool round-trip. The model verifier checks the owned deployment,
identity/context, swap and an actual completion. A fresh `/healthz` is only
monitor freshness: the report also preserves warning/critical/unknown health
observations. Host acceptance is separate from isolated-worker C00.

## 4. Pin or provision benchmark tools

Each native benchmark specifies a copied venv interpreter (`python.path` and
SHA-256), exact distribution version and a pinned `requirements_lock` file.
This file contains the complete installed distribution set as plain
`name==version` lines, including pip/setuptools when installed. The verifier
compares installed metadata with that set and rejects editable dependencies.
It does not log package direct-reference URLs or inherit API-key variables.

An existing matching environment is reused. To install one automatically from
retained artifacts, add `runtime.provision`:

```json
{
  "base_python": {"path": "/absolute/python3.12", "sha256": "<SHA256>"},
  "wheelhouse": "/absolute/offline-wheels",
  "data_manifest": {"path": "/absolute/wheels.json", "sha256": "<SHA256>"},
  "install_lock": {"path": "/absolute/requirements-hashed.txt", "sha256": "<SHA256>"}
}
```

The controller creates `<venv>/bin/python` using `venv --copies`, verifies its
expected binary checksum, then uses wheel-only, offline pip installation with
`--require-hashes`. The install lock must contain the complete transitive
dependency hashes. The separate runtime lock records the expected installed
versions. Wheels must match the target architecture/Python. No current-latest
package resolution or source compilation occurs during a scored run.
Failed/partial provisioning is retained rather than repeatedly reinstalled;
select a new environment path after diagnosing it.

Task YAML, tokenizer and dataset files need a manifest of actual local bytes:

```bash
python3 -B scripts/benchmark.py pin-data \
  --root /absolute/materialized-tokenizer \
  --root /absolute/offline-hf-cache \
  --root /absolute/reviewed-tasks \
  --revision REVIEWED-BUNDLE-ID \
  --output build/coordinator/model-data.json
```

Record each upstream revision in the bundle ID/provenance; manifests may also
record a separate revision per file. The helper prints the manifest's SHA-256.
It requires materialized files, not snapshot symlinks. All task/cache/tokenizer
files must be covered; ephemeral `.lock` and `__pycache__` files are not data.
lm-eval runs with HF network downloads disabled. Prepare data in advance.
These manifests are technical identity evidence, not correspondence approval.

## 5. BFCL, SWE-bench and independent evaluator adapters

The controller has native AIPerf and lm-eval integrations. BFCL/SWE-bench model
registrations, containers and scorer formats vary by pinned release. Their
adapters run the official generation/scoring commands. They are not replaced
with a home-made approximate score. A complete workflow therefore needs those
target adapters and data; the example does not claim they are provisioned.

Use a reviewed executable, or the supplied `scripts/suite-adapter.py` with a
pinned definition. An adapter entry is:

```json
{
  "executable": {"path": "/absolute/scripts/suite-adapter.py", "sha256": "<SHA256>"},
  "definition": {"path": "/absolute/reviewed-suite.json", "sha256": "<SHA256>"},
  "version": "REVIEWED-SUITE-COMMIT",
  "data_manifest": {"path": "/absolute/suite-data.json", "sha256": "<SHA256>"},
  "timeout_seconds": 21600
}
```

The definition supplies `schema_version: 1`, `benchmark` (`bfcl`, `swe_bench`
or `melusense`), a tool `runtime` as above, pinned script `artifacts`, and
`commands`: arrays of `argv` plus `timeout_seconds`. Arguments may use
`{python}`, `{model}`, `{base_url}`, `{seed}`, `{output}`, `{request}` and
`{candidate}`. They are argument substitutions, never shell commands. Use the
actual commands supported by the pinned suite/backend. No hosted provider
credentials are inherited. The supplied adapter sets local OpenAI base URLs
and uses a fresh home; the suite registration must actually honor that local
backend configuration. This adapter does not create an inference firewall or
the independent evaluator's sandbox.

`result.file` is a relative JSON path inside the output directory.
`result.samples_pointer` and `result.metrics` JSON pointers project the
official scorer's count and numeric measurements, with explicit units.
`scope` is `smoke`, `full` or `qualified-held-out`. Full/held-out runs must
match `expected_samples`. For example, the **shape**, not an official BFCL
schema, is:

```json
{
  "file": "native-score.json",
  "samples_pointer": "/evaluated_cases",
  "metrics": {"accuracy": {"pointer": "/scores/accuracy", "unit": "fraction"}}
}
```

A custom adapter accepts `--request FILE --result FILE` (and the supplied
adapter additionally `--definition FILE`). Its result echoes `schema_version`,
`request_sha256`, `adapter_version`, `data_manifest_sha256`, `benchmark`,
`model` and `seed`, then supplies `status: PASS`, `evaluated_samples`, `scope`,
`metrics: {name: {value, unit}}` and `evidence: [{path, sha256}]`.
The definition-based adapter also echoes `definition_sha256`. Native evidence
must exist inside its output directory and match the hashes.

The Melusense evaluator additionally checks and returns
`candidate_tree_sha256`, `train_examples_checked: 12` and
`train_bundle_sha256`. A definition uses corresponding
`result.<field>_pointer` entries. Its isolated evaluator runtime scores frozen
code with protected Gold kept outside worker access; never run candidate code
directly in the coordinator's host interpreter. Missing qualified Gold or
evaluator produces `NOT_EVALUATED`. TRAIN checks are reported separately from
held-out accuracy, with the reviewed annotation mapping.

## 6. Read, resume and retain

```bash
# Same identity: verify and reuse recorded phases; continue untouched phases.
python3 -B scripts/benchmark.py run --config build/coordinator/benchmark.json --run-id spark-kolibri-001

# Rebuild only the report from matching retained receipts and hashed evidence.
python3 -B scripts/benchmark.py report --run build/experiments/spark-kolibri-001
```

No failed/blocked/completed phase is retried under the same ID. An interrupted
phase is retained and requires a new experiment ID. Changed configuration,
controller, host/boot or source inputs also require a new ID. Backend revision,
profile, unit and process identity must remain unchanged during measurements.
Shared leases keep the managed updater's downloads/builds and canaries out of
the timed experiment. Unregistered external workloads still need coordination.

If the pipeline is interrupted during bootstrap, its durable systemd bootstrap
job can still be running. Inspect that job and its receipt before submitting a
new experiment; the existing host lock prevents parallel bootstrap mutations.

The report records per-phase scores, actual sample counts and scope, three-seed
coding results, visible test counts, timings, hardware/configuration identity,
sampled host memory/swap/GPU observations, and raw evidence references.
Missing token, cache, cost and energy measurements remain unknown. Native
vLLM counter deltas are retained without inventing a cache-hit percentage;
GPU power samples are not a whole-run energy measurement.

Exit 0 means the requested pipeline completed, or a plan was printed.
`COMPLETED_WITH_SMOKE` explicitly identifies a completed subset run. Exit 2
means partial, blocked or failed results; exit 130 means interruption.
Each tool's actual exit code remains in its command receipt. Report regeneration
does not contact the model or rerun tests.

```text
scripts/
|-- benchmark.py                         # Public experiment CLI
|-- suite-adapter.py                     # Pinned native-scorer command adapter
|-- modelbench/
|   |-- common.py                        # Pins, locks, durable bounded commands
|   |-- provision.py                     # Offline hash-locked tool environments
|   |-- adapters.py                      # AIPerf, lm-eval and scorer receipts
|   |-- telemetry.py                     # Sampled host readings/native counters
|   |-- pipeline.py                      # Phase orchestration and three seeds
|   `-- report.py                        # Self-contained HTML and JSON
`-- deploy/verify_installation.py         # Inventory and live host acceptance

build/experiments/<run-id>/               # Private, ignored; review before sharing
|-- configuration.json, state.json        # Experiment identity, never key contents
|-- report.html, report.json              # The single human entry point + data
`-- phases/<phase>/
    |-- receipt.json                     # Phase result and evidence hashes
    |-- */command.json, output.log        # Commands, exits and bounded logs
    |-- telemetry.json                   # Sampled observations, when applicable
    `-- workers/<run-id>/                 # Coding only: C00, frozen code and tests
```

The implementation has local syntax, CLI and plan checks. No Spark experiment,
official benchmark execution or held-out score has been claimed from those
checks. Provision target inputs, complete a real run and retain its report.

Primary tool contracts: [AIPerf](https://github.com/ai-dynamo/aiperf),
[lm-eval API guide](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/docs/API_guide.md),
[SWE-bench](https://github.com/SWE-bench/SWE-bench),
[BFCL](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard).

## Terminal model outcomes and independent repetitions

An independently reviewed native candidate that does not complete the task is
`CANDIDATE_REJECTED`, with `candidate_verdict: FAILED`. This is a completed
measurement. The coordinator retains it and continues to the other independent
seeds; repetition never retries that candidate. Infrastructure failure, uncertain
accounting and pending independent review still stop progression.

`NOT_EVALUATED` records a completed decision that the configured evaluator is
unavailable. It remains visible as missing evidence; no score is fabricated.
A run containing a rejected candidate reports `INCOMPLETE`; one with unavailable
measurements reports `PARTIAL`. A terminal continuation state never means that
the model passed, that held-out Gold was qualified, or that publication is ready.

Explicit BFCL `retained` selection reuses only a completed, sealed result with
matching model/process/boot, benchmark configuration and intact raw evidence.
The original scorer run identity is preserved and repeated model requests are
zero. Changed inputs require a new deliberate measurement; no silent fallback
runs a scorer when retained evidence fails verification.

For native sessions, the shared model-workload lock belongs to the unique actual
`runtime_root` in the pinned session profiles. The adopted installation registry
may live elsewhere and must not determine this lock. Independent native sessions
with conflicting runtime roots are rejected. Observation of a validated existing
coding session is permitted under its coordinator's already-held lock.
