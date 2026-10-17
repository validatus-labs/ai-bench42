# Evaluation and freeze contract — base-v3

**Status: NOT STARTED.** The coordinator pins the exact `benchmark/base-v3` SHA outside the candidate sandbox. Preserve previous `benchmark/base-v1` and `benchmark/base-v2` snapshots.

1. **Immutable assignment:** verify exact tree, instructions, tests, model catalog and budgets before creating any candidate trial. Existing dirty/changed/ambiguous state must fail closed—not silently reset, clean or overwrite.
2. **Models and seeds:** each eligible model gets the same source snapshot, prompts/test data/tool permissions and the seeds 41/42/43. The model catalog is illustrative, not a claim that every backend can run. Pin exact model checkpoint, tokenizer, serving setup, context and quantization in a per-run manifest.
3. **Separate execution:** enforce isolation outside Git. Workers must not access reference implementation, competitor source, corpus/HPI Gold, hidden tests, other runs, host HOME, Git credentials, shared Git object stores or unrestricted network endpoints.
4. **One result branch per model × seed:** a worker uses a Git-free isolated export; after freeze the coordinator may preserve code in `trial/<model-slug>/seed-<n>`. Never continue another model's branch; divergent state requires a new Run-ID.
5. **Idempotence:** same source/config/test/model/seed fingerprint => verify/reuse complete artifacts. Different input => new Run-ID, never overwrite earlier metrics. Keep raw bounded logs and unsuccessful attempts.
6. **Candidate implementation:** untouched fixture/API safety contract, rules-only parser, `authorized_removals=[]`. Initial scaffold checks pass; initial acceptance fails by design; candidate must make acceptance pass without changing tests.
7. **Independent evaluation:** freeze final candidate tree. Only evaluator sees rights-cleared HPI Gold/hidden tests; report TP/FP/FN/F1, exact boundaries, abstentions, source preservation and unsupported cases without self-certification.
8. **Separate scores:** serving metrics (AIPerf), general IFEval/MMLU-Pro/BBH, SWE-bench/BFCL and Melusense applied coding are complementary measures. Report code quality and run cost separately.
9. **No classifier gate:** training an FN logistic classifier, Synthetic FN, model-based deletion or extra LLM inference is not part of this benchmark; optional research needs its own separately frozen experiment.

[Required directory contract](WORKSPACE_LAYOUT.md) · [Main task](../TASKS.md) · [API contract](contract.md).
