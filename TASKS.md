# TASKS — Melusense Rule-First Benchmark / Clean Start

This file is the immutable *assignment*, not a progress log. Its checkboxes are task identifiers; agents must not edit or tick them.
Results belong only in isolated `build/` artifacts and independent evaluator records.
The current repository snapshot is in [STATE.md](STATE.md).

**Goal:** Compare diverse models (e.g. Kolibri, Mistral, GLM, Qwen) as coding agents on one bounded, deterministic email-structure parser. No classifier inference/training, Silver-label mining, FN-Recovery model, online LLM parsing, or destructive cleanup is required. The reserved `ml_mode=off|recover` interface is an extensibility check, not a classifier implementation or ML score.

## 0. Expected parser architecture (normative overview)

```text
     .eml (RFC-822 bytes)             Unicode text
              |                            |
     [01 MIME/charset ingest]              |
     - inert attachments                   |
     - conservative decoding               |
     - provenance / offset status           |
              +--------------+-------------+
                             |
                [02 Original-source view]
                  immutable Unicode text
                  exact codepoint positions
                  CRLF preserved verbatim
                             |
                [03 Canonical Recognition]
                  typed lines / header roles
                  source-backed evidence
                             |
             [04 TOML dictionaries + safe regex]
                  EN / DE / FR / ES initially
                  bounded matching / budgets
                             |
               +-------------+-------------+
               |             |             |
          Reply/Quote    Forward      Signature/Footer
               |             |             |
               +-------------+-------------+
                             |
                  [05 Candidate registry]
                  category, [start, end),
                  rule ID, evidence, status
                             |
                [06 Deterministic reviewer]
                  context corroboration
                  negative/code contexts
                  conflict & overlap review
                  stable ordering / dedupe
                  uncertain => ABSTAIN
                             |
                  [07 Final safety gate]
                      KEEP_ALL
                 authorized_removals = []
                             |
               [08 JSON-compatible result]
                 original/decoded provenance
                 exact text coordinates
                 attachment metadata only
                 candidates + warnings
```

A header candidate is **not** a deletion instruction. `detect_text` bypasses MIME ingest; `detect_eml` must not claim exact raw byte offsets unless proven. The frozen [API contract](docs/CONTRACT.md) controls actual output field names and coordinates. Preserve all legitimate current-body text.

## 1. Reproducibility contract

- One candidate = **one isolated runtime and clean Git-free export** from the *same exact source SHA*, recorded in the coordinator's offline package manifest. Do not use a branch name as an implicit source identity. Never reuse a previous solution, agent cache, tool history or a private reference implementation.
- Coordinator verifies repo SHA, task/fixture/config hashes, tool versions, budgets, available context, isolation and tool/model endpoint before any trial. An unchanged rerun verifies/reuses its existing Run-ID; changed input creates a new Run-ID. **Never reset, overwrite or silently repair** divergent states.
- Implementation source layout is defined by [AGENTS.md](AGENTS.md); worker layout and research policy are in the [runbook](docs/RUNBOOK.md). Required module paths are fixed for comparable outputs, while internals can differ. Source permissions prohibit access to the private reference implementation, protected corpus and human Gold, other agent runs, hidden tests and Git credentials. A Git branch/worktree is **not** a security boundary.
- Use pinned common [budgets](config/budget.json), [agent rules](AGENTS.md), [API contract](docs/CONTRACT.md) and [evaluation rules](docs/EVALUATION.md). Document unsupported context/platform settings; no silent fallback.
- Run three isolated attempts per model with seeds **1, 2 and 3**. Keep every failure, timeout, generated token count, tool call, command, model revision and tree SHA.
- **No progress checkbox is ever ticked in this file.** Store per-run progress and findings under `build/`, which is not committed to the frozen candidate source.

## 2. Coordinator phases (not candidate implementation tasks)

### P1 — Serving and instrumentation
- [ ] Verify pinned serving configuration: weights/quantization, tokenizer, context length, active sequences, memory and logs.
- [ ] Verify **one central** Prometheus endpoint (not one per worktree): TTFT, prefill/decode, cache/KV memory, throughput, request queue and failures.
- [ ] Run identical NVIDIA AIPerf probes with 1/2/4 clients and three repetitions; **queueing is not concurrent decoding**.
- [ ] Record immutable configurations, hashes, timestamps, raw metrics and Run-IDs.

### P2 — General model evaluation
- [ ] Pin evaluation backend and IFEval / MMLU-Pro / BBH revisions, prompts, samples and scoring.
- [ ] Run matched settings; record truncation, unsupported tasks and failures.
- [ ] Report each score separately; never call a smoke subset a full benchmark.

### P3 — General coding and tool calls
- [ ] Pin SWE-bench Verified selection, platform/container requirements and scorer.
- [ ] Pin BFCL selection and official AST/tool-call checks.
- [ ] Report completion, tests, time, tokens, tool failures and independent code review, without conflating these scores with parser quality.

### How to interpret the four phases

P1 uses [AIPerf](https://docs.nvidia.com/aiperf/getting-started/profiling-with-ai-perf), [vLLM](https://docs.vllm.ai/en/latest/) statistics and [Prometheus](https://prometheus.io/docs/introduction/overview/) for latency, throughput, memory and queue behavior. TTFT means time to first token; prefill processes the prompt and decode generates subsequent tokens. Record KV-cache dtype and memory per run: FP8 and BF16 are not equivalent. P2 may use [LightEval](https://huggingface.co/docs/lighteval/index) to run pinned [IFEval](https://github.com/google-research/google-research/tree/master/instruction_following_eval), [MMLU-Pro](https://github.com/TIGER-AI-Lab/MMLU-Pro) and [BIG-Bench Hard](https://github.com/suzgunmirac/BIG-Bench-Hard). P3 uses [BFCL](https://gorilla.cs.berkeley.edu/leaderboard) for tool calls and [SWE-bench Verified](https://github.com/swe-bench/SWE-bench) for issue-to-patch work. Keep smoke subsets separate from full runs. P4 evaluates the frozen Melusense candidate independently; code quality and end-to-end correctness are separate results.

Pin exact hosted model ID, checkpoint, tokenizer, weights/quantization, context, KV-cache settings, loaded sequence count and tool-call format. An unsupported model/backend combination is `BLOCKED/UNSUPPORTED`; do not silently shrink context or substitute a model. These measurements are task-specific, not a universal model score. A weak Silver label or parser prediction is not human Gold. Preserve failed attempts, mistakes, safety violations, time, tokens and memory alongside successes.

## 3. P4 — Candidate implementation from a deliberately empty parser

**One identical offline handoff for all models:** [English copy/paste agent prompt](docs/OFFLINE_AGENT_PROMPT.md), [required candidate layout](AGENTS.md#required-candidate-source-layout), [API contract](docs/CONTRACT.md) and [runbook](docs/RUNBOOK.md). Model agents receive no Git credentials or clone access; controlled public source-page research is permitted. Coordinator-supplied frozen source, documentation, and budgets must match exact hashes before any candidate begins.

- [ ] **C00 Brave-MCP + TRAIN preflight (coordinator, read-only):** verify the immutable Git-free package hashes, pinned Brave/Playwright/MCP binary/config/tool-schema fingerprints, a real browser MCP tool call from each isolated model agent, headless/sandbox, service-worker blocking and identical public email-format research scope and budgets. Independently prove DNS/redirect/IPv4/IPv6 egress controls that exclude private/internal destinations, plus worker filesystem/private-reference/Gold/credential denial; never treat a browser flag as a sandbox. Require the rights-approved 12-pair HPI TRAIN bundle for every model and seed, validate its identical SHA-256 and worker disclosure permission, and record the hash in each run manifest. Missing approval, data or a matching bundle blocks C00; synthetic fixtures cannot replace TRAIN. Any missing qualification remains BLOCKED. No install, restart or silent Chromium fallback. See the [runbook](docs/RUNBOOK.md#c00-qualify-one-worker-before-c01) and [HPI data](docs/HPI_TRAIN.md).

- [ ] **C01 Baseline:** Read `MANIFEST.md`, `AGENTS.md`, this task, `docs/CONTRACT.md`, fixtures and tests. Run and record unchanged scaffold checks **and expected failing acceptance tests**.
- [ ] **C02 Design:** Define input budgets, canonical line/span model, original-source provenance, rule registry and conservative abstention. Specify exact Unicode codepoint and CRLF behavior.
- [ ] **C03 Recognize:** Research public Gmail, Outlook, Thunderbird, Apple Mail/iPhone and named Android-client reply/forward/signature/footer formats, localized markers and public parser/regex examples using the approved browser. Record URLs, access dates and license/provenance for adapted terms/patterns. Implement bounded regex + TOML dictionaries (EN/DE/FR/ES first; expand only with evidence and tests), including quoted chains, multiline headers, separators, negative contexts and conflicts. Integrate the candidate's own parser; do not import a finished implementation.
- [ ] **C04 MIME:** Implement inert MIME/charset ingest; no attachment fetching/execution/payload export. Return attachment *metadata* and warnings when charset/HTML/source mapping is not provable.
- [ ] **C05 Review + reserved ML switch:** Add deterministic BoundaryReviewer and stable evidence-based arbitration. Implement `detect_text(text, locale="auto", *, ml_mode="off")` and `detect_eml(raw, locale="auto", *, ml_mode="off")` with the same original output contract, and a minimal local `python -m melusense ... --ml-mode off|recover` CLI, as specified by `docs/CONTRACT.md`. Default and `off` execute **only rules** and produce identical results. `recover` raises explicit deterministic not-implemented/unsupported error without loading/training/calling any model or silently falling back. Unknown values fail closed. A reserved `processors/recovery_hook.py` is only a stub/interface, not a classifier. `authorized_removals=[]` always.
- [ ] **C06 Verify:** Add targeted positive and negative tests for researched client and language variants, no-history mail, nested forwards, Unicode, CRLF, misleading From/Date inside current body or code/patches, malformed MIME, hostile regex input and budgets. Record source-to-rule-to-test traceability and unsupported variants. Verify default vs explicit `ml_mode="off"` parity, `recover` explicit unsupported behavior, bad-mode rejection, and the minimal CLI without network/ML calls. Preserve all provided tests unchanged.
- [ ] **C07 Freeze candidate:** Run visible tests and check the parser on all 12 approved HPI TRAIN examples. Produce `build/worker-report.json` with Run-ID, hashes (including TRAIN bundle SHA-256), decisions, commands, `ml_mode` behavior, test outcomes, per-example TRAIN results and failures, annotation mapping where used, tokens, wall time and limitations, then stop. TRAIN checks are development evidence. Only the independent evaluator may score protected Gold.

**Mandatory candidate smoke commands:**

```bash
python3 -B tools/verify_scaffold.py
python3 -B -m unittest discover -s tests -p 'test_scaffold.py'
python3 -B -m unittest discover -s tests -p 'test_greenfield.py'
python3 -B -m unittest discover -s tests -p 'test_acceptance.py'
python3 -B -m unittest discover -s tests -p 'test_reserved_ml_mode.py'
```

The untouched starter **must fail acceptance** (`melusense/api.py` is unimplemented). A scaffold PASS is not a parser PASS. Do not weaken the contract, remove tests or mask expected initial failures.

## 4. Independent scoring and why the task is useful

| Axis | What is measured |
|---|---|
| Correctness | Exact reply/forward/signature/footer boundaries on independently qualified HPI human Gold: TP/FP/FN, P/R/F1, exact case accuracy and ABSTAIN, where rights allow |
| Safety | Never drop current text, no authorized removals, no invented byte offsets, finite resource limits, inert attachments |
| Code quality | Modular rules, tests, readability, maintainability, errors, security and disciplined scope |
| Efficiency | Coding time, generated tokens, tool calls, runtime, memory and throughput |
| Reproducibility | Frozen input and outputs, identical budgets, isolation, repeatability, failures retained |

This is a **domain-specific coding benchmark**, not a universal model ranking. Run SWE-bench/BFCL separately. No qualified Gold => **NOT_EVALUATED**, not “0 FN” or “100% recall”.

F1 is the harmonic mean of precision and recall; a score on weak Silver labels is not an independent Gold result.

## 5. Research background (coordinator only; not model-training instructions)

- **HPI Email Structure / Quagga (ECIR 2018):** historically annotated ASF/Enron zones; preserve original TRAIN/TEST/EVAL, provenance, source spans and rights. The previous Melusense HPI development review recorded 1,009 valid cases and ~90.6% historic rule F1; it is **not** new blind evidence.
- The former experimental FN classifier produced **0 added TP / 4 added FP** on a known 145-case HPI EVAL. In a separate 4-GiB Thunderbird prefix, **29/29 source-corroborated headers** were already rule-covered. Neither result proves perfect recall. Silver labeling also suffered quotation/blank-line shortcuts and few independent FR/ES positives.
- Classifier development is **not** part of this benchmark. If later justified, open a separately versioned research task and compare rule-only vs optional LLM recovery on independent Gold (additional TP, FP, latency, tokens, safety).
- Public parser examples for research: [Crisp reply](https://github.com/crisp-oss/email-reply-parser), [Crisp forward](https://github.com/crisp-oss/email-forward-parser), [GitHub reply](https://github.com/github/email_reply_parser), [Mailgun Talon](https://github.com/mailgun/talon) and [HPI Quagga](https://github.com/HPI-Information-Systems/Quagga). Coding candidates may inspect public source pages through the approved browser, adapt bounded terms or patterns with provenance/license notes and test them. The private Melusense reference and other benchmark trials remain prohibited.
- **Only approved external corpus reference:** [HPI Email Structure](https://hpi.de/en/database-group/projects/data-integration-projects/web-science/mimir-corpus-exploration-and-knowledge-management/email-structure/). Download availability does not grant permission to republish private correspondence.

## 6. Freeze and start criteria

For each trial, the coordinator records the exact source SHA, obtains independent review of the public-web egress policy, verifies Brave research tools and worker isolation, and transfers a checksum-verified Git-free archive. C01 begins only after the C00 readiness decision. Preserve earlier baselines and run evidence under their original identities; protected HPI Gold and BLIND assets remain outside worker access.
