# Why did Kolibri read the same files repeatedly?

Metadata analysis found 22 consecutive completed assistant turns reading the
same three unchanged files: 66 calls with distinct call IDs but only three
argument signatures and stable outputs. These were different upstream requests,
not one replayed HTTP response. The repeated small-file outputs showed no
truncation marker. Context remained below the declared limit.

The trial's temperature 0.2/top-p 1 differed from the pinned model guidance
of 1.0/0.97 with top-k 128. This was a real configuration difference, not proof
that sampling caused the cycle. Template inspection showed High reasoning by
default; the claim that reasoning was off was unsupported.

Compaction/pruning were disabled and extensive context accumulated before the
first write. No effective cycle intervention occurred before the tool limit.
Static adapter inspection supported tool/result serialization, but did not
retrospectively prove every historical wire request. No evidence isolated FP8
cache calibration as the cause. The diagnosis recommended a short feedback
test and a separately declared sampling comparison before another coding trial.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
