# ModelBench — One lab. Many models. Same evidence.

*How good is an LLM when it has to build something that actually works?*

## TL;DR — Too long; didn't read

We give **Kolibri, Mistral Small 4, GLM-5.3 Flash, Qwen and other models** the same engineering challenge, tools and budget. We measure **speed, reasoning, tool use and real coding quality**—and keep the code, failures and costs, not just a leaderboard score. Our first challenge is **Melusense**: independently build a multilingual email parser from an empty starter.

![Server racks and cabling in a research data center](https://images.unsplash.com/photo-1775519520461-6b6e068d9250?auto=format&fit=crop&w=1400&q=80)

<sub>Photo: [Eric Stoynov / Unsplash](https://unsplash.com/photos/two-server-racks-filled-with-electronic-components-and-wires-k27hkqXuveo) · Unsplash License.</sub>

## The twist: use AI to need less AI

**We ask an LLM to build software that could make many LLM calls unnecessary.** Email history often follows recognizable structures—MIME, replies, forwards and signatures—that a deterministic parser can process without generating tokens. We test whether a coding agent can engineer that cheaper first stage **without sacrificing correctness or safety**.

That is the hypothesis, not a promised result.

## Four benchmarks. Four different questions.

| Phase | What do we learn? | Method & references |
|---|---|---|
| **01 — Speed** | How fast does the model process prompts and generate tokens under load? | [NVIDIA AIPerf](https://docs.nvidia.com/aiperf/getting-started/profiling-with-ai-perf) · [Prometheus](https://prometheus.io/docs/introduction/overview/) |
| **02 — Reasoning** | Can it follow instructions and solve hard questions? | [LightEval](https://huggingface.co/docs/lighteval/index) · [IFEval](https://github.com/google-research/google-research/tree/master/instruction_following_eval) · [MMLU-Pro](https://github.com/TIGER-AI-Lab/MMLU-Pro) · [BBH](https://github.com/suzgunmirac/BIG-Bench-Hard) |
| **03 — Tools & coding** | Can it call tools correctly and fix real software issues? | [BFCL](https://gorilla.cs.berkeley.edu/leaderboard) · [SWE-bench](https://github.com/swe-bench/SWE-bench) |
| **04 — Engineering** | Can it build the *same* reliable parser from zero? | [Melusense task](TASKS.md) · [API contract](docs/contract.md) |

**A model can produce 50 tokens per second and still write a broken parser.** Speed, correctness, code quality and token cost must be reported separately—not compressed into one mysterious score.

[What each benchmark means →](docs/BENCHMARKS.md)

## Same task. Three attempts per model.

> **Seed = a reproducible random starting point.** Each model attempts the same coding task three times (seeds **41, 42, 43**) to measure reliability, not just one lucky result. The seed improves reproducibility; GPU and agent runs may still differ.

```text
                     NVIDIA DGX Spark
                       vLLM + metrics
                             |
                   FROZEN TASK + BUDGET
                             |
                  +----------+----------+
                  |          |          |
                Kolibri    Mistral    GLM / Qwen / ...
                41/42/43   41/42/43   41/42/43
                  |          |          |
                  +----------+----------+
                             |
                  INDEPENDENT EVALUATION
                  Quality · Safety · Cost
```

One model × one seed = one **isolated coding trial**. The coordinator may later save its result on a branch such as `trial/kolibri-1/seed-41`; every worker starts from the **same frozen commit**, never another agent's solution. A Git branch stores code—it is **not** a security sandbox.

The DGX Spark is an example host, not a requirement for every trial. The exact served model revision, quantization, context, KV-cache settings and tool gateway must be pinned per run.

## What does the coding agent build?

```text
       RFC-822 email                Plain text
             |                          |
        MIME / charset                  |
             +------------+-------------+
                          |
                 Immutable source
                          |
               Canonical recognition
                          |
           TOML dictionaries + safe Regex
                          |
          Reply · Forward · Signature · Footer
                          |
                  BoundaryReviewer
                          |
                   KEEP_ALL gate
                          |
                JSON + exact spans
```

**Dictionaries** capture language-specific header words; **regex** finds structural patterns; the **BoundaryReviewer** checks competing evidence and original text positions. Uncertain cases abstain rather than delete: `authorized_removals=[]`.

**Classifier?** Not in this coding benchmark. Previous FN-Recovery research has not demonstrated enough additional benefit to make it a required step; future classifier/LLM recovery is a separate experiment.

## One clean repository. Repeatable agent output.

```text
melusense-benchmark/
├── README.md                # Why this lab exists
├── TASKS.md                 # All tasks open; frozen assignment
├── AGENTS.md                # Required candidate source layout
├── MANIFEST.md              # Navigation
├── config/
│   ├── budget.json          # Common limits and seeds
│   └── models.json          # Extensible model profiles
├── docs/
│   ├── BENCHMARKS.md        # Background and official links
│   ├── WORKSPACE_LAYOUT.md  # Branches, isolation, Run-IDs
│   ├── contract.md          # Parser API and safety
│   └── evaluation.md        # Independent scoring
├── melusense/
│   └── api.py               # Deliberately unimplemented
├── tests/                   # Frozen acceptance tests
└── tools/                   # Scaffold verification
```

Agents create matching `melusense/rules/`, `dictionaries/`, `processors/` and reviewer modules as specified in [AGENTS.md](AGENTS.md). The files are organized alike, but the implementations can differ. Agents never edit frozen tasks/tests; their progress stays in ignored `build/`, and independent evaluation stays outside the candidate sandbox.

[Agent contract](AGENTS.md) · [Directory & branch workflow](docs/WORKSPACE_LAYOUT.md) · [Complete assignment](TASKS.md)

## Start from zero

The frozen trial baseline is [**`benchmark/base-v3`**](https://github.com/validatusinternal/melusense-benchmark/tree/benchmark/base-v3) at commit `4fe60510526d1b929faaa52670296eee79e6dd3a`. The editorial README on `main` can evolve without altering that benchmark input.

```bash
git clone git@github.com:validatusinternal/melusense-benchmark.git
cd melusense-benchmark
git fetch origin benchmark/base-v3
git rev-parse origin/benchmark/base-v3
python3 -B tools/verify_scaffold.py
python3 -B -m unittest discover -s tests -p 'test_acceptance.py'
```

**Expected:** scaffold PASS; acceptance FAIL on the intentionally empty parser. This is a **not-started coding benchmark**, not evidence of successful Kolibri, Mistral, GLM or Qwen trials.

[DGX Spark](https://developer.nvidia.com/topics/ai/dgx-spark) · [vLLM](https://docs.vllm.ai/en/latest/) · [Evaluation protocol](docs/evaluation.md)

*Build independently. Measure what survives the tests.*
