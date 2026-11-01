# How we measure — and what the results mean

We ask whether a coding agent can turn a fixed assignment into complete, safe,
tested software. Published coding scores provide context; our own observations
describe one development task under recorded conditions.

## Four questions, separate results

| Phase | Question | Reporting boundary |
| --- | --- | --- |
| 1 — Serving | Can the model run and respond at the requested capacity? | Latency, throughput and accepted context do not establish answer quality. |
| 2 — General evaluation | Does it follow instructions and solve selected questions? | Small fixed selections, not complete benchmark suites. |
| 3 — Tools and coding | Can it choose tools and complete bounded actions? | Basic tool proof succeeded; no completed local SWE-bench score. |
| 4 — Project development | Can it deliver the whole parser? | Supplied tests, supplemental checks and requirements review remain separate. |

The general evaluation used 32 fixed English examples for each of IFEval,
MMLU-Pro and two BBH tasks, repeated three times at temperature zero. That is
128 unique questions, not 384 independent questions. The output allowance was
4,096 tokens including reasoning. All 53/384 capped baseline answers and
51/384 capped calibrated answers remained in the score denominator. MMLU-Pro
alone had 36/96 and 30/96 capped answers; its gap from the published 80.0% CoT
score cannot be interpreted as a measured loss of model capability.

Calibration changed K/V cache scales, not model weights. Mixed quality changes
do not establish a causal improvement: cache state, execution time and other
historical conditions were not fully controlled. The tool pilot's 9/9 calls
cover three distinct simple cases, not full BFCL or long-workflow reliability.

## Reference scope and evaluation boundaries

The private Melusense reference is a research candidate, not a certified production
system or a source of substitute Gold labels. Its multilingual infrastructure is
broader than independently validated language coverage. Its optional historical
recovery experiment is outside the rules-only coding challenge. Reference CI checks
software regressions and repository contracts; it does not establish blind parser
accuracy or attribute reference functionality to Kolibri.

The coding task evaluates delivery against its frozen requirements rather than
source-code similarity to the reference. Historical reference metrics, synthetic
checks and model-written tests are separate from held-out evaluation. The reference
and its data remain unavailable to workers. These pages disclose no reference
implementation; they do not provide full independent reproduction of its results.

## Independent work, guidance and direct repair

Independent trials receive the assignment and approved tools. Guided trials
add coordinator review and corrections. Direct repair by a different coding
agent is assisted development, never success attributed to Kolibri.

The latest independent trial passed all 21 supplied and ten self-authored tests,
plus 24/27 supplemental probes. Requirements review still found missing
integration and safety behavior. Passing 24/27 probes is not 89% project
completion. The guided trial also remained incomplete; two failing fixtures
were themselves invalid and are not counted as model defects. A final
client-limited answer was truncated, so the outcome does not isolate model
ability from harness behavior.

### Recorded effort

| Coding trial | Observed elapsed time | Model requests | Generated tokens | Tool calls |
| --- | ---: | ---: | ---: | ---: |
| Latest independent attempt | 28 min 32.01 s | 47 | 48,120 | 137 |
| Separate guided attempt | 68 min 44.28 s | 90 | 103,929 | 168 |

These are coding-phase counts. Each trial had its own additional readiness proof:
two requests, 1,696 generated tokens and four tools for the independent trial;
two requests, 548 tokens and four tools for the guided trial. Generated tokens
include reasoning. Guided elapsed time includes review waits, not measured human
labor. Summed guided request durations were 56 min 27.32 s, not pure compute time.
Planning/basic integration needed one/two correction rounds respectively; the
MIME stage ended on its third attempt. This is not a complete tally of human
interventions. No human-only baseline, monetary saving or productivity gain has
been measured. Different guidance and tool versions prevent causal timing comparisons.

## What published benchmarks add

[LiveCodeBench](https://github.com/LiveCodeBench/LiveCodeBench) tests programming,
execution and repair. [SWE-bench Verified](https://www.swebench.com/verified)
tests issue repair in existing repositories. Our parser task requires new-project
integration and delivery. These results answer related but different questions.
[FeatureBench](https://arxiv.org/abs/2602.10975) and
[SWE-Lancer](https://openai.com/index/swe-lancer/) already evaluate broader
engineering work; a practical task is useful without being a novel benchmark idea.

The assessment labels external developer-reported scores and expectations.
Different agents, quantization, output budgets and tasks prevent a matched model
ranking. Repeating one project does not establish task diversity or a general
success probability. Held-out email accuracy, a qualified Gold/reference score
and matched local Mistral/GLM outcomes are not available.

## Rules for the next comparison

Use the same frozen assignment, data, tools and declared budgets for each
qualified model. Fix the complete acceptance criteria before development and
report failed and interrupted trials. Add different tasks, count review/correction
effort and compare with a human baseline before claiming productivity savings.
Keep independent and guided cohorts separate. Publish one model assessment per
evaluated model; retain per-run records as evidence rather than new reader reports.

These result documents stay outside fresh candidate assignments. No new coding
trial or benchmark freeze is created by reorganizing the reports.

[Results](README.md) · [Kolibri assessment](kolibri.md) · [Evidence](evidence/README.md)
