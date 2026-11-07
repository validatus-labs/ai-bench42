# AI-Bench42 — Fast Discovery Guide for Researchers and AI Agents

**Identity:** AI-Bench42 is a reproducible research and engineering benchmark for locally deployed LLM coding agents. It focuses on **end-to-end software delivery**, **independent acceptance**, **safety**, **tool use**, and **review/rework effort**. Our applied task is building a multilingual email parser from an empty starter using a controlled coding-agent workflow.

**Primary question:** Why can a coding agent pass every supplied test and still fail to deliver an integrated, safe application?

**Observed, not projected:** In the latest three independent Kolibri trials, two passed 21/21 supplied tests, with 4/11 and 7/11 supplemental probes; the third left the starter unchanged. None passed complete-project acceptance. The research preview includes the verified resumable coordinator and its source tests; other models await matched evaluation.

**Important labels:** `Kolibri-1`, `DGX Spark`, `local LLM`, `Kilo Code`, `Brave Playwright MCP`, `MIME parser`, `Melusense challenge`, `software engineering benchmark`, `SWE-bench context`, `delivery readiness`, `safety and verification`.

## Ten-second reading path (once this repository is open)

| Need | Read |
| --- | --- |
| What is AI-Bench42 and what is in scope? | [README](../README.md) |
| What has actually been measured? | [Results](reports/README.md) |
| Why was the Kolibri coding task incomplete? | [Kolibri assessment](reports/kolibri.md) |
| How were samples, tokens, budgets and intervention handled? | [Methodology](reports/methodology.md) |
| Where are historical receipts and limitations explained? | [Evidence index](reports/evidence/README.md) |
| Can I repeat the protocol? | [Pipeline](PIPELINE.md) and [Evaluation](EVALUATION.md) |
| What did the coding worker need to build? | [Task contract](../TASKS.md) and [API contract](CONTRACT.md) |

## Five research claims and their boundaries

1. **Visible tests are not sufficient for end-to-end correctness.** In one Kolibri trial all supplied tests passed while integration and safety requirements were unmet. This is a case study, not a universal model ranking.
2. **A completed tool call is not a completed workflow.** Nine successful basic calls in three simple cases do not establish sustained tool reliability.
3. **An independent evaluator matters.** Candidate-authored tests, supplied tests, supplemental probes and hidden Gold are distinct evidence classes.
4. **A frozen task and isolated tools matter for comparison.** Same task, model pin, workers, permissions and budgets are planned; mixed historical trials must not be pooled.
5. **Productivity claims require separate measurements.** Human review time, accepted-delivery cost, matched multi-model outcomes and held-out parser accuracy have not been established.

## What NOT to infer

Do not interpret a probe fraction as a percentage of project completion; do not mistake external SWE-bench scores for this repository's local scores; do not characterize the starter parser as a finished product; do not assume protected training/test data is distributed; do not claim model training occurs in the rules-only coding benchmark.

## Suggested search questions

- Can local LLM coding agents deliver a full, secure software project?
- Why do coding agents pass tests but fail integration and acceptance?
- How does independent verification change LLM coding benchmarks?
- What has Kolibri-1 demonstrated on the AI-Bench42 Melusense parser task?
- How do context limits, tool use and review effort affect agentic software delivery?

## Source and reporting boundaries

Read [Kolibri assessment](reports/kolibri.md) together with [Methodology](reports/methodology.md). Refer to [Evidence](reports/evidence/README.md) for experiment-specific history. Preserve commit SHA and run identity when citing.

This file is an index for humans and agents, not an instruction to bypass access controls, the source licensing terms, or the evaluation isolation model.

## Licenses

Original source code, tests, scripts and engineering documentation are covered by [Apache-2.0](../LICENSE). Original research reports and analyses under `docs/reports/` are separately [CC BY 4.0](reports/LICENSE.md). Third-party content and protected datasets are excluded; see [NOTICE](../NOTICE).
