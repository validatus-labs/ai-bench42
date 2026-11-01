# A bounded feedback and sampling diagnostic

Six synthetic Kilo sessions tested whether Kolibri could read an unknown marker,
use it in a write and verify the result. Three paired seeds compared temperature
0.2/top-p 1 with 1.0/0.97. Both explicitly used top-k 128 and High reasoning.
The tasks were semantically matched, but a changing harness timestamp prevented
byte-identical full wire prompts.

All six sessions received real tool results in subsequent requests. Strict task
success was 0/3 with the former recipe and 2/3 with the recommended recipe.
Totals were 28 requests and 11,881 generated tokens. The failed cases initially
inserted an extra space; a deliberately write-once fixture prevented later
correction, even when the model then supplied the correct value.

This supports working feedback in this path, not a universal transport guarantee.
Three pairs, order/cache effects and the artificial write-once rule constrain
interpretation. No historical 22-turn read cycle was reproduced. Reuse verified
all six results without inference. The result motivated a new declared recipe;
it did not prove a root-cause fix or complete the parser.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
