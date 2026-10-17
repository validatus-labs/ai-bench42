# ModelBench — One lab. Many models. Same evidence.

*The answer might be 42. The code still has to pass.*

ModelBench asks a practical question: **Can a locally served language model build software that works, rather than merely write convincing code?**

## TL;DR

- **One challenge:** build **Melusense**, a multilingual email-structure parser, independently from an intentionally empty starter.
- **Many contenders:** Kolibri-1, Mistral Small 4, GLM-5.3 Flash, Qwen — and additional models once their endpoints qualify.
- **One coding harness:** **Kilo Code**; each model connects through an explicitly configured, reproducible local inference endpoint.
- **One research browser:** **Brave + Playwright MCP**, restricted to approved technical documentation. No GitHub access for coding workers.
- **Three shots per model:** **`x42` · `xx42` · `xxx42`** — separate, isolated attempts from the same frozen assignment.
- **Real evidence:** source changes, passing and failing tests, tool calls, token usage, elapsed time, safety checks and independent evaluation.
- **No model training in the scored challenge.** The final parser is rule-first; optional FN-Recovery research lives in the bonus section below.

## Four phases. Four different questions.

| Phase | Question | Evidence |
| --- | --- | --- |
| **01 · Speed** | How quickly and reliably does the model serve requests? | TTFT, prefill/decode, throughput, KV cache, queues, memory |
| **02 · Reasoning** | Does it follow instructions and reason over fixed examples? | IFEval, MMLU-Pro and BBH; samples, truncations and scorer versions recorded |
| **03 · Tools** | Can it use tools and solve programming tasks? | BFCL, SWE-bench where supported, execution traces and honest blockers |
| **04 · Engineering** | Can it independently build a safe, maintainable parser? | Frozen source and visible tests, independent hidden evaluation, time and token cost |

An impressive tokens/second figure cannot compensate for incorrect code. **Report quality, safety, speed and cost separately.** Smoke tests are not full benchmark scores. See [benchmark methodology](docs/BENCHMARKS.md).

## x42 · xx42 · xxx42

Every contender gets the **same task, initial code, tool permissions and resource limits**. Each attempt starts clean; no candidate may read another candidate or the reference solution.

```text
                        FROZEN CHALLENGE
                   same task · tools · budget
                               |
           +-------------------+-------------------+
           |                   |                   |
        Kolibri             Mistral             GLM / Qwen / ...
           |                   |                   |
    x42 · xx42 · xxx42  x42 · xx42 · xxx42  x42 · xx42 · xxx42
           |                   |                   |
           +-------------------+-------------------+
                               |
                      INDEPENDENT EVALUATOR
                     Quality · Safety · Effort
```

The names are a nod to the answer to life, the universe and everything. **They are run labels, not random seeds:** the pinned numeric seeds are still `41`, `42` and `43`, respectively, in [config/budget.json](config/budget.json). Run IDs, model revisions, context and quantization are recorded separately. A seed improves reproducibility; it does not guarantee identical model output.

## The first challenge: build Melusense

The coding agent must make a safe, deterministic pipeline from scratch:

```text
     Raw .eml / RFC-822         Unicode text
             |                      |
        MIME / charset              |
             +----------+-----------+
                        |
               Immutable source
                        |
               Canonical recognition
                        |
          TOML dictionaries + bounded regex
                 (EN · DE · FR · ES)
                        |
        Reply · Forward · Signature · Footer
                        |
             Deterministic BoundaryReviewer
                        |
                   KEEP_ALL gate
                        |
              JSON + exact source spans
```

The challenge is not to delete anything. **Original text stays intact**; ambiguous boundaries abstain, and `authorized_removals=[]` is mandatory. Candidate modules and the local CLI follow the same [build contract](docs/BUILD_CONTRACT.md), [API contract](docs/contract.md) and [tasks C00–C07](TASKS.md).

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

## One workbench, predictable output

```text
modelbench/                         # logical offline workspace root
├── README.md
├── AGENTS.md · TASKS.md · MANIFEST.md
├── config/                         # common limits and model/tool profiles
├── docs/                           # one English prompt, API and build contract
├── tools/                          # scaffold and coordinator utilities
├── melusense/                      # deliberately unfinished parser starter
├── tests/                          # frozen, visible tests
├── build/runs/<run-id>/workspace/  # ONE isolated model attempt
├── evidence/runs/<run-id>/         # coordinator-only technical receipts
└── reports/runs/<run-id>/          # coordinator/evaluator findings

evaluator-private/                  # protected outside worker mounts
```

The `build/`, `evidence/` and `reports/` directories are **generated, Git-ignored outputs**, not proof that any trials have run. No worker may mount the coordinator root or another run. The complete ASCII tree is in [BUILD_CONTRACT.md](docs/BUILD_CONTRACT.md) and [WORKSPACE_LAYOUT.md](docs/WORKSPACE_LAYOUT.md).

## How to run a challenge

1. **Coordinator:** select the approved exact source SHA, package it without Git history, verify hashes on both sides and pin the model/tool profile.
2. **C00 preflight:** prove real agent-to-MCP and agent-to-model operation **inside the isolated worker**, plus effective browser, filesystem and network restrictions. Missing proof means stop.
3. **Coding agent:** use the **same [English task prompt](docs/OFFLINE_AGENT_PROMPT.md)** and independently implement C01–C07. The empty starter deliberately fails initial acceptance tests.
4. **Evaluator:** freeze the result, run authorized hidden checks separately and report correctness, safety, time, tokens and failures. Never let an agent grade its own code.

The **assignment has been approved, but this README does not claim the model-specific runtime or Phase 4 is READY**. Existing historical P1–P3 receipts keep their original scope; no Phase-4 candidate result is claimed. The model server and existing Spark evidence are not changed by GitHub documentation.

## Bonus round · Recovery Lab (optional, unscored)

**Want to explore whether a classifier can find boundaries missed by rules?** That is a separate playground, **not part of the x42/xx42/xxx42 coding score**.

- The scored parser runs with `--ml-mode off`. The `--ml-mode recover` option is only a reserved extension point and must clearly report *not implemented*.
- For a future, separately versioned experiment, you may research, train or compare an FN-Recovery classifier **only on rights-cleared TRAIN material**, with separately authorized tools and compute.
- Evaluate additional true positives **and** false positives on independent, sealed human Gold. Keep `KEEP_ALL`, preserve every source byte and never turn candidate detection into automatic deletion.
- No hidden TEST/EVAL data, real correspondence or trained weights belong in ordinary coding-worker packages or public reports.

If you want the bonus challenge, start with the [HPI TRAIN data/rights protocol](docs/HPI_TRAIN.md) and the [reserved extension API](docs/BUILD_CONTRACT.md). It needs its **own approval, dataset split, run IDs and independent evaluation**, outside the main benchmark.

*Build independently. Measure what survives the tests.*
