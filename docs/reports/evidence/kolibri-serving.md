# Kolibri serving and context-capacity qualification

The historical baseline used Kolibri-1 FP8 weights, FP8 key/value cache,
vLLM 0.29.0 and the Aleph Alpha inference plugin 1.0.0. Serving was configured
for one sequence and a 262,144-token context.

A real synthetic request accepted 262,112 input token IDs and generated 32 tokens:
262,144 total. This established capacity, not retrieval accuracy or meaningful
reasoning over an entire long document. Small semantic and protocol fixtures
also verified separated reasoning, function-call arguments and tool-result feedback.

Repeated deployment, start and status operations preserved the existing release and
state without restarting it. An earlier failed first installation rolled back
after missing compiler headers were detected. Later preflight added a real
compiler/JIT gate. A narrow vendor dependency warning was retained explicitly;
it was not hidden by modifying the dependency.

The baseline used unit cache scales and emitted an accuracy warning. The separate
calibration reports describe the later release. Hardware, allocation totals,
service addresses, binary paths and private release identifiers are withheld.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
