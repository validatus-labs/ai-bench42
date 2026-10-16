# Common task checklist — base-v1

All three models receive this identical file at the same pinned starting SHA.
No prior Melusine research gates or reference implementation are inherited.
Coordinator infrastructure phases and candidate development are separate.

## Phase 1 — Infrastructure and metrics (coordinator)

- [ ] Inventory pinned model revision, quantization, context and serving limits.
- [ ] Central Prometheus: health, memory, TTFT, prefill, decode, cache, queue.
- [ ] NVIDIA AIPerf: identical workloads at client concurrency 1/2/4, three runs.
- [ ] Record Run-ID, configuration/version hashes, raw outputs and limitations.

## Phase 2 — General evaluation (coordinator)

- [ ] Freeze LightEval version, dataset revisions, task names, prompts and metrics.
- [ ] Use IFEval, MMLU-Pro and BBH with identical sample IDs/rules for all models.
- [ ] Verify task/backend support; no silent task substitution or truncation.
- [ ] Report separate benchmark scores; pilot subsets are not full-suite scores.

## Phase 3 — Coding and tool calls (coordinator, later)

- [ ] Pin a SWE-bench Verified subset, environments and evaluation protocol.
- [ ] Pin BFCL selection and actual tool-call scoring; retain failures.
- [ ] Independent evaluator reviews success, safety, cost and reproducibility.

## Phase 4 — Melusine AgentBench (candidate, once coordinator starts trial)

- [ ] C01: Inspect starter, establish fresh failing acceptance baseline.
- [ ] C02: Specify typed registry, candidate spans, provenance and bounded execution.
- [ ] C03: Implement independent locale-aware reply/forward/signature/footer rules;
      start FR/EN/DE/ES. Preserve Unicode code-point indices and CRLF verbatim.
- [ ] C04: Implement inert MIME ingest and attachment metadata. Never execute,
      fetch or export attachments; never infer unproven raw-byte source offsets.
- [ ] C05: Wire detect_text/detect_eml and deterministic JSON-compatible results.
      Candidate detection alone grants no removal authority; unsafe mapping abstains.
- [ ] C06: Add positive/negative/adversarial tests for malformed MIME, Unicode,
      mixed-language current-body false positives and resource limits.
- [ ] C07: Run all visible tests unchanged; document failures, architecture and
      exact commands in build/worker-report.json. Stop for independent evaluation.

Private real-corpus rights, mapping and HUMAN Gold gates belong to the evaluator;
no model invents labels, accesses held-out data or certifies its own precision/F1.
No direct use, copy, dependency or execution of mail-parser-reply is permitted.
External source reuse requires pinned file-level license/provenance approval.
