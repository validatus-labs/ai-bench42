# ModelBench — One lab. Many models. Same evidence.

> **OWNER-APPROVED TASK CONTRACT; RUNTIME NOT READY:** This repository defines the shared offline Brave/Playwright-MCP coding assignment. Approval of the task structure does **not** qualify the deployed tools, isolation or evaluator, or authorize Phase-4 C01–C07. Existing DGX Spark worktrees and P1–P3 receipts remain untouched.

*How good is an LLM when it has to build something that actually works?*

## TL;DR — Too long; didn't read

We give **Kolibri, Mistral Small 4, GLM-5.3 Flash, Qwen and other models** the same engineering challenge, tools and budget. We measure **speed, reasoning, tool use and real coding quality**—and keep the code, failures and costs, not just a leaderboard score. Our first challenge is **Melusense**: independently build a multilingual email parser from an empty starter.

![Server racks and cabling in a research data center](https://images.unsplash.com/photo-1775519520461-6b6e068d9250?auto=format&fit=crop&w=1400&h=300&q=80)

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

**Classifier?** No model training or classifier inference in this coding benchmark. The proposed new contract requires only a **reserved `--ml-mode off|recover` switch**: `off` is the rule-only implementation; `recover` must say explicitly that it is not implemented. This tests clean extensibility, **not** ML accuracy. Future real FN-Recovery remains a separate experiment. [Exact extension contract →](docs/BUILD_CONTRACT.md).

## Same verified research tools; optional real TRAIN examples.

Every agent must receive the **same independently qualified, hash-pinned Brave/Playwright MCP browser tools**, approved documentation origins and budgets. The coordinator may separately provision **12 HPI/Quagga ASF TRAIN email/annotation pairs** only after explicit data-rights, privacy and worker-disclosure approval and SHA-256 equality. TRAIN is optional; independent TEST/EVAL Gold remains sealed.

The existing `tools/greenfield.py` still includes an **obsolete Chromium installer** and is **not** the approved Brave verifier. Do **not** invoke its `install` or `greenfield` operations. The coordinator must qualify the *existing* Brave/MCP toolchain and effective sandbox/egress before starting any agent. No GitHub access is needed on Spark. [Exact requirements →](docs/RESEARCH_TOOLS.md).

Browser MCP must actually be wired into every coding agent. `--network-isolated` is an **operator attestation**, not a firewall; the coordinator must enforce sandbox and egress restrictions externally. HPI download is **not automatic**: it requires documented rights/privacy approval.

[Playwright deployment & fairness →](docs/RESEARCH_TOOLS.md) · [HPI sample download and Gold protocol →](docs/HPI_TRAIN.md)

**Brave runtime gate:** The existing Brave/Playwright/Kilo-MCP installation is the chosen toolchain, but each model worker must pass real MCP calls and independently enforced filesystem/egress restrictions. A read-only Brave verification adapter is **not yet implemented or audited**; do not treat browser connectivity as worker isolation. [Research-tool requirements →](docs/RESEARCH_TOOLS.md).

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
│   ├── WORKSPACE_LAYOUT.md  # Portable offline workbench
│   ├── BUILD_CONTRACT.md    # Full required source/build ASCII tree
│   ├── OFFLINE_AGENT_PROMPT.md # Identical English agent task
│   ├── contract.md          # Parser API and safety
│   └── evaluation.md        # Independent scoring
├── melusense/
│   └── api.py               # Deliberately unimplemented
├── tests/                   # Frozen acceptance tests
└── tools/                   # Scaffold verification
```

Agents create matching `melusense/rules/`, `dictionaries/`, `processors/` and reviewer modules as specified in [AGENTS.md](AGENTS.md). The files are organized alike, but the implementations can differ. Agents never edit frozen tasks/tests; their progress stays in ignored `build/`, and independent evaluation stays outside the candidate sandbox.

[English reusable agent prompt](docs/OFFLINE_AGENT_PROMPT.md) · [Standard candidate build tree](docs/BUILD_CONTRACT.md) · [Agent contract](AGENTS.md) · [Workspace layout](docs/WORKSPACE_LAYOUT.md) · [Complete assignment](TASKS.md)

## Start from one offline package (after future freeze approval)

Only a **coordinator** with repository access records the exact owner-approved source SHA, exports a **Git-free** candidate starter, hashes it and transfers it to the machine. The DGX Spark and coding models do **not** need repository access. A merged task contract is **not** proof that a particular offline runtime/package has passed security or readiness qualification.

Every model receives the same English instruction in [OFFLINE_AGENT_PROMPT.md](docs/OFFLINE_AGENT_PROMPT.md), identical parser source/API tree in [BUILD_CONTRACT.md](docs/BUILD_CONTRACT.md), budgets and frozen tests. The coordinator checks a real Brave MCP tool call **from the actual isolated worker**, not only the historical Kolibri/Kilo host-open session, and confirms read/write/egress isolation before C01. The deliberately unimplemented starter must initially fail acceptance; those failures are expected, **not** candidate success.

No new coding-model trials, training, browser installations, server restarts or data disclosures are authorized merely by approval or merge of the task contract.

[DGX Spark](https://developer.nvidia.com/topics/ai/dgx-spark) · [vLLM](https://docs.vllm.ai/en/latest/) · [Evaluation protocol](docs/evaluation.md)

*Build independently. Measure what survives the tests.*
