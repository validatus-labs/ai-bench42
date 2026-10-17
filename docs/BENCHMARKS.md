# Benchmark guide — one lab, four complementary questions

Benchmarks answer different questions; never collapse them into one unexplained “model score.” This project is an extensible **harness specification + applied coding starter**, not a completed evaluation or a promise that every candidate fits the DGX Spark.

| Phase | Question | Method | Official sources |
|---|---|---|---|
| **P1 Serving** | What is the real latency/throughput/memory/queue behavior under identical prompts? | NVIDIA AIPerf, vLLM serving statistics and one central Prometheus endpoint. Test concurrency 1/2/4; distinguish client queueing from actual parallel decode. | [AIPerf](https://docs.nvidia.com/aiperf/getting-started/profiling-with-ai-perf), [vLLM](https://docs.vllm.ai/en/latest/), [Prometheus](https://prometheus.io/docs/introduction/overview/) |
| **P2 General quality** | Can the model follow precise instructions and reason on fixed questions? | Hugging Face LightEval as a runner; pin IFEval, MMLU-Pro, BIG-Bench Hard, prompts, sample IDs, truncation behavior and scorer. | [LightEval](https://huggingface.co/docs/lighteval/index), [IFEval](https://github.com/google-research/google-research/tree/master/instruction_following_eval), [MMLU-Pro](https://github.com/TIGER-AI-Lab/MMLU-Pro), [BBH](https://github.com/suzgunmirac/BIG-Bench-Hard) |
| **P3 Agentic coding** | Does the model use tools and solve authentic software issues? | BFCL scores function/tool calls; SWE-bench Verified measures issue-to-patch outcomes. Keep smoke subsets and full runs separate. | [BFCL](https://gorilla.cs.berkeley.edu/leaderboard), [SWE-bench](https://github.com/swe-bench/SWE-bench) |
| **P4 Applied engineering** | Can it independently build a correct, safe, maintainable parser with a reproducible workflow? | Same frozen Melusense starter for every model; evaluate frozen candidate output and licensed HPI Gold independently. | [TASKS](../TASKS.md), [contract](contract.md), [HPI Quagga](https://github.com/HPI-Information-Systems/Quagga) |

**Terms:** TTFT = time to first token. Prefill = processing prompt tokens. Decode = generating subsequent tokens. KV-cache = Attention history storage; FP8 and BF16 consume different amounts of memory and must be tracked per run. F1 = harmonic mean of precision and recall; a high Silver-label self-score is **not** an independent Gold score.

## DGX Spark and candidate registry

Model examples: **Kolibri-1**, **Mistral Small 4**, **GLM-5.3 Flash**, **Qwen**, **DeepSeek**. Register exact hosted model ID, checkpoint/revision, weights dtype/quantization, tokenizer, context, KV-cache dtype/scaling, loaded sequence count and tool-call formatting **before** running. If a model/backend combination cannot support the frozen task, mark **BLOCKED/UNSUPPORTED**; never silently shrink context or replace a model.

[Model profiles (unqualified examples)](../config/models.json) · [Shared budgets](../config/budget.json) · [NVIDIA DGX Spark](https://developer.nvidia.com/topics/ai/dgx-spark).

## Scientific and operational limits

- These benchmarks measure **task-specific observed behavior**, not the full intelligence of a model.
- For P4, judge code quality separately from end-to-end correctness; passing tests does not certify maintainability.
- A private human-annotated, licensed evaluation corpus is evaluator-only. A parser rule, weak Silver label or model prediction is not Gold.
- In the old Melusense research, optional FN-Recovery lacked demonstrated benefit and suffered training-label shortcuts; no classifier is required in this assignment.
- Preserve failed attempts and report tokens, time, memory, mistakes and safety violations alongside success.

**Status of this repository:** A frozen starter, tests and documentation exist. No completed Kolibri/Mistral/GLM/Qwen AgentBench results are supplied here. External coordinator runners and real sandbox enforcement require separate verification.
