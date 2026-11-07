# Kolibri-1 — Coding quality in practice

**Useful implementation ability; incomplete autonomous delivery.** That is the
clearest conclusion from our latest three independent attempts. Kolibri produced
working pieces and passed supplied tests in two trials, but no trial satisfied
the complete engineering task. This supports bounded assistance with review,
not an assumption that a long assignment can be left unattended.

We test a local model on a concrete business problem: building a multilingual
email parser that could later support ERP assistants, reply drafting and reports.
The candidate must preserve original text, decode MIME safely, expose attachment
metadata, identify quoted histories and make conservative boundary decisions.
It cannot call an LLM inside the finished parser or train a classifier.

## Latest independent cohort

The 6 November cohort used Kolibri-1 FP8 with the existing V5 K/V-cache
calibration, vLLM 0.29.0 and a configured 262,144-token context on DGX Spark.
Each seed received the same frozen starter, task, tests, approved TRAIN input and
tooling in its own isolated Kilo worker. No candidate received another trial's
code or review feedback. There was no total wall deadline.

| Trial | Supplied tests | Additional contract probes | Complete task |
| --- | --- | --- | --- |
| Seed 1 | 21/21 | 4/11 | Not accepted |
| Seed 2 | Starter remained unimplemented | No working parser | Not accepted |
| Seed 3 | 21/21 | 7/11 | Not accepted |

The additional probes are different from the supplied tests. Neither fraction
measures project completion or email-detection accuracy. Seed 2's infrastructure
checks and a negative CLI check are not counted as parser success.

The first implementation had multiple modules but left important components as
placeholders. The third handled more examples and independently demonstrated
its own 12 TRAIN executions. Nevertheless, MIME/attachment handling, integration,
safe CLI output and final evidence remained incomplete. Candidate-authored reports
also contained incorrect zero usage counts; coordinator accounting is used here.

Seed 2 read the scaffold but wrote no implementation. Its final response used
31,999 reasoning tokens and one answer token before hitting a 32,000-token ceiling.
That establishes a failed attempt under this model/client configuration. It does
not establish that more time alone would fix it or that the model can never solve
the task. The original total time limit had already been removed.

## What worked, and what did not

Kolibri can produce code that passes concrete examples, edit a multi-module
project and use tools. Each trial passed an actual model-issued browser-MCP
admission proof; connectivity was not merely assumed. Seed 3's better coverage
shows meaningful progress within the same task, not a consistent ability to finish.

The gap was carrying requirements through the complete implementation and
checking the final result beyond visible examples. For a user, this matters more
than a superficially green test summary: a parser can pass ordinary text fixtures
while mishandling a MIME message or failing to connect required components.

Earlier experiments include a separate independent attempt with 24/27 probes
and a guided attempt with partial progress. They used different conditions and
are retained as historical cohorts. They are not additional successes in this
three-seed comparison. Earlier small general-evaluation/calibration results also
remain separate; calibration is not a demonstrated cure for coding completeness.

## Practical interpretation

Start with small changes, explicit acceptance criteria and independently checked
outputs. The current evidence does not justify unattended email processing,
ERP/database changes or security decisions. Direct tests of those applications
are still needed; German business quality and human productivity savings were
not measured by this parser exercise.

Published function-level and repository-repair benchmarks answer different
questions from assembling a complete new application. A high score there can
coexist with this result. We have not run a matched local Mistral, GLM or Qwen
comparison, so switching models is a hypothesis to test, not a measured remedy.

Our contribution is a concrete delivery test with preserved failures, independent
review and measured effort. It is a case study of one task under documented
conditions, not proof of general incapability or a universal model ranking.

[Results](README.md) · [Methodology](methodology.md) · [Cohort evidence](evidence/kolibri-20261106.json)
