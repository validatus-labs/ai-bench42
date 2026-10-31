# A separate Codex-assisted repair

After the failed Kolibri run, the Owner authorized a direct Codex repair in a
separate development state. It passed 40 tests: 21 original tests plus 19 added
adversarial tests. The same 27 independent synthetic probes passed, as did source
preservation/determinism checks on 12 approved TRAIN examples. Repeat verification
reused existing receipts without executing the checks again or changing them.

The repair wired detection and language dictionaries, preserved Unicode/CRLF
positions, added conservative MIME handling and resource bounds, and used
private exclusive output creation. Independent review identified and closed six
issues in the assisted work, including MIME limits and verifier binding.

This is a tested assisted implementation, not an autonomous Kolibri success.
The original failed trial and cost ledger remain separate. TRAIN preservation
is not target-label accuracy; no annotation mapping or held-out Gold score was
substituted. Complete research coverage and full benchmark qualification were
not established. Candidate source, test payloads and private data are not included
in this report collection.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
