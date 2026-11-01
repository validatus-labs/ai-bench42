# Kolibri results

[Read the two-page quality assessment](kolibri-overview.md).

Kolibri showed useful coding and tool-use ability, but did not deliver the complete
parser in the reviewed trials. The report explains how this fits published
coding benchmarks and what to expect from Mistral Small 4 and GLM-5.3-Flash.
Measured project results, external developer-reported scores and expectations
are distinguished throughout.

For individual scores, read the [baseline](general-baseline.md),
[calibrated evaluation](general-calibrated.md) and
[calibration comparison](calibration-comparison.md). For project development,
read the [independent result](coding-no-wall-deadline.md) and
[guided result](guided-development.md).

[Evaluation methods](METHODS.md) define the scope and denominators.
The [collection manifest](collection.json) inventories the supporting records.

<details>
<summary>Supporting measurements and historical preparation records</summary>

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

</details>
