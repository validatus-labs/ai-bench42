# Melusense Benchmark

A reproducible A/B/C benchmark for **Kolibri-1, Mistral Small 4 and Qwen**.
We evaluate serving performance, general model quality, coding/tool calling and
independent development of the same Melusine pipeline as separate outcomes.

This private repository contains the agent-visible development assignment and
an intentionally incomplete starter. Infrastructure and coordinator runners live
in the separate AI-Model project. The parser stubs here are not the reference
implementation. Maintained project documentation is written in English.

## Purpose and research question

Can each model independently implement the Melusine email pipeline when given
the same starting code, TASKS.md, tools and budget? How do the resulting solutions
differ in correctness, safety, architecture, code quality and development cost?

The four phases help explain those differences. They separate hardware/serving
limits, general model capability, tool-use failures and the ability to complete
the actual engineering task. We compare measured outcomes and independently
review implementations; equivalent functionality does not require identical code.

The intended deliverables are a versioned methodology, reproducible run records,
separate phase results and an independently assessed implementation comparison.
An ALTONJI article and a reproducible Hugging Face evaluation are future release
goals, subject to review and explicit publication approval.

## Start here

- [MANIFEST.md](MANIFEST.md): navigation.
- [AGENTS.md](AGENTS.md): binding agent rules.
- [TASKS.md](TASKS.md): common assignment and phase checklist.
- [API contract](docs/contract.md): interfaces and safety invariants.
- [Evaluation contract](docs/evaluation.md): comparability and isolation.
- [Common budgets](config/budget.json): identical limits for all models.

## Four phases

| Phase | Question and scope | Tools and execution |
|---|---|---|
| 1 — Infrastructure & Metrics | How does the model run on this hardware? Revision, quantization, context, memory, TTFT, prefill, decode, cache and 1/2/4 concurrent clients. | vLLM, one central Prometheus and NVIDIA AIPerf; coordinator runners in AI-Model. |
| 2 — General Evaluation | How well does it follow instructions, recall knowledge and reason? Identical tasks, dataset revisions and scoring rules. | Hugging Face LightEval with IFEval, MMLU-Pro and BBH; coordinator runners in AI-Model. |
| 3 — Coding & Tool Calling | Can it solve coding tasks and issue correct tool calls? Record successes, errors, elapsed time and token usage. | Versioned SWE-bench Verified and BFCL selections; preparation, inference and grading runners in AI-Model. |
| 4 — Melusine AgentBench | Can it independently implement the same pipeline from the same frozen commit? | Separate branches/worktrees and confined runtimes; freeze candidates before independent reference/Gold evaluation. |

## Current evidence and open gates

The AI-Model project has executed a Kolibri performance pilot, a general-evaluation
smoke and a BFCL pilot. The BFCL pilot uses three simple Python tool cases with
three seeds: 9/9 calls pass the official AST checker and execute locally as
allowlisted pure functions. This small single-turn test is not a full BFCL score
or a multi-turn tool-result-consumption benchmark. The three frozen SWE-bench
images currently provide AMD64, not ARM64; their Spark execution is blocked,
without emulation or silent case substitution.

Three branches/worktrees per model are prepared from the identical base SHA.
Candidates receive Git-free exports. Nine real tool/evaluator containers each
pass 14 confinement checks. Those checks do not attest confinement of the visible
Kilo worker or its model gateway. Reference freeze, qualified human Gold,
independent worker isolation and qualified additional model profiles remain
open gates. No real Melusine model trial, reference/Gold comparison, Melusine F1
or complete A/B/C comparison has run.

Coordinator commands in AI-Model are `scripts/benchmark/coding.py` with
`prepare`, `bfcl`, `swe-preflight`, `swe-evaluate`, and
`scripts/benchmark/agentbench.py` with `prepare`, `status`, `probe`, `handoff`,
`freeze`, `evaluate`. Freeze records a Git tree without committing/pushing.
The separate evaluator is implemented to compare frozen candidates and an
independently approved reference against private qualified Gold. It retains
failures and exports aggregate metrics only. Real private-Gold evaluation has
not yet been executed. Future workers stay in the visible Kilo VS Code session;
a hidden agent loop is not a substitute. This starter alone starts no benchmark
or agent run.

## Common starting point

The frozen starting commit is:

```text
75fcaad909346909115d92b9929b5b91b3ddfbd6
Branch: benchmark/base-v1
Tag:    benchmark-base-v1
```

Every model trial must use this **full SHA**. The main branch may evolve project
documentation and is not a replacement for the base SHA. Branch protection is
unavailable under the current private GitHub plan; the coordinator must verify
refs against the SHA before each trial.

Each model receives identical TASKS.md, visible tests and budgets. At least
three independent repetitions get unique Run-IDs. Record model revision,
quantization, context, decoding settings, tool versions, timing, token usage and
failures. Do not reuse earlier solutions, agent histories or modified trial
files. Reproducible preparation and scoring do not imply identical stochastic
model outputs.

## Verify the starter

Python >=3.12 is the target environment. Initial source uses only the standard
library:

```bash
python3 -B tools/verify_scaffold.py
python3 -B -m unittest discover -s tests -p 'test_scaffold.py'
python3 -B -m unittest discover -s tests -p 'test_acceptance.py'
```

The first two commands verify the starter structure. The last command fails
on the frozen base because the parsers are intentionally unimplemented. Fulfill
these visible acceptance tests unchanged; a passing structure check is not parser
success. Never delete, skip or weaken failed tests to improve a result.

## Architecture and isolation boundaries

One central Prometheus collects metrics from the active model server. Worktrees
do not need their own Prometheus. Large models are tested sequentially on the
DGX Spark; concurrent clients and actual active model sequences are reported
separately.

The complete reference stays in the separate `validatusinternal/melusense`
repository. Branches and worktrees are not access control. Agents must not access
the reference, other trials, host credentials, private corpora, Gold or hidden
tests. Verify that isolation outside Git before starting a real trial.

Only the independent evaluator receives approved additional evaluation data.
It scores previously frozen candidates; workers do not certify their own success.
Rights/privacy review and independent human Gold annotation remain binding gates.

The three visible examples are synthetic. Real email, private annotations,
reference code, secrets and previous model solutions do not belong in this
repository. Publication on ALTONJI or Hugging Face requires separate review and
approval.
