# TASKS — Melusense Rule-First Coding Benchmark

**Status:** benchmark assignment vNext; **not yet executed**.  
**Purpose:** compare how independently operating coding agents implement a safe, multilingual email structure parser—not whether they can train a classifier.  
**Authority:** [AGENTS.md](AGENTS.md), [API contract](docs/contract.md), [Evaluation protocol](docs/evaluation.md), [Budget](config/budget.json).

> **Research question:** When structured, inexpensive logic already solves predictable input, can a coding model build a reliable deterministic first stage and reserve costly LLM inference for genuinely uncertain downstream work?

## Why this still matters in an LLM world

A document system does not need an LLM to recognize an RFC-822 header, a MIME boundary, a known reply separator, or an unambiguous quote marker. Use bounded MIME parsing, TOML dictionaries, safe regex and a deterministic reviewer first; **abstain** on uncertainty rather than delete user text. A future optional LLM can examine exceptional *authorized* cases, with its source spans checked independently. This is an architectural hypothesis to **measure**, not an automatic claim that regex is universally better.

**Real-world motivation:** ARD/ZDF/Deutschlandradio Beitragsservice tender **BW 04/26 / TED 705814-2026** seeks an AI-supported inbound-document service covering paper/scans, email and fax, classifying document kinds/intent and extracting fields with confidence and structured JSON integration. This is **not** a specification that every item must go through a generative model. An email-boundary parser is only one preprocessing component; it does not replace OCR/handwriting recognition, document understanding or professional workflow review. [Tender notice](https://www.hellotender.eu/de/ausschreibungen/einfuhrung-von-ki-in-der-eingangsverarbeitung-705814-2026).

## Execution rules — idempotence and isolation

- **Frozen candidate input:** `benchmark/base-v1`, full SHA `75fcaad909346909115d92b9929b5b91b3ddfbd6`, for existing v1 trials. This updated file on `main` **does not retroactively change that frozen commit**. Before using this revised assignment, the coordinator must review and freeze a **new versioned base** with its full SHA; never retarget the existing tag.
- **Idempotent preparation:** before any write, verify SHA, clean worktree, candidate isolation, matching budgets/tests and stable run configuration. A repeat with identical parameters must verify and reuse the same prepared artifacts; divergent state must **fail closed**, not reset, delete, merge, overwrite or silently create a different trial.
- **Idempotent evaluation:** derive a Run-ID/config fingerprint from model revision, code/tree SHA, dataset/test revision, prompt, seed, versions and limits. Repeating a completed run verifies integrity and shows its recorded result; changes need a **new Run-ID**. Raw outputs/logs stay in isolated `build/`.
- **Isolation:** one model in one sandbox per trial; no access to `validatusinternal/melusense` reference, other trials, private HPI Gold, corpus/BLIND, Git credentials or host secrets. Branches/worktrees alone are **not** security boundaries.
- **Repetitions:** same frozen input, tests, tool access, budgets and seeds `41/42/43` for Kolibri, Mistral and Qwen; retain all attempts, errors, timeouts and token usage. Repeatable procedure does not imply identical stochastic generated code.
- **Safety:** no raw mail or private annotations in Git; no destructive text cleanup, unproven offsets, remote data transfer or attachment execution. All documentation and reports in English.

## Phase checklist

### P1 — Serving and instrumentation (coordinator)

- [ ] Record model revision, quantization, tokenizer, context cap, decoding parameters and source hashes.
- [ ] Use **one** central Prometheus endpoint; record TTFT, prefill/decode throughput, KV/cache, memory, queue and failures. Do not require one endpoint per worktree.
- [ ] Run identical NVIDIA AIPerf workloads at concurrency 1/2/4, three runs; distinguish queued requests from *true* concurrently decoded sequences.
- [ ] Freeze configuration and store machine-readable measurements under each Run-ID.

### P2 — General model capability (coordinator)

- [ ] Pin LightEval, IFEval, MMLU-Pro and BBH dataset/task/backend revisions.
- [ ] Run comparable prompts/sample IDs and publish individual scores; no silent task replacement or calling subsets full benchmarks.

### P3 — General coding and tools (coordinator)

- [ ] Freeze an executable SWE-bench Verified selection, environment and scorer; report architecture/platform incompatibilities rather than substituting test cases.
- [ ] Freeze BFCL tasks, use official tool-call scoring, and distinguish a small smoke test from the full benchmark.
- [ ] Record task completion, patches, tool errors, wall time, tokens and security violations. Independently review maintainability; benchmarks are complementary, not interchangeable.

### P4 — Melusense Rule-First AgentBench (coding candidate)

- [ ] **C01 Inspect:** read [MANIFEST.md](MANIFEST.md), [AGENTS.md](AGENTS.md), [contract](docs/contract.md), starter and visible fixtures. Run the untouched scaffold check and intentionally failing initial acceptance tests; record baseline.
- [ ] **C02 Design:** define typed rule registry, immutable original source, codepoint span/evidence/provenance model, bounded processing and fail-closed abstention. State how CRLF and Unicode coordinates are preserved.
- [ ] **C03 Implement:** independently create `Reply`, `Forward`, `Signature` and `Footer` recognizers using bounded regex + locale dictionaries (start EN/DE/FR/ES); handle multiline, negative contexts, quoted history and overlap.
- [ ] **C04 MIME:** inert RFC-822/MIME ingest; decode text safely, collect attachment *metadata only*, report unsupported HTML/byte-coordinate mappings, never fetch or execute attachments.
- [ ] **C05 Review:** deterministic BoundaryReviewer resolves conflicting evidence; expose `detect_text`/`detect_eml` with the **exact frozen** JSON contract. `authorized_removals=[]` always; no automatic body edits.
- [ ] **C06 Tests:** add original tests for quoted headers, forwarded blocks, signatures, multilingual false positives, empty/malformed mail, CRLF, Unicode, HTML ambiguity, oversized inputs and regex/resource exhaustion. Never change visible/hidden tests.
- [ ] **C07 Freeze:** pass unchanged acceptance suite where implementable, record every failure and source SHA, and produce `build/worker-report.json` with commands, decisions, limitations, resource use and tests. Stop; independent evaluator scores only frozen outputs.

**Deliberately OUT OF SCOPE:** training, scoring or promoting any logistic/FN classifier, Silver mining, synthetic-FN checkpoint, LLM inference inside the parser, and automatic deletion. These are not completion gates.

## Local verification (candidate checkout)

```bash
python3 -B tools/verify_scaffold.py
python3 -B -m unittest discover -s tests -p 'test_scaffold.py'
python3 -B -m unittest discover -s tests -p 'test_acceptance.py'
```

The first two check **starter integrity**, not parser quality. `test_acceptance.py` is expected to **fail on the untouched scaffold** because `melusense/api.py` is unimplemented; a candidate must make it pass without weakening tests. The independent evaluator alone may run protected HPI Gold tests after candidate freeze and rights/cohort review.

### Independent scoring (one report per run)

| Dimension | Required evidence |
|---|---|
| Functional correctness | Exact source-anchored reply/forward/signature/footer predictions against adjudicated HPI Gold; TP/FP/FN, precision/recall/F1 and exact-case accuracy; count UNKNOWN separately |
| Safety | Unauthorized removal count **0**; current-body preservation; MIME/HTML/offset abstention; regex input/size/time limits |
| Code quality | Legible modular design, contract adherence, tests, diagnostics, dependency/supply-chain hygiene, bounded complexity and reviewer rationale |
| Efficiency | Wall time, memory, throughput, generated tokens/tool calls, coding completion time and failure-recovery rate |
| Reproducibility | Frozen base, model, source/tree SHA, evaluator version, seeds, immutable metrics, repeatability/failure logs |

**Interpretation:** This is a current, useful **domain-specific coding and software-engineering challenge**, not a universal coding-intelligence ranking. Cross-check outcomes with SWE-bench and BFCL; compare both parser quality and the *coding agent's implementation quality*. If Gold is missing or invalid, report **NOT_EVALUATED**, never infer 100% recall.

## Key research finding — why there is no classifier checkpoint

- Historical HPI development (previously examined) contained **1,009 valid cases** and an approximately **90.6% rules F1** under its old development protocol; not a new blind result.
- The earlier optional FN classifier added **0 true positives and 4 false positives** on the known 145-case HPI evaluation. There is no demonstrated benefit sufficient to make it mandatory.
- In the separately investigated Thunderbird 4-GiB prefix, **29/29** independently *source-corroborated* historical headers (23 reference-connected groups) were already covered by rules, yielding **0 demonstrated additional FN Silver positives**. This is not proof of perfect recall: plausible/UNKNOWN content and missing parents remain unresolved.
- Classifier research also encountered labeling shortcuts (quotation and preceding blank-line cues), uncertain MIME provenance and insufficient FR/ES independent positive threads. Retain these lessons as historical context, **not** benchmark gates or scoring data.

**If revisited later (separate opt-in research):** seek independently annotated historical reply/forward header starts from **HPI Email Structure / Quagga** (ASF/Enron TRAIN/TEST/EVAL with original splits and licensing review). Compare rules-only vs optional LLM-assisted recovery on the *same held-out human Gold*, verified source anchors, FP cost, latency and tokens. Do not train on EVAL/BLIND or recycle rule-derived Silver as Gold. No general bulk-mail download is required by this benchmark.

## Parsers worth comparing (coordinator context, not agent source code)

| Implementation | Approach | Important limitation / lesson |
|---|---|---|
| [GitHub Email Reply Parser](https://github.com/github/email_reply_parser) | Small fragment/quote-rule parser | Known language and multiline-header limitations; simple baseline |
| [Crisp Email Reply Parser](https://github.com/crisp-oss/email-reply-parser) | Actively maintained multilingual regex for plain-text replies; optional RE2 | Demonstrates 2026 operational relevance; not a MIME/offset-verification system |
| [Crisp Email Forward Parser](https://github.com/crisp-oss/email-forward-parser) | Locale/client-specific forwarded-mail structures | Complementary forward metadata; no automatic deletion authority in Melusense |
| [Mailgun Talon](https://github.com/mailgun/talon) | Heuristics for quote extraction and optional trained signature model | Hybrid comparator; learned signature stage is outside our assignment |
| [HPI Quagga](https://github.com/HPI-Information-Systems/Quagga) | ECIR-2018 recurrent-neural zoning; repository includes older Jangada, Zebra, FeatureRNN competitors | Valuable historical scientific reference, not a modern coding-agent benchmark |

**Only corpus reference:** [HPI Email Structure](https://hpi.de/en/database-group/projects/data-integration-projects/web-science/mimir-corpus-exploration-and-knowledge-management/email-structure/). Dataset annotations/code/mail-text rights differ; do not copy or publish original mail without permission. Do not let coding candidates fetch these comparator implementations: equal tasks must be solved independently from the frozen starter.

**Next coordinator action:** review this vNext task and the unchanged contracts, freeze a new candidate base (e.g. `benchmark/base-v2`), verify security isolation, then run three independent model implementations. Never rewrite `benchmark/base-v1`.
