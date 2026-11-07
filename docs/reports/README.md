# Results — Can Kolibri deliver a complete project?

**Kolibri can write useful code and operate tools. In the latest three independent
trials, none delivered the complete parser.** Two implementations passed all
21 supplied tests. Independent review still found important gaps.

Our first task is Melusense: build a multilingual email parser from an empty
starter, preserve the original text and handle MIME, attachments and uncertain
boundaries safely. The question is practical: can a local coding agent connect
all the required pieces and verify its own delivery?

| Latest cohort: 6 November 2026 | Result |
| --- | --- |
| Complete, independently accepted deliveries | **0/3** |
| Trial 1 | 21/21 supplied tests; 4/11 additional probes; incomplete |
| Trial 2 | Starter unchanged; final response reached its token ceiling |
| Trial 3 | 21/21 supplied tests; 7/11 additional probes; incomplete |
| Real browser-tool admission proof | Three model-issued MCP calls per trial |
| Repeatability | Completed results reused with zero additional model requests |

Passing a probe is not a percentage of project completion. These three attempts
share one task and do not estimate a general model success rate.

- **[Kolibri assessment](kolibri.md)** — what it achieved, where it failed and
  what that means for practical use; about two pages.
- **[Methodology](methodology.md)** — fixed inputs, accounting, review and limits.

The [structured cohort summary](evidence/kolibri-20261106.json) records counts
and artifact hashes. The [evidence index](evidence/README.md) separates this
cohort from earlier diagnostics, calibration and guided development. Older
results are retained under their original scope, not pooled into a ranking.

[Project and setup](../../README.md) · [Content inventory](collection.json)
