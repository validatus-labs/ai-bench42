# ModelBench — Navigation

1. [README](README.md) — mission, DGX Spark, model examples, four benchmark phases, parser pipeline.
2. [TASKS](TASKS.md) — **frozen ASCII architecture and all-unchecked task contract**.
3. [AGENTS](AGENTS.md) — binding coding-agent source layout and safety rules.
4. [Workspace layout](docs/WORKSPACE_LAYOUT.md) — one offline workbench, restricted builds/evidence/reports, Run-IDs and idempotence.
5. [English offline coding-agent prompt](docs/OFFLINE_AGENT_PROMPT.md) — single copy/paste handoff for every model/seed.
6. [Candidate build/tree and reserved ML interface](docs/BUILD_CONTRACT.md) — fixed Python module layout, CLI `--ml-mode off|recover` (reserved only), and no training.
7. [Benchmark guide](docs/BENCHMARKS.md) — definitions, official frameworks, references.
8. [Model profile catalog](config/models.json) — illustrative profiles; deployment verification required.
9. [Shared budgets](config/budget.json).
10. [API and safety](docs/contract.md); [Independent evaluation](docs/evaluation.md).
11. [Empty parser API](melusense/api.py), [synthetic fixtures](tests/fixtures.json), [visible acceptance](tests/test_acceptance.py), [scaffold check](tools/verify_scaffold.py).

12. [Existing greenfield/bootstrap script](tools/greenfield.py) — pinned browser + HPI TRAIN importer.
13. [Fair browser tools](docs/RESEARCH_TOOLS.md) · [Rights-gated HPI TRAIN](docs/HPI_TRAIN.md).

**Proposal scope:** The standalone English prompt, full build tree and reserved classifier-mode obligation are being revised on an unmerged Brave-proposal branch. No model trial has completed this proposed assignment, and it is NOT an approved freeze. The old main package and Spark installations remain unchanged. No checkbox may be ticked in `TASKS.md`; results are recorded separately.
