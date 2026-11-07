# Three early independent coding attempts

Three fresh Kolibri trials began from the same empty assignment with seeds 1, 2
and 3. Each had an isolated visible Kilo worker, real browser canary and independent
readiness review. They retained temperature 0.2, top-p 1, a 262,144-token context,
100 requests, 200 tools and a one-hour whole-trial ceiling.

| Attempt | Coding requests / known generated tokens / tools | Common probes |
| --- | --- | --- |
| Seed 1 | 36 / 31,593 / 103 | 21/27 |
| Seed 2 | 29 / 37,551 / 92 | 19/27 |
| Seed 3 | 32 charged / 24,818 known / 124 | 19/27 |

All five original verification commands passed in each trial. Independent review
found incomplete detection/reviewer integration, MIME/attachment handling and
private/race-safe output behavior. Passing the small supplied suite was insufficient.
Seed 3 also had invalid delivery JSON and an unresolved transport cutoff; reserved
tokens were not counted as observed consumption. It is not a clean completed
quality trial.

The controller's earlier response ceiling, report-key assumptions and archive
identity handling were corrected for future runs, without rewriting old outcomes.
The restricted research catalog did not cover every requested research source,
which also limited compliance. No held-out accuracy or full challenge PASS follows.

[Report index](README.md) · [Methods and publication scope](METHODS.md)
