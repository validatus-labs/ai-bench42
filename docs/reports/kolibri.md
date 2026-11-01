# Kolibri-1 — Coding Quality in Practice

**Kolibri can write useful code, follow explicit instructions and operate tools.
Our experiments did not establish reliable delivery of a complete software
project.** These observations support trying it as a coding assistant on
bounded changes with review; broader reliability remains unmeasured. The missing capability in this task was carrying
all requirements through integration, edge cases and final verification.

## What our measurements show

| Capability | Observed result | Practical meaning |
| --- | --- | --- |
| Instruction following, IFEval | 91.67% before / 88.54% after cache calibration | Good results on the tested constraints |
| Knowledge/reasoning, MMLU-Pro | 45.83% / 50.00% | Challenging answers were less reliable under this answer budget |
| BBH date / three-object logic | 84.38% / 100% in both cohorts | Strength on these narrow reasoning tasks |
| Basic tool calling | 9/9 calls across three distinct simple cases | Can select tools and supply arguments; long workflows remain a different test |

General scores average three repetitions of the same 32 English examples per
task. Outputs were limited to 4,096 tokens including reasoning; 53/384 baseline
and 51/384 calibrated responses hit that limit and remained scored. Calibration
changed cache scales, not weights, and produced mixed quality changes.

In the latest completed independent parser attempt, Kolibri passed all 21 supplied
tests, ten additional tests it wrote and 24/27 independent supplemental probes.
It nevertheless left required detection components disconnected from the main
API, with missing malformed-message warnings and unsafe output-file handling.
**24/27 is a probe count, not 89% project completion.** The model ended naturally
after about 29 minutes with remaining budgets. A separate guided experiment
made integration progress but also ended before full acceptance. Its final answer
was truncated as the client reduced its output allowance; that limits attribution
to the model alone and does not explain all earlier defects. This demonstrates
useful implementation ability alongside insufficient completeness checking.

## Why published coding scores and our result can both be true

The published results below are external reports, not our measurements:

| Evaluation, % | Kolibri-1 | Mistral Small 4 | GLM-5.3-Flash |
| --- | ---: | ---: | ---: |
| LiveCodeBench v6 | 85.9 | 71.2 | — |
| HumanEval+ | 92.7 | 94.7 | — |
| SWE-bench Verified | 66.4 | 60.8 | — |
| Terminal-Bench 2.1 | 27.7 | 21.0 | 84.3* |

Kolibri and Mistral values come from
[Aleph Alpha's common evaluation table](https://huggingface.co/Aleph-Alpha/Kolibri-1#evaluation),
using its stated evaluation setup and each model's documented settings.
They are developer-reported comparisons, not an independent ranking.
The starred GLM figure is from
[Z.ai's model card](https://huggingface.co/zai-org/GLM-5.3-Flash), using a different
agent and budget. A dash means no comparable result supplied here, not zero.

Function-level coding tests and programming problems reward solving bounded
tasks. [SWE-bench Verified](https://www.swebench.com/verified) measures issue
repairs in existing repositories: 66.4% describes resolved benchmark instances,
not the probability of finishing any new project. Our challenge requires a
multilingual parser built from an empty starter, including MIME, safety, integration
and honest delivery evidence. Good code fragments and passing limited tests can
coexist with an unfinished product. The published Terminal-Bench result already
suggests that strong bounded coding does not imply uniformly strong agent execution.

## What to expect from Mistral and GLM

**Mistral Small 4 is a credible alternative, not an evidenced automatic upgrade.**
The common table favors Kolibri on SWE-bench and Mistral slightly on HumanEval+.
Neither establishes who will finish our parser; a matched project comparison
is still missing.

**GLM-5.3-Flash is the stronger candidate to investigate for sustained agent work.**
That is an expectation from its much stronger reported terminal result, not a
demonstrated win here. Its evaluation used Claude Code, up to 65,536 output tokens
and a six-hour timeout. Different conditions prevent a numerical head-to-head
claim or qualify a local quantized deployment. Its 63.4% DeepSWE result is a different benchmark and must not be ranked
against Kolibri's 66.4% SWE-bench score.

For practical use, give Kolibri small, verifiable implementation steps and review
the result before relying on it. A model switch may improve completion, but only
the same project, inputs, review criteria and comparable budgets can establish
that. These small subsets and repeated attempts on one project establish neither
a general project-success rate nor held-out email accuracy.

The purpose is to measure the gap between code generation and complete delivery,
not to prove a model unsuitable in advance. Repeated attempts on this parser
remain one task. Independent and guided outcomes must stay separate.

[Results overview](README.md) · [Methodology and effort](methodology.md) ·
[Experiment evidence](evidence/README.md)
