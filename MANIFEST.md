# AI-Bench42 — Navigation

[Run Kolibri alone](docs/KOLIBRI.md) — executable diagnostics, exact evidence,
repeatable results and the explicit connection to the real coding challenge.

[Verify the coordinator package](scripts/verify-package.py) runs its complete
offline test set and seals reusable evidence. [Adopt an existing model](scripts/deploy/adopt-existing.py)
registers exact owned source/deployment bytes without installing or restarting.
[Requalify updated native browser tools](scripts/deploy/requalify-existing.py)
preserves previous registrations and requires exact observed hashes.
[Seal actual experiment inputs](scripts/configure-experiment.py) validates real
runtimes, offline data and adapter qualification.

1. [README](README.md) — mission, DGX Spark, model examples, four benchmark phases, parser pipeline.
2. [TASKS](TASKS.md) — **frozen ASCII architecture and all-unchecked task contract**.
3. [AGENTS](AGENTS.md) — binding coding-agent source layout and safety rules.
4. [Runbook](docs/RUNBOOK.md) — package, worker isolation, Brave research, C00 and run evidence.
   [Beginner guide](docs/QUICKSTART.md) — one command at a time from Git clone to a checked Git-free package.
5. [English offline coding-agent prompt](docs/OFFLINE_AGENT_PROMPT.md) — single copy/paste handoff for every model/seed.
6. [Candidate source layout](AGENTS.md#required-candidate-source-layout) · [Reserved mode and CLI](docs/CONTRACT.md#reserved-optional-classifier-mode-interface).
7. [Benchmark phases and methods](TASKS.md#2-coordinator-phases-not-candidate-implementation-tasks).
8. [Model profile catalog](config/models.json) — illustrative profiles; deployment verification required.
9. [Shared budgets](config/budget.json).
10. [API and safety](docs/CONTRACT.md); [Independent evaluation](docs/EVALUATION.md).
11. [Empty parser API](melusense/api.py), [synthetic fixtures](tests/fixtures.json), [visible acceptance](tests/test_acceptance.py), [scaffold check](tools/verify_scaffold.py).

12. [Legacy greenfield/bootstrap script](tools/greenfield.py) — historical Chromium installer (NOT a Brave verifier); rights-gated HPI TRAIN importer remains available.
13. [Public research and worker preflight](docs/RUNBOOK.md#public-research-through-brave) · [Rights-gated HPI TRAIN](docs/HPI_TRAIN.md).
14. [Current repository state](STATE.md) — human snapshot; per-run receipts remain authoritative.
15. [Bootstrap scripts and usage guide](scripts/deploy/README.md) — portable component wrapper, per-user sudo/systemd handling, Brave/MCP, maintenance, health and FP8 Kolibri/KV calibration, with command examples and ASCII trees.
16. [Health monitoring guide](scripts/deploy/HEALTH-README.md) — purpose, 16 host/model checks, freshness, metrics and operating commands.
17. [Isolated worker guide](docs/WORKERS.md) — toolchain template, explicit native/legacy launcher, TRAIN transfer, C00 evidence and one-shot candidate execution.
18. [Updates and recovery](scripts/deploy/UPDATES-README.md) — release lifecycle, APT events, full npm pins, real canaries, rollback and offline bundles.
19. [One experiment, one report](docs/PIPELINE.md) — deployment/verification, standard-suite adapters, three isolated coding seeds, independent scoring and one HTML report; [controller](scripts/benchmark.py), [target configuration](config/benchmark.example.json).

The English prompt, build tree, Brave/MCP research rules and classifier-mode interface define the common candidate handoff. Record each trial's readiness and results in its own run evidence.

## Results for readers and coordinators

- [Results at a glance](docs/reports/README.md) — conclusions and what is still unmeasured.
- [Kolibri: abilities and limits](docs/reports/kolibri.md) — concise capability assessment and benchmark interpretation.
- [How we measure](docs/reports/methodology.md) — conditions, effort, private-reference boundaries and comparison limits.

The results page leads to an experiment-grouped evidence index. Historical reports
are preserved there; old paths are compatibility links, not additional reader reports.
Reports must stay outside candidate offline packages. This documentation commit
is not a new approved assignment or benchmark freeze.

[Native runtime builder](tools/native_runtime.py), [namespace constructor](tools/native_namespace.py),
and [reconnectable inspection transport](tools/native_gui.py) are described in the
[worker guide](docs/WORKERS.md#native-spark-backend-and-reconnectable-inspection).
Synthetic isolation and GUI proofs are not full C00 or coding acceptance.

[Inspection preparer](tools/native_inspection.py) creates and reuses the private
synthetic UI configuration from validated, pinned existing inputs; it starts no model.

[Offline assignment exporter](tools/assignment.py) selects unchanged task/API/tests/
budgets from an exact source SHA and derives outcome-free navigation. The export
retains scaffold checks and expected empty-parser failures; it is not readiness.

[Publication privacy gate](scripts/verify-publication.py) — source checks; reproducibility metadata retained.

[Latest reviewed three-seed cohort](docs/reports/evidence/kolibri-20261106.json) — redacted counts, source/artifact pins and publication limits.
