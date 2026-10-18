# AI-Bench42 — Navigation

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
17. [Isolated worker guide](docs/WORKERS.md) — toolchain template, bubblewrap launcher, TRAIN transfer, C00 evidence and one-shot candidate execution.
18. [Updates and recovery](scripts/deploy/UPDATES-README.md) — release lifecycle, APT events, full npm pins, real canaries, rollback and offline bundles.
19. [One experiment, one report](docs/PIPELINE.md) — deployment/verification, standard-suite adapters, three isolated coding seeds, independent scoring and one HTML report; [controller](scripts/benchmark.py), [target configuration](config/benchmark.example.json).

The English prompt, build tree, Brave/MCP research rules and classifier-mode interface define the common candidate handoff. Record each trial's readiness and results in its own run evidence.
