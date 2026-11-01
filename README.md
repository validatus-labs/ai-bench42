# AI-Bench42 — LLM & Coding Agent Benchmarks

*One lab. Many models. Same evidence.*

How good is an LLM when it has to build something that actually works?

## What have we learned?

**Kolibri writes useful code and uses tools, but did not complete the full parser
in the reviewed trials.** We test complete delivery and required supervision,
not just isolated coding answers. A matched Mistral/GLM comparison is still open.

[Results at a glance](docs/reports/README.md) ·
[Kolibri: abilities and limits](docs/reports/kolibri.md) ·
[How we measure](docs/reports/methodology.md)

## TL;DR — Too long; didn't read

**Bootstrap your DGX Spark with one command:**

```bash
python3 scripts/bootstrap.py --brave --playwright --maintenance --health --kolibri --on
```

[Requirements and setup →](scripts/deploy/README.md) · [Run benchmarks, the coding task and get one report →](docs/PIPELINE.md)

Our comparison protocol gives **Kolibri, Mistral Small 4, GLM-5.3 Flash, Qwen
and other qualified models** the same engineering challenge, tools and budget.
**The reported model trials currently concern Kolibri.** Other named models are
planned contenders; a matched local comparison has not yet been completed.

The four phases examine:

- **Speed**
- **Reasoning**
- **Tool use**
- **Real coding quality**

We also preserve the code, failures, and costs—not just a leaderboard score. Our first challenge is **Melusense**: each model must independently build a multilingual email parser from an empty starter.

![Server racks and cabling in a research data center](https://images.unsplash.com/photo-1531746790731-6c087fecd65a?auto=format&fit=crop&w=1400&h=400&q=80)

<sub>Photo: [Franck V. / Unsplash](https://images.unsplash.com/photo-1531746790731-6c087fecd65a) · Unsplash License.</sub>

## Why this task matters

**We ask an LLM to build software that could make repeated LLM processing
unnecessary.** Business emails often repeat earlier messages, signatures and
footers. A useful preprocessing layer should identify that structure while
preserving the original message and making uncertainty visible. This could
reduce repeated context in ERP assistants, reply drafting and reporting;
actual token, time and cost savings remain unmeasured.

Melusense is our private research reference for this problem. AI-Bench42 gives
coding agents a separate unimplemented assignment with explicit requirements.
The reference, independent model attempts and assisted repairs are different
artifacts. Workers do not receive the finished reference implementation.

## Real-mail development examples

Every Phase-4 parser trial uses the same fixed HPI/Quagga TRAIN examples and
annotations. Import, verification and use of the identical worker bundle are
required for comparability; see the [HPI TRAIN protocol](docs/HPI_TRAIN.md).

New to the benchmark? Start with the [command-by-command beginner guide](docs/QUICKSTART.md)
to download and pin the source package. The [runbook](docs/RUNBOOK.md) covers
worker isolation and trial operation.

<a id="four-benchmarks-four-different-questions"></a>

## Four phases. Four different questions.

| Phase | What do we learn? | Method & references |
|---|---|---|
| **01 — Speed** | How fast does the model process prompts and generate tokens under load? | [NVIDIA AIPerf](https://docs.nvidia.com/aiperf/getting-started/profiling-with-ai-perf) · [Prometheus](https://prometheus.io/docs/introduction/overview/) |
| **02 — Reasoning** | Can it follow instructions and solve hard questions? | [LightEval](https://huggingface.co/docs/lighteval/index) · [IFEval](https://github.com/google-research/google-research/tree/master/instruction_following_eval) · [MMLU-Pro](https://github.com/TIGER-AI-Lab/MMLU-Pro) · [BBH](https://github.com/suzgunmirac/BIG-Bench-Hard) |
| **03 — Tools & coding** | Can it call tools correctly and fix real software issues? | [BFCL](https://gorilla.cs.berkeley.edu/leaderboard) · [SWE-bench](https://github.com/swe-bench/SWE-bench) |
| **04 — Engineering** | Can it build the *same* reliable parser from zero? | [Melusense task](TASKS.md) · [API contract](docs/CONTRACT.md) |

**A model can produce 50 tokens per second and still write a broken parser.** Speed, correctness, code quality and token cost must be reported separately—not compressed into one mysterious score.

This table describes the intended protocol. Available results include bounded
pilots and fixed task selections; no completed local SWE-bench score is available.

[What each benchmark means →](docs/BENCHMARKS.md)

## Same task. Three attempts per model.

**One model × one seed = one isolated coding trial.** This is the target
comparison design: each contender receives the same frozen assignment, tools and
budget, without access to another model's solution. Historical diagnostic and
guided trials include recorded differences and are not pooled into a matched ranking.

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

### Research the formats before writing rules

Each coding worker should use the same approved public-web research tools to examine how Gmail, Outlook, Thunderbird, Apple Mail (including iPhone/iPad), and named Android mail apps render replies, forwards, signatures and footers. Android is a platform, so record the actual app and version when a format depends on them. Compare localized header words and date/address forms, starting with English, German, French and Spanish; add another language only with documented examples and tests. Public vendor help, standards, localization resources and public parser/regex examples are in scope, including public source pages on GitHub.

For each useful example, record its URL, access date and license/provenance, then adapt dictionary entries or **bounded** regex rules in the candidate parser. Add positive examples and negative lookalikes so a quoted header, code block or ordinary body text does not become a false boundary. This is rule design and checking, not model training. Public examples supplement the required rights-approved HPI TRAIN set; hidden Gold and other candidates' output remain unavailable. See the [research contract](docs/RESEARCH_TOOLS.md) and [candidate task](TASKS.md).

**Classifier?** No model training or classifier inference in this coding benchmark. The benchmark contract requires only a **reserved `--ml-mode off|recover` switch**: `off` is the rule-only implementation; the `recover` mode must raise an explicit `NotImplementedError`. This tests clean extensibility, **not** ML accuracy. Future real FN-Recovery remains a separate experiment. [Exact extension contract →](docs/CONTRACT-BUILD.md).

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
- Browser research may use public email-client documentation, localization references and public parser/regex examples through the approved Brave MCP. The same read-only web scope and budget apply to every worker; egress and file access must be enforced outside the browser.
- Each candidate may see only visible fixtures and explicitly approved development examples. Hidden tests, private Gold, the existing Melusense implementation and competitor runs remain inaccessible.
- The coordinator saves technical evidence; a **separate evaluator** scores each frozen candidate. Missing tests or unsupported platforms stay `BLOCKED` or `NOT_EVALUATED` — never a made-up zero or success.

**Offline** describes the Git-free starter, local build and local model inference; it does not prohibit controlled public-web research. Workers may inspect public GitHub source pages through the approved browser, but they do not clone repositories or receive repository credentials. Research traffic uses controlled access separate from model inference. See the [research-tool contract](docs/RESEARCH_TOOLS.md).

## Bonus round · Recovery Lab (optional, unscored)

**Want to explore whether a classifier can find boundaries missed by rules?** That is a separate playground, **not part of the scored coding benchmark**.

- The scored parser runs with `--ml-mode off`. The `--ml-mode recover` option is only a reserved extension point and must clearly report *not implemented*.
- For a future, separately versioned experiment, you may research, train or compare an FN-Recovery classifier **only on rights-cleared TRAIN material**, with separately authorized tools and compute.
- Evaluate additional true positives **and** false positives on independent, sealed human Gold. Keep `KEEP_ALL`, preserve every source byte and never turn candidate detection into automatic deletion.
- No hidden TEST/EVAL data, real correspondence or trained weights belong in ordinary coding-worker packages or public reports.

If you want the bonus challenge, start with the [HPI TRAIN data/rights protocol](docs/HPI_TRAIN.md) and the [reserved extension API](docs/CONTRACT-BUILD.md). This optional experiment requires its **own approval, dataset split, run IDs, and independent evaluation**. It remains outside the main benchmark.

*Build independently. Measure what survives the tests.*
