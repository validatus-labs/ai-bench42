# AI-Bench42 — current repository state

**Checked on 18 October 2026.** This is a human-readable snapshot of this
checkout. It is not a C00 readiness decision or a substitute for per-run
evidence. [TASKS.md](TASKS.md) remains the immutable assignment; the
[runbook](docs/RUNBOOK.md) defines the checks and status transitions.

## Coverage and evidence

| Scope | Documented in | Evidence in this checkout |
| --- | --- | --- |
| P1–P3 serving, general evaluation and tools | [Pipeline](docs/PIPELINE.md), [TASKS.md](TASKS.md#2-coordinator-phases-not-candidate-implementation-tasks) | Native AIPerf/lm-eval execution, optional offline tool provisioning and pinned official-suite scorer adapters implemented. Target tool versions/data/backend registrations remain to configure; no actual benchmark scores |
| Automated experiment and combined report | [Pipeline](docs/PIPELINE.md) | `scripts/benchmark.py` joins inventory, optional deployment, live verification, P1–P3, three C00/coding/freeze/visible-test seeds and independent evaluator receipts. Private hash-bound phase evidence, bounded commands, sampled telemetry and HTML/JSON report implemented; local syntax/CLI/plan checks only |
| DGX Spark serving-host bootstrap sources | [Bootstrap guide](scripts/deploy/README.md) | Imported source plus portable `scripts/bootstrap.py`, native templates and account-specific model/calibration handling; local regression checks only. No host installation or GPU calibration was performed |
| Browser-toolchain updates and recovery | [Update guide](scripts/deploy/UPDATES-README.md) | Versioned APT/npm runtime, full dependency resolution, real browser/MCP/model canaries, atomic promotion, rollback holds, recovery archives and APT/systemd integration implemented; syntax/CLI checks only, no live release/hook rollout |
| Local health history | [Health guide](scripts/deploy/HEALTH-README.md#history-and-retention) | Hourly JSONL archive and pruning implemented; `--retention 7\|30\|90\|180\|365\|forever`, fresh default 30 days, `never`/`--never` aliases for unlimited history. Existing saved settings survive repeat installation. No target rollout or retention acceptance run |
| C00 package, Brave MCP, isolation and required TRAIN | [Worker guide](docs/WORKERS.md), [RUNBOOK.md](docs/RUNBOOK.md#c00-qualify-one-worker-before-c01), [HPI_TRAIN.md](docs/HPI_TRAIN.md) | Launcher, C00, coordinator freeze and isolated visible acceptance are supplied. Target rootfs/pins, scoped Unix brokers and a reviewed channel qualification adapter remain to be provisioned. No live worker or `READY` receipt |
| C01–C05 parser implementation | [TASKS.md](TASKS.md#3-p4-candidate-implementation-from-a-deliberately-empty-parser), [CONTRACT.md](docs/CONTRACT.md), [AGENTS.md](AGENTS.md) | `melusense/api.py` remains an unimplemented starter |
| C06 candidate verification | [TASKS.md](TASKS.md), [EVALUATION.md](docs/EVALUATION.md#visible-mode-and-cli-cases) | Visible starter tests exist; client/language and adversarial cases still require candidate tests and independent review |
| C07 freeze and scoring | [RUNBOOK.md](docs/RUNBOOK.md#run-and-retain-evidence), [EVALUATION.md](docs/EVALUATION.md) | No `build/`, frozen candidate or evaluator report |

The earlier portable host wrapper passed 66 local regression tests, including 100
unchanged source preparations and 100 model-reuse calls for each calibration
mode with GPU/install operations mocked. Syntax and documentation links passed.
This verifies local integration, not a fresh-host installation or GPU calibration.

`python3 -B tools/verify_scaffold.py` returned exit 0 with
`PASS: scaffold integrity only; parser remains unimplemented`. The model
catalog contains candidate names but no pinned served model IDs or revisions.
The current development snapshot is committed under the AI-Bench42 name. No
release tag or approved benchmark source baseline has been selected. No live model, MCP or evaluator runtime was
checked in this review. Treat a new coding trial as **not READY** until its C00
evidence exists.

## Development history and source baseline

AI-Bench42 starts a new Git history with the current implementation and
consolidated documentation. This start commit is a development snapshot, not a
release or a qualified benchmark baseline. Select and record a shared source
commit only after the remaining target installation and acceptance work is
complete; until then, continue with ordinary development commits. Dependency,
model and toolchain pins remain in place for repeatable installation.

The Melusense package remains the first coding challenge. Existing internal
`modelbench` Python module names, runtime paths and ownership markers are
retained for compatibility; they do not identify a separate project.

## Next recorded action

Prepare `build/coordinator/benchmark.json` from `config/benchmark.example.json`
on the actual Spark: pin benchmark environments/data, source/TRAIN/toolchain,
official BFCL/SWE-bench adapters and the independent evaluator. Run the new
inspection/verifier and the complete experiment, retaining its generated report.
The template deliberately contains unresolved pins and is not deployment-ready.

Local controller checks on 18 October: Python AST (51 files plus the embedded
health implementation and metadata query), configuration JSON, CLI help and
123 relative documentation links passed, as did `git diff --check`. The plan
returned `PLAN_ONLY` with 13 phases and 21 missing target inputs. These were
source/preview checks, not execution of the new test or benchmark paths.

On the supported Spark target, roll out and verify the maintenance controller
and health history, qualify an actual toolchain release, exercise update,
rollback and offline recovery, and inspect retention cleanup. The new paths
have local syntax/CLI checks only; no live installation is claimed.

Provision the reviewed worker rootfs, scoped inference/browser Unix services
and channel qualification adapter; fill the private toolchain pins using
[WORKERS.md](docs/WORKERS.md). The new coordinator tools have syntax/CLI checks,
not live namespace, channel or model qualification evidence.

Reconcile and freeze the source package, then perform C00 for the selected
model and seed. Only after a
per-run `READY` receipt should C01 begin. The fixed 12-pair HPI TRAIN bundle is
required for every Phase-4 model and seed, with matching SHA-256, rights and
worker-disclosure evidence.
