# How we measure

AI-Bench42 separates serving, answer quality, tool use and complete software
delivery. A successful execution is not automatically a good answer or an
accepted project. The model, assignment, tools, limits and evaluation scope must
be bound to each cohort; old and new measurements are not interchangeable.

## Latest cohort: 6 November 2026

Three independent seeds used the same 27-file frozen assignment, public API,
supplied tests and numeric budgets. They used separate native Kilo workers,
existing local Kolibri-1 FP8/V5 and the same qualified Brave/Playwright MCP assets.
Each worker needed three genuine model-issued MCP calls before coding. Reference
code, other candidates and held-out Gold were excluded. Approved TRAIN remained
private and was identical across seeds.

There was no total coding wall deadline. Request, output, token, tool and other
resource bounds still applied. Generated tokens include reasoning. Accounting
comes from the coordinator, not the candidate's self-report.

| Seed | Recorded interval | Coding requests | Generated tokens | Coding tool calls |
| --- | ---: | ---: | ---: | ---: |
| 1 | 899.694 s | 39 | 28,317 | 100 |
| 2 | 1,023.552 s | 2 | 32,280 | 6 |
| 3 | 706.826 s | 31 | 21,466 | 113 |

Counts exclude each trial's three additional admission/model-MCP requests.
Seed 1's interval is the recorded lifecycle interval; seeds 2/3 record coding
intervals. These are observed elapsed intervals, not GPU time or a timing ranking.
Seed 2's last response reached 32,000 tokens: 31,999 reasoning and one output.

Candidates were frozen before independent requirements review. Supplied tests,
11 supplemental probes, TRAIN execution and held-out accuracy are distinct.
Two candidates passed 21/21 supplied tests, with 4/11 and 7/11 supplemental probes;
neither completed the task. The third kept the starter unimplemented. Its
infrastructure passes and vacuous negative CLI pass are not parser performance.
No hidden-Gold precision, recall or F1 is available.

The coordinator finished all selected phases and retained rejection as
`CANDIDATE_REJECTED`, with held-out scoring `NOT_EVALUATED`. Overall `INCOMPLETE`
reflects failed model delivery, even when `progress.action=COMPLETE` means the
measurement workflow has finished. Repeating the completed workflow preserved
77 experiment files and 69 original evidence files with zero new model requests.

## What phases 1–3 establish

The current combined workflow reused bounded integration results: AIPerf 0.13.0
with 36 requests over nine trials at concurrency 1/2/4; lm-eval 0.4.13 with
42 leaf tasks, one sample each and 128 output tokens including reasoning; and
three BFCL simple-Python AST cases. These verify selected integrations. They
are not full AIPerf/IFEval/MMLU-Pro/BBH/BFCL leaderboard measurements. SWE-bench
was explicitly not requested. A 262,144 context setting does not prove retrieval
quality across that context.

Earlier calibration experiments instead used 32 fixed English examples for each
of IFEval, MMLU-Pro and two BBH tasks, repeated three times, with a 4,096-token
allowance including reasoning. All capped responses remained in the denominator.
These earlier scores are preserved in the [historical evidence](evidence/README.md)
and must not be relabelled as results of the newer integration smoke.

## Evidence and reproducibility

The [structured cohort summary](evidence/kolibri-20261106.json) binds model/source
identity, candidate trees, reviewed receipts and measured counts. The public
summary is derived from privately retained execution records. Hashes identify
those records; they do not let a reader independently inspect withheld raw
sessions, candidate archives, private TRAIN or Gold. Complete replay of the
historical runs therefore requires separately authorized inputs and retained
runtime assets. No raw correspondence or hidden annotations are published here.

The reviewed coordinator source passed 374 local/native package tests. The
release has its own source-bound check; those software tests are not a model
score or proof of installation on a blank machine. The accepted historical
audit reviewed captured artifacts; it did not independently replay the remote
reuse/cleanup/model-counter observations. The deployment check concerns an
existing installation, not verified greenfield commissioning.

Earlier independent, guided and Codex-repaired candidates remain separate.
Guidance changes conditions; direct repair is not success attributed to Kolibri.
The private Melusense reference is not substitute Gold, and CI does not establish
blind email accuracy. A fresh worker gets an exported, reviewed Git-free
assignment, not this coordinator repository with its reports and evaluator tools.

For a matched comparison, retain identical task/data/tools and declared budgets,
fix acceptance criteria in advance and report failures. Add other tasks and a
human baseline before claiming broad reliability or productivity benefits.

[Results](README.md) · [Kolibri assessment](kolibri.md) · [Evidence](evidence/README.md)
