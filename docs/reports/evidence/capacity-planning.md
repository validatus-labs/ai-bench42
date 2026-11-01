# Capacity planning: estimates versus measurements

Capacity planning kept model weights, attention-cache representation, serving
overhead and safety reserve separate. Checkpoint file sizes were planning inputs,
not measurements of resident memory. Decimal GB and binary GiB were distinguished.

Compressed attention-cache estimates apply only when the runtime actually keeps
the compressed representation. Expanded attention invalidates that assumption;
block rounding, scale storage, graphs and allocation pools add overhead. A cache
planner's capacity estimate is not a concurrency measurement.

Machine-specific budgets and candidate allocation tables are withheld. The
technical conclusion survives: memory fit is necessary but insufficient. A real
request must verify the declared context, and separate tasks must test useful
reasoning at that length. Swapping is not evidence of a fully resident deployment.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
