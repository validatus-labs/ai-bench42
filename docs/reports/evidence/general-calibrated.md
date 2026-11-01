# Kolibri after accepted cache calibration

The accepted cache-calibrated release completed three repetitions of the same
128-example English selection, nine short performance runs and nine basic tool
calls. Weights remained FP8; only compatible static K/V scales changed. Context
was 262,144 tokens, with one serving sequence. The general evaluation retained
temperature zero and a 4,096-token answer allowance including reasoning.

| Task | Mean result |
| --- | ---: |
| IFEval prompt-level strict / loose | 88.54% / 88.54% |
| MMLU-Pro generated-answer accuracy | 50.00% |
| BBH date understanding | 84.38% |
| BBH three-object logic | 100.00% |

Fifty-one of 384 responses reached the cap: 11 IFEval, 30 MMLU-Pro and ten date
questions. All remain scored. Repeated questions do not create independent new
samples. The basic BFCL pilot passed nine calls on three unique simple cases;
SWE-bench remained untested.

A real 262,112-input-plus-32-output request passed the capacity check. This does
not demonstrate accuracy across a 256K document. The general evaluation did not
test a GUI High selector. The recorded request protocol, not a UI label, defines
the evaluated setup. No held-out email score, completed coding challenge or
cross-model ranking is claimed.

## Individual repetitions

| Task | Repetition 1 | Repetition 2 | Repetition 3 |
| --- | ---: | ---: | ---: |
| IFEval strict / loose | 78.12% | 93.75% | 93.75% |
| MMLU-Pro | 50.00% | 50.00% | 50.00% |
| BBH date | 84.38% | 84.38% | 84.38% |
| BBH three-object logic | 100.00% | 100.00% | 100.00% |

The task inputs and seed were held fixed across these repetitions; observed
variation does not establish broad sampling uncertainty.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
