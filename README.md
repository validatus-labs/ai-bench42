# ModelBench — LLM Engineering & Evaluation Lab

**One lab. Many models. Same evidence.**

A model-agnostic, reproducible benchmark workspace for testing what local and self-hosted LLMs **can do**, **how fast they do it**, and **how reliably a coding agent turns instructions into working software**. The first applied engineering challenge is **Melusense**: build a safe, multilingual email-structure parser from an intentionally empty Python starter.

**Status: STARTER ONLY · NO MODEL TRIALS RUN FROM THIS BASELINE.** A passing scaffold check is not a successful coding benchmark.

> **Built for experiments on NVIDIA DGX Spark and other compatible inference hosts.** Example candidate profiles: **Kolibri-1, Mistral Small 4, GLM-5.3 Flash, Qwen and DeepSeek**. These are *targets*, not claims that all models are installed, have compatible context lengths, or have been benchmarked. Each run pins its exact served model ID, revision and quantization.

[**Task & pipeline**](TASKS.md) · [**Agent contract**](AGENTS.md) · [**Directory layout**](docs/WORKSPACE_LAYOUT.md) · [**Benchmark guide**](docs/BENCHMARKS.md) · [**API**](docs/contract.md) · [**Evaluation**](docs/evaluation.md)

## What are we measuring?

A single tokens-per-second chart cannot tell whether a model follows constraints, solves difficult problems, uses tools correctly, or produces maintainable software. This lab deliberately keeps **serving performance**, **general quality**, **tool/coding ability**, and **end-to-end engineering** separate.

| Phase | Benchmark | In two sentences | Official reference |
|---|---|---|---|
| **01 · Speed** | **NVIDIA AIPerf + Prometheus** | Measure TTFT, prompt/prefill speed, decode tokens/s, memory, queueing and concurrency. Client concurrency is **not** proof of parallel model decoding. | [AIPerf](https://docs.nvidia.com/aiperf/getting-started/profiling-with-ai-perf) · [Prometheus](https://prometheus.io/docs/introduction/overview/) |
| **02 · Reasoning** | **LightEval · IFEval · MMLU-Pro · BBH** | Measure instruction following and reasoning on fixed datasets, prompts and scorers. Scores must include truncation and backend limitations—not just headline percentages. | [LightEval](https://huggingface.co/docs/lighteval/index) · [IFEval](https://github.com/google-research/google-research/tree/master/instruction_following_eval) · [MMLU-Pro](https://github.com/TIGER-AI-Lab/MMLU-Pro) · [BBH](https://github.com/suzgunmirac/BIG-Bench-Hard) |
| **03 · Tools & code** | **BFCL · SWE-bench Verified** | BFCL checks whether a model selects and calls tools correctly; SWE-bench tests code changes against real software issues. A tiny smoke test is not a complete leaderboard result. | [BFCL](https://gorilla.cs.berkeley.edu/leaderboard) · [SWE-bench](https://github.com/swe-bench/SWE-bench) |
| **04 · Build something** | **Melusense AgentBench** | Each coding agent independently implements the **same** rule-first email parser, starting with the same empty files. Independent tests assess correctness, safety, architecture, speed, token cost and reproducibility. | [Assignment](TASKS.md) · [Contract](docs/contract.md) |

A benchmark is not an all-purpose ranking. A fast model can code poorly; a model that passes small tool tests can fail complex workflows. Results are comparable **only when task revisions, hardware/serving conditions, seeds and evaluation procedures are explicitly matched**.

## How a DGX Spark experiment works

```text
                  NVIDIA DGX Spark (or other qualified host)
                                  |
                       vLLM / model server
                                  |
                    one active model at a time
                                  |
            +---------------------+--------------------+
            |                     |                    |
     AIPerf + metrics         LightEval / BFCL     Coding-agent gateway
         P1 / P2                   P2 / P3                 P4
                                                         |
                                        frozen base SHA + identical task
                                                         |
                                  +----------------------+---------------------+
                                  |                      |                     |
                              Kolibri                 Mistral                 GLM / Qwen / ...
                             seed 41/42/43            seed 41/42/43          seed 41/42/43
                                  |                      |                     |
                                  +----------------------+---------------------+
                                                         |
                                           Independent evaluator
                                                         |
                                        Accuracy · Safety · Cost · Quality
```

Only the **coordinator** may see reference implementations and private evaluator data. Each coding worker receives an isolated, **Git-free export** of the same pinned task. Branches preserve the resulting work; they do **not** enforce security isolation.

### One task, one candidate branch per repetition

A candidate is saved to a uniquely named output branch **after** its isolated run:

| Model profile (examples) | Result branches (examples) |
|---|---|
| Kolibri-1 | `trial/kolibri-1/seed-41`, `.../seed-42`, `.../seed-43` |
| Mistral Small 4 | `trial/mistral-small-4/seed-41`, ... |
| GLM-5.3 Flash | `trial/glm-5.3-flash/seed-41`, ... |
| Qwen / others | `trial/<model-slug>/seed-41`, ... |

Each branch starts from the **same frozen commit**, never from another model's solution. Progress reports, telemetry, credentials and private Gold stay **outside Git**, in per-Run-ID artifacts. See the [complete filesystem and module layout](docs/WORKSPACE_LAYOUT.md).

## Our first engineering challenge: Melusense

An email often contains new text, replies, older quoted content, signatures and forwarded history. The assignment is to recognize their **source-anchored boundaries** without changing or deleting the original message.

```text
   EML bytes           Text input
       |                    |
   MIME decode               |
       +----------+---------+
                  |
        Immutable source view
                  |
       Canonical line / header roles
                  |
        TOML language dictionaries
                  +
             bounded Regex
                  |
       Reply · Forward · Signature · Footer
                  |
          Candidate registry
                  |
      Deterministic BoundaryReviewer
                  |
        KEEP_ALL safety gate
                  |
       JSON + provenance + offsets
```

**Dictionary?** Curated words and header variants for EN/DE/FR/ES. **Regex?** Fast, bounded structural pattern matching. **Reviewer?** Checks evidence, competing candidates, negative contexts and exact original positions; uncertain cases abstain. **Classifier?** *Not part of this coding assignment*: prior FN-Recovery experiments did not prove additive benefit. An optional LLM/classifier recovery stage can be researched independently **after** establishing a rules-only baseline, never by weakening KEEP_ALL.

Why build deterministic software in an LLM era? Common MIME/headers and known reply structures can often be processed without repeatedly paying for generative tokens. The **speed/cost versus generalization** trade-off is something we will *measure*, not assume.

## Repository map

```text
melusense-benchmark/
├── README.md                # Start here: project and benchmarks
├── MANIFEST.md              # Navigation
├── AGENTS.md                # Binding rules for candidate agents
├── TASKS.md                 # Frozen, all-unchecked benchmark assignment
├── config/
│   ├── budget.json          # Shared resource and run limits
│   └── models.json          # Candidate profiles; deployment NOT verified
├── docs/
│   ├── BENCHMARKS.md        # Method, definitions and official links
│   ├── WORKSPACE_LAYOUT.md  # Per-agent directory and branch contract
│   ├── contract.md          # Immutable parser API and safety
│   └── evaluation.md        # Independent evaluator & isolation
├── melusense/
│   └── api.py               # Deliberately raises NotImplementedError
├── tests/                   # Unchanged visible fixtures/acceptance
└── tools/                   # Read-only scaffold verifier
```

Candidate-created modules (MIME, canonical parser, TOML dictionaries and processors) follow the same required layout in [AGENTS.md](AGENTS.md). No production Melusense code or private messages are included in this starter.

## Start from zero

The old bases remain available. **The documentation-rich task baseline is `benchmark/base-v3`**; the coordinator must verify and record its full SHA before giving it to any agent. Never overwrite `benchmark/base-v1` or `benchmark/base-v2`.

```bash
git clone git@github.com:validatusinternal/melusense-benchmark.git
cd melusense-benchmark
git fetch origin benchmark/base-v3
git rev-parse origin/benchmark/base-v3
python3 -B tools/verify_scaffold.py
python3 -B -m unittest discover -s tests -p 'test_scaffold.py'
python3 -B -m unittest discover -s tests -p 'test_acceptance.py'
```

**Expected on untouched starter:** scaffold PASS, acceptance FAIL because the implementation is intentionally missing. These are inspection commands, **not** a benchmark launch. Only the coordinator may provision isolated trials, model endpoints, hidden scoring, and a real Run-ID.

**DGX Spark docs:** [NVIDIA Developer](https://developer.nvidia.com/topics/ai/dgx-spark) · [vLLM](https://docs.vllm.ai/en/latest/). No real Kolibri/Mistral/GLM/Qwen results are claimed by this repository snapshot.

---

*Build reproducibly. Measure independently. Keep every failure.*
