# Evaluation methods

The main report combines three kinds of evidence: measured local results,
external developer-reported benchmarks and explicitly labelled expectations.
They must not be pooled into one score.

- General evaluation: 32 fixed English examples per task, repeated three times;
  temperature zero, 4,096 output tokens including reasoning. Capped answers remain
  in the denominator. Repetition does not create new independent questions.
- Tools: nine successful calls on three distinct simple cases. This is a basic
  protocol pilot, not full BFCL or multi-turn reliability.
- Coding: repeated development from an empty assignment, with supplied tests,
  independent supplemental probes and requirements review. Probe counts do not
  measure percentage completion. Guided and independent attempts are separate.
- External comparison: the report cites official model cards and the benchmark
  definition. Developer evaluations use different models/settings from local
  profiles. GLM and Aleph Alpha use different agent setups; figures are not a
  matched head-to-head comparison.

No completed local SWE-bench score, held-out email accuracy or general project
success probability is available. The full records retain experiment-specific
limits. [Model-card guidance](https://huggingface.co/docs/hub/model-cards) and
[HELM](https://arxiv.org/abs/2211.09110) inform the separation of scenarios,
metrics and limitations.

These reports are evaluation material, outside fresh candidate assignments.

[Quality assessment](kolibri-overview.md) · [Supporting results](README.md)
