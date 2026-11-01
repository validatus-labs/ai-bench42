# Guided development: progress, invalid tests and truncation

The separately authorized guided experiment gave Kolibri staged requirements
and concrete review feedback; Kolibri authored the parser code. Planning and
basic text integration advanced after corrections. Automatic language handling
remained English-only, while explicit language cases were narrower successes.
The MIME milestone failed review twice and its third attempt ended truncated.
Later safety and final-delivery milestones were not reached.

Coding used 90 requests, 103,929 generated tokens and 168 tools. Readiness added
two requests, 548 tokens and four tools. Observed coding elapsed time was
4,124.28 seconds, including review waits; summed request durations were
3,387.32 seconds, not pure GPU compute time.

The final test run discovered 56 tests with three failures. Review found two
faulty fixture assumptions: a whole-message attachment did not imply a separate
body, and another fixture lacked the delimiter needed for its claimed structure.
Missing metadata for a well-formed attached email was a genuine defect. An unsafe
raw-message fallback and incomplete later requirements remained.

The final successful HTTP response used 164,177 input tokens and an allowance
of only 1,607 output tokens, despite a 32,768 configured ceiling. It ended at
length; 1,606 tokens were reasoning. Output reservations had progressively shrunk
while compaction/pruning were disabled. The exact internal clamp formula was
not established. This explains final truncation, not all earlier code failures.

The trial was independently reviewed and preserved as incomplete. Guidance and
tool versions differed from older trials, so their effects are not causally
isolated. No Gold score or complete parser PASS is claimed.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
