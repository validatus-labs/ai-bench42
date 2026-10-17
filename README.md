# ModelBench — One lab. Many models. Same evidence.

*How good is an LLM when it has to build something that actually works?*

## TL;DR — Too long; didn't read

We give **Kolibri, Mistral Small 4, GLM-5.3 Flash, Qwen and other models** the same engineering challenge, tools and budget.

We measure:

- **Speed**
- **Reasoning**
- **Tool use**
- **Real coding quality**

We also preserve the code, failures, and costs—not just a leaderboard score. Our first challenge is **Melusense**: each model must independently build a multilingual email parser from an empty starter.

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

**One model × one seed = one isolated coding trial.** Every model receives the same frozen assignment, tools and budget. No agent can inspect another model's solution.

```text
                   NVIDIA DGX SPARK
                    vLLM + Metrics
                          |
                   KILO CODE HARNESS
                          |
                 FROZEN TASK + BUDGET
                          |
        +-----------------+-----------------+
        |                 |                 |
      KOLIBRI           MISTRAL           GLM / QWEN
        |                 |                 |
     K42-1/2/3         M42-1/2/3         G42-1/2/3
                                        Q42-1/2/3
        |                 |                 |
        +-----------------+-----------------+
                          |
                INDEPENDENT EVALUATION
                Quality | Safety | Cost
```

**The answer is 42. The evidence is in the code.**

The `42` series gives each trial a recognizable identity:

| Model | Attempt 1 | Attempt 2 | Attempt 3 |
|---|---|---|---|
| Kolibri | `K42-1` | `K42-2` | `K42-3` |
| Mistral | `M42-1` | `M42-2` | `M42-3` |
| GLM | `G42-1` | `G42-2` | `G42-3` |
| Qwen | `Q42-1` | `Q42-2` | `Q42-3` |

These are human-readable **run labels**, not random seeds. Attempts 1, 2, and 3 use the fixed numeric seeds 1, 2, and 3, respectively. The seed values are recorded in [config/budget.json](config/budget.json) for reproducibility. Each attempt starts from the same frozen source, never another agent's work. Models are benchmarked separately under the common resource budget.

The coordinator may preserve an output branch such as `trial/kolibri-1/seed-1` after freezing the candidate. A Git branch is **not** a worker security boundary. The DGX Spark is an example host, not a requirement. The exact model revision, context-window size, quantization, KV-cache configuration, and tool gateway are pinned for each run.

[Research tools, isolated workspaces & execution protocol →](docs/RESEARCH_TOOLS.md)

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

**Classifier?** No model training or classifier inference in this coding benchmark. The benchmark contract requires only a **reserved `--ml-mode off|recover` switch**: `off` is the rule-only implementation; the `recover` mode must raise an explicit `NotImplementedError`. This tests clean extensibility, **not** ML accuracy. Future real FN-Recovery remains a separate experiment. [Exact extension contract →](docs/BUILD_CONTRACT.md).

## Why Kilo Code?

**Kilo Code is our coding-agent harness — not the model, the inference server, or the browser.** It supplies the agent workflow for inspecting and editing files, running commands/tests, and invoking approved MCP tools.

We favor it for three practical reasons:

- **Plug in local models:** connect a vLLM/OpenAI-compatible endpoint by base URL and model ID, or use supported local providers such as Ollama and LM Studio. Context and tool-use capabilities can be configured per model.
- **Keep the workflow constant:** pin the Kilo build, tool permissions and agent instructions while swapping only the qualified model endpoint. This makes comparisons more meaningful.
- **Use one browser tool:** Brave + Playwright MCP is exposed through the same permission-controlled agent interface. A connected MCP server is not proof a model can actually use it; verify a real tool call for each contender.

Kilo Code supports these capabilities in its [OpenAI-compatible provider guide](https://kilo.ai/docs/ai-providers/openai-compatible), [VS Code agent guide](https://kilo.ai/docs/code-with-ai/platforms/vscode) and [MCP documentation](https://kilo.ai/docs/automate/mcp/using-in-kilo-code). A local model endpoint keeps **model inference** local; other Kilo integrations still need explicit network controls.

## Same tools, fair boundaries

- The coordinator prepares one **Git-free, SHA-256-verified offline package**. Workers do not clone GitHub or receive repository credentials.
- Each model gets an **isolated workspace**, its own clean browser profile and the same pinned Kilo, Brave/Playwright MCP tools and budgets.
- Browser research is limited to approved Python, RFC Editor, IETF Datatracker and MDN documentation. Egress and file access must be enforced by the sandbox, not merely a browser flag.
- Each candidate may see only visible fixtures and explicitly approved development examples. Hidden tests, private Gold, the existing Melusense implementation and competitor runs remain inaccessible.
- The coordinator saves technical evidence; a **separate evaluator** scores each frozen candidate. Missing tests or unsupported platforms stay `BLOCKED` or `NOT_EVALUATED` — never a made-up zero or success.

**Offline** means *no GitHub dependency in the coding worker*, not automatically *zero network access*. Permitted documentation requests use controlled access separate from the model-inference transport. See the [research-tool contract](docs/RESEARCH_TOOLS.md).

## Bonus round · Recovery Lab (optional, unscored)

**Want to explore whether a classifier can find boundaries missed by rules?** That is a separate playground, **not part of the scored coding benchmark**.

- The scored parser runs with `--ml-mode off`. The `--ml-mode recover` option is only a reserved extension point and must clearly report *not implemented*.
- For a future, separately versioned experiment, you may research, train or compare an FN-Recovery classifier **only on rights-cleared TRAIN material**, with separately authorized tools and compute.
- Evaluate additional true positives **and** false positives on independent, sealed human Gold. Keep `KEEP_ALL`, preserve every source byte and never turn candidate detection into automatic deletion.
- No hidden TEST/EVAL data, real correspondence or trained weights belong in ordinary coding-worker packages or public reports.

If you want the bonus challenge, start with the [HPI TRAIN data/rights protocol](docs/HPI_TRAIN.md) and the [reserved extension API](docs/BUILD_CONTRACT.md). This optional experiment requires its **own approval, dataset split, run IDs, and independent evaluation**. It remains outside the main benchmark.

*Build independently. Measure what survives the tests.*
