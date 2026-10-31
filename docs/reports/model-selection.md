# Model selection and qualification limits

Initial selection considered Mistral Small 4, Devstral Small 2 and several Kolibri
quantizations. Integer Q8 checkpoints and floating-point FP8 checkpoints are
different formats; a shared eight-bit label does not establish equivalent storage,
runtime support or accuracy.

Kolibri's official FP8 checkpoint was subsequently qualified at a configured
262,144-token context. Other candidates remained proposals, with runtime/kernel,
cache and quality gates still open. Third-party speed figures were external
references, not our controlled comparison, and are omitted here.

This is a historical selection record. It does not rank Mistral, Qwen or GLM,
qualify their endpoints, or demonstrate a preferred quantization by accuracy.
Machine-specific fit calculations and hardware identifiers are withheld.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
