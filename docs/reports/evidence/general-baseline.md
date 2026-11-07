# Kolibri before cache calibration

Status: completed fixed-subset assessment; full-suite and held-out coding
accuracy remain unmeasured. Kolibri-1 used FP8 weights and FP8 cache, one serving
sequence and a 262,144-token configured context. The historical cache used unit
scales. Temperature was zero, the output limit was 4,096 tokens including reasoning,
and response caching was disabled.

Each of four English tasks supplied 32 fixed distinct examples, repeated three
times with selection/seed 42. Means across the repetitions were:

| Task | Result |
| --- | ---: |
| IFEval prompt-level strict / loose | 91.67% / 91.67% |
| MMLU-Pro generated-answer accuracy | 45.83% |
| BBH date understanding | 84.38% |
| BBH three-object logic | 100.00% |

Of 384 responses, 53 reached the output cap: eight IFEval, 36 MMLU-Pro and nine
date questions. They remain in the denominators. Repetition measures variability
on the same questions; it does not triple dataset diversity. These generated
multiple-choice results are not full-suite or log-likelihood leaderboard scores.

The short serving pilot had 54 successful requests. More clients queued against
one sequence, so it did not demonstrate parallel decoding. Basic tools passed
nine calls on three distinct cases; SWE-bench was not evaluated. The limited
selection and output cap constrain generalization. No email precision, recall or F1
or complete-project success follows from this assessment.

## Individual repetitions

| Task | Repetition 1 | Repetition 2 | Repetition 3 |
| --- | ---: | ---: | ---: |
| IFEval strict / loose | 81.25% | 96.88% | 96.88% |
| MMLU-Pro | 50.00% | 43.75% | 43.75% |
| BBH date | 84.38% | 84.38% | 84.38% |
| BBH three-object logic | 100.00% | 100.00% | 100.00% |

The task inputs and seed were held fixed across these repetitions; observed
variation does not establish broad sampling uncertainty.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
