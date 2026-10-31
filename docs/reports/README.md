# AI-Bench42 — Reports

**Start with [What we learned from Kolibri](kolibri-overview.md).**
Kolibri generated useful code and used real tools. None of the reviewed coding
attempts completed the full email-parser challenge. The general evaluations
showed mixed results; cache calibration did not deliver a universal improvement.

These are 32 sanitized editorial editions of the retained result reports, with
failed trials and limitations preserved. Historical preparation reports describe
their own checkpoints; they are not current live-state claims. Read the
[methods and publication scope](METHODS.md) before reusing a result. The
[collection manifest](collection.json) inventories every edition and its content
hash. The manifest excludes itself; navigation and methodology are additional
documents, not additional experiments.

## Main findings

| Question | Read |
| --- | --- |
| What did we learn, in plain English? | [Reader overview](kolibri-overview.md) |
| What changed with calibration? | [Comparison](calibration-comparison.md) |
| Why did independent coding fail? | [Retrospective](coding-retrospective.md) |
| Did removing the time limit help? | [Elapsed-only attempt](coding-no-wall-deadline.md) |
| Did guided development finish? | [Guided experiment](guided-development.md) |
| Which claims remain unproven? | [Scope and limitations](METHODS.md) |

## General evaluation, serving and tools

| Edition | Scope |
| --- | --- |
| [Four-phase pilot](four-phase-pilot.md) | Initial measured subsets and untested suites |
| [Serving qualification](kolibri-serving.md) | Context capacity and protocol, not long-context accuracy |
| [Baseline general evaluation](general-baseline.md) | Four small tasks, 128 unique questions |
| [Cache-calibration method](cache-calibration-method.md) | Accepted K/V method and rejected export |
| [Calibrated general evaluation](general-calibrated.md) | Matched fixed selection and capped responses |
| [Calibration comparison](calibration-comparison.md) | Mixed changes and causal limits |
| [Browser agent proof](browser-agent-proof.md) | Real local form task via Kolibri and Kilo |

## Independent and assisted coding

| Edition | Scope |
| --- | --- |
| [Three early attempts](coding-three-attempts.md) | Independent seeds; one transport-censored attempt |
| [Tool-budget failure](coding-loop-failure.md) | Incomplete candidate and repeated reads |
| [Repeated-read diagnosis](repeated-read-diagnosis.md) | Confirmed cycle, unproven root cause |
| [Feedback/sampling diagnostic](feedback-sampling.md) | Six synthetic sessions; small-sample limits |
| [Recommended-recipe attempt](coding-recommended-sampling.md) | Natural stop; 17/27 supplemental probes |
| [Elapsed-only policy](elapsed-only-policy.md) | Duration measurement and remaining limits |
| [No-wall-deadline attempt](coding-no-wall-deadline.md) | Natural stop; 24/27 probes, challenge incomplete |
| [Independent-coding retrospective](coding-retrospective.md) | Combined conclusions without a universal model verdict |
| [Separate Codex-assisted repair](assisted-repair.md) | Assisted scope; never Kolibri benchmark success |
| [Guided Kolibri development](guided-development.md) | Partial progress, invalid fixtures and answer truncation |
| [Reader synthesis](kolibri-overview.md) | Human explanation with fictional Alice/Bob |

## Readiness and toolchain history

| Edition | Scope |
| --- | --- |
| [Early readiness](early-readiness.md) | Source selection and missing gates |
| [Browser contract deviation](browser-contract-deviation.md) | Works technically; differs from the old contract |
| [Browser boundary gaps](browser-boundary-gaps.md) | Missing restrictions versus observed exposure |
| [Isolated browser baseline](isolated-browser-baseline.md) | Independently checked bounded tool isolation |
| [Isolated model-to-tool proof](isolated-model-tool-proof.md) | Actual inference/MCP proof and rejected follow-up |

## Preparation and repeatability

| Edition | Scope |
| --- | --- |
| [Inventory scope](inventory-scope.md) | Machine measurements withheld |
| [Capacity planning](capacity-planning.md) | Estimates versus real requests |
| [Model selection](model-selection.md) | Candidates versus qualified models |
| [Repository checks](repository-checks.md) | Navigation and bounded synchronization |
| [Initial bootstrap validation](bootstrap-first-validation.md) | Partial checks; complete install blocked |
| [Existing-installation adoption](existing-installation-adoption.md) | Reuse without reinstalling |
| [Experiment preparation](experiment-preparation.md) | Pins/data prepared; readiness still separate |
| [Resumable controller](resumable-controller.md) | Verified reuse, no uncertain-action replay |
| [Release gates](release-gates.md) | Repeatable infrastructure is not benchmark PASS |

No reports in this collection establish a successful full Phase 4, a completed
SWE-bench score or held-out email accuracy. Raw evidence and candidate/data
payloads remain outside the publication. This collection belongs outside fresh
benchmark worker packages.
