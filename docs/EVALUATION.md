# Evaluation and freeze contract — Brave offline AI-Bench42

This document defines the Brave-based coding benchmark. The coordinator pins the exact offline source SHA and verifies worker controls before each trial.

The [automated experiment controller](PIPELINE.md) executes the phases and
combines their evidence. Its isolated visible-test run and request-bound
independent scorer receipts do not change the evaluation rules below.

1. **Immutable assignment:** verify exact tree, instructions, tests, model catalog and budgets before creating any candidate trial. Existing dirty/changed/ambiguous state must fail closed—not silently reset, clean or overwrite.
2. **Research-tool parity:** pin the actual approved **Brave + Playwright + MCP** binary hashes, server/tool schema, configuration, runtime identity, externally enforced public HTTPS research policy, service-worker blocking and network/worker isolation. Demonstrate a real MCP tool-call from each candidate model inside its worker. No Chromium install/fallback as a side effect. All candidates must receive the same browser affordances, task scope and budgets; log allowed/blocked/retried navigation. Verify public client and parser-source pages are reachable while private/internal targets remain denied. Browser origin filtering does not create a firewall. Pin the package SHA and complete independent preflight before each trial.
3. **Required HPI development data:** supply the exact same 12-pair ASF/TRAIN visible bundle from `tools/greenfield.py hpi-bundle` to every Phase-4 model and seed; record its SHA-256 in each run manifest. Each worker must run its parser on all 12 examples and report per-example results, failures and the mapping used for annotation comparisons. Missing rights/privacy or worker-disclosure approval, missing data or a different bundle blocks C00; synthetic fixtures cannot substitute for this shared input. TRAIN results are development evidence, not held-out accuracy. Hold out independent HPI TEST/EVAL, private Melusense reference code and private Gold.
4. **Models and seeds:** each eligible model gets the same source snapshot, prompts/test data/tool permissions and the seeds 1/2/3. The model catalog is illustrative, not a claim that every backend can run. Pin exact model checkpoint, tokenizer, serving setup, context and quantization in a per-run manifest.
5. **Separate execution:** enforce isolation outside Git. Workers may inspect public parser/regex source pages through approved Brave MCP and record provenance/license for adapted rules. They must not access the private original Melusense reference implementation, protected corpus/HPI Gold, hidden tests, other runs, host HOME, Git credentials, shared Git object stores or internal network endpoints.
6. **One result branch per model × seed:** a worker uses a Git-free isolated export; after freeze the coordinator may preserve code in `trial/<model-slug>/seed-<n>`. Never continue another model's branch; divergent state requires a new Run-ID.
7. **Idempotence:** same source/config/test/model/seed fingerprint => verify/reuse complete artifacts. Different input => new Run-ID, never overwrite earlier metrics. Keep raw bounded logs and unsuccessful attempts.
   Keep each prior receipt under its original run and seed identity.
8. **Candidate implementation:** frozen fixture/API safety contract, rules-only parser, `authorized_removals=[]`. Review research URL/date/license-to-rule-to-positive/negative-test traceability for client and language variants; public examples are not automatic evidence of parser correctness. A backward-compatible `ml_mode="off"` flag and a **reserved/unsupported** `recover` mode are tested only for interface design; no classifier inference/training or weights are allowed. Include a minimal local offline CLI with `--ml-mode off|recover` as documented in [CONTRACT.md](CONTRACT.md). Initial scaffold checks pass; initial acceptance fails by design; candidate must make acceptance pass without changing tests.
9. **Independent evaluation:** freeze final candidate tree. Only evaluator sees rights-cleared HPI Gold/hidden tests; report TP/FP/FN/F1, exact boundaries, abstentions, source preservation and unsupported cases without self-certification.
10. **Separate scores:** serving metrics (AIPerf), general IFEval/MMLU-Pro/BBH, SWE-bench/BFCL and Melusense applied coding are complementary measures. Report code quality and run cost separately.
11. **No classifier gate:** training an FN logistic classifier, Synthetic FN, model-based deletion or extra LLM inference is not part of this benchmark. The explicit off-only/recover-unsupported interface may be scored narrowly under API extensibility, **never as ML detection accuracy**. Actual classifier research needs its own separately frozen experiment.

## Visible mode and CLI cases

The checked-in `tests/test_reserved_ml_mode.py` applies to every candidate.
It checks default versus explicit `off` parity for both APIs, a documented
`recover` exception, rejection of unknown modes, and a local synthetic CLI
case. It blocks socket creation in the direct API cases; the CLI case checks
exit status, restricted output permissions, no overwrite and no output from
`recover`. The visible text case checks CRLF preservation and
`authorized_removals=[]`. These tests do not independently prove absence of
model imports, all MIME/client behavior or comprehensive input immutability;
those remain contract requirements for candidate tests and independent review.
Keep all provided tests unchanged. New candidate tests join the same reviewed
baseline for every model. Passing a reserved-mode test demonstrates API
discipline, not classifier accuracy.

[Runbook and worker layout](RUNBOOK.md) · [Candidate source layout](../AGENTS.md#required-candidate-source-layout) · [English task prompt](OFFLINE_AGENT_PROMPT.md) · [Main task](../TASKS.md) · [API contract](CONTRACT.md).
