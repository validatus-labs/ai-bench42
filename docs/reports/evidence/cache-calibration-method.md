# Cache calibration: method and rejected export

Calibration changed static key/value cache scales, not model weights. Kolibri-1
FP8, vLLM 0.29.0, plugin 1.0.0, context 262,144 and one sequence were retained.
Thirty-two authored synthetic inputs covered English, German, French and technical
code-labelled records. No evaluation answers, correspondence or private reference
code entered calibration.

All 50 attention layers were observed with 2,048 input and 64 forced decode tokens
per input. The scale rule was absmax × 1.1 / 448, rounded upward to values exactly
representable by the loader's parameter type. The accepted export calibrated K/V;
queries remained BF16 with unit Q/probability scales. This is a project static
min/max method, not a complete vendor-endorsed Kolibri recipe.

An earlier export incorrectly supplied FP8 Q scales for unquantized queries. Its
first repetition scored 3.125% IFEval and zero on all three multiple-choice tasks,
with 77 of 128 outputs capped. A second repetition was stopped after five requests.
Those failures remain disclosed and excluded from the accepted cohort.

The corrected export preserved the rounded K/V values and fixed export scope;
it did not fit new K/V numbers to benchmark answers. This was post-observation
engineering, not a blinded experiment. Scale loading, finite semantics/protocol
and full-capacity acceptance passed. Short synthetic calibration does not qualify
production distributions or long-context reasoning. Later quality changes were mixed.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
