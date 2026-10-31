# The independent attempt without a wall deadline

The fresh attempt ended naturally after 28 minutes 32.01 seconds. It used
47 coding requests, 48,120 generated tokens and 137 tools; including its own
readiness proof, totals were 49 requests, 49,816 tokens and 141 tools.
All requests completed successfully. The largest prompt plus completion was
148,270 tokens against the declared 262,144 context.

All 21 original tests and ten worker tests passed. The unchanged supplemental
probes passed 24 of 27. The three failures concerned malformed-MIME warnings,
initial private output permissions and concurrent destination overwrite.
These probes are not a percentage of project completion or held-out accuracy.

Source review found a larger architectural gap: the main API remained largely
quote-line detection, with required processors, dictionaries and reviewer not
fully integrated. Resource bounds and research/reporting were incomplete. The
complete challenge failed despite the model finishing voluntarily with remaining
time-independent budgets. No exact repeated-read cycle was detected.

The earlier diagnostic passed 17/27 of the same probes. Both ended naturally
before the old whole-trial ceiling, so the improvement cannot be attributed to
removing that ceiling. Separate stopped-state and unchanged-result reuse checks
passed without additional inference. Gold/reference scoring was not evaluated.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
