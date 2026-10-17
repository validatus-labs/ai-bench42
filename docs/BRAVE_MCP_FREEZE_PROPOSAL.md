# Proposal — ModelBench Brave/Playwright MCP baseline (NOT FROZEN)

**Decision intent (2026-10-17):** Prefer the existing, proven native **Brave + Playwright Headless + Kilo MCP** research toolchain over provisioning a second Chromium browser, **provided every ModelBench worker receives an equally pinned, isolated and restricted configuration**. This proposal is not an evaluation result, installation order, or permission to start Phase 4.

**Source commit for this proposal:** `031f0cfa5a33383aafd073899e29294af9c8dfc2` (`main` on 2026-10-17). The historical `benchmark/base-v1` and `benchmark/base-v2` references, original Spark trials and published reports remain unchanged. **This draft branch now changes proposed tasks, API contract, agent instructions, new tests and docs only; none of these have been merged into `main` or approved as a frozen benchmark.** No new baseline SHA has been approved or frozen.

## A. Verified evidence versus outstanding claims

| Question | Current observation | Status |
| --- | --- | --- |
| Earlier Melusine R00 browser qualification | Reported independent 10/10, sandbox/headless and profile isolation, retained R00 evidence | PASS for **that** Melusine environment only |
| Native Brave/Playwright local `data:` smoke | Successful, namespace/Seccomp sandbox reported | PASS for local browser function |
| Kolibri Kilo-agent actual browser tools | Five successful MCP invocations: open local page, read marker/snapshot, close tab | PASS for **that** Kolibri/Kilo session |
| Identical, pinned MCP server and browser versions for each model | Not established for Kolibri/Mistral/GLM/Qwen | NOT_EVALUATED |
| Explicit docs-only origin list + service-worker block | Not demonstrated in current live configuration | DEVIATION |
| OS/container-enforced egress + filesystem/reference denial | Not demonstrated by an actual worker | BLOCKED |
| HPI/Quagga TRAIN worker disclosure | No approved common TRAIN bundle confirmed | NOT_EVALUATED; do not supply TRAIN |
| Independent evaluator + rights-cleared Gold | Not qualified | BLOCKED for protected-data scoring |
| Coding Phase 4, C01–C07 | Not started | BLOCKED |

The **local** report is referenced by the operator as `evaluations/results/modelbench-browser-preflight.md`; the PR author has not read its full contents or verified its absolute path, hashes, version fields or attachments. Likewise, the R00 evidence paths are historical relative paths, not an assertion of a current deployment root. Do not invent the missing values or use a report heading in place of actual configuration inspection.

## B. Required new browser contract (candidate v3)

The coordinator, not the model, qualifies the following on the real host and then pins the values in an **external signed-off run manifest**. A new frozen task revision should specify:

1. **One research-tool identity:** actual Brave executable path/version/SHA-256; Playwright package version; Python/Node runtime if used; actual Kilo extension version; MCP server package/version, executable path, transport, tool schema and exact configuration hash. Distinguish Python Playwright from `@playwright/mcp` and from Kilo-provided browser MCP tools. Do **not** assume the five Kilo calls came from `@playwright/mcp@0.0.83` unless proven.
2. **Single equal affordance:** every coding model gets the identical approved browser actions, tool budget, documentation URLs, browser/profile policy and effective network restrictions. Prove an agent-issued MCP call from each model, not merely `connected` state.
3. **Confinement:** headless, sandbox enabled, separate clean browser profiles, service workers blocked, no public debugging port, no credential-bearing personal profile, bounded page size/timeouts, no downloads or filesystem escape.
4. **Research origins:** limit worker navigation to `https://docs.python.org`, `https://www.rfc-editor.org`, `https://datatracker.ietf.org`, `https://developer.mozilla.org`; no GitHub/reference code, competing solutions, private evaluator or Gold. Documentation is untrusted input, not instructions.
5. **Actual egress isolation:** an origin allowlist in an MCP or browser flag is insufficient. Enforce host/container network allowlisting and browser process confinement; demonstrate permitted-origin success and deliberately disallowed neutral-origin denial with logs; do not read private data to prove denial.
6. **Worker filesystem isolation:** Git-free exported source only; no shared Git objects, credentials, reference `validatusinternal/melusense`, HPI TEST/EVAL, hidden evaluator, other worker output, or outside home mounts. Verify real denial, not only an intent statement.
7. **Idempotence:** same signed-off source/tools/model/data/seed inputs -> verify/reuse immutable Run-ID; mismatched inputs -> BLOCKED and a new Run-ID only with explicit authorization. No silent installation, updates, fallback to Chromium, or silent replacement of the current Brave version.
8. **Models:** pin exact model revision/tokenizer/backend, context/KV settings and supported tool gateway for each candidate. The presence of a Kolibri MCP connection does not qualify a Mistral/GLM endpoint.
9. **Data:** no HPI real-mail TRAIN bundle without independent rights, privacy and worker-disclosure approval and an identical SHA-256 for every worker. No real-mail content or Gold in Git.
10. **Evaluation:** C01–C07 stays rules-only, with no executing classifier, training, or LLM parsing. A **reserved `ml_mode=off|recover` extension point** is proposed: `off` runs exactly the rule-only pipeline; `recover` reports unsupported and never loads or runs a model. Keep `authorized_removals=[]`; permit independent evaluator-only scoring only when qualified Gold exists.

## C. Proposed *minimum* changes for an approved freeze

Do not update existing `benchmark/base-v1` or `benchmark/base-v2` refs. Prepare a new exact-SHA branch/freeze only **after** qualification:

- `AGENTS.md`: replace the Chromium-only *research-tool identity* clause with the pinned, verified Brave/Kilo/Playwright tool contract, while preserving research prohibitions, source and evaluation isolation.
- `TASKS.md`: revise C00 for the approved Brave adapter and verified worker policies (STILL OPEN), and C05–C07 for the reserved, non-executing ML-mode switch and reproducible local CLI. Keep original parsing/safety requirements; never train a model.
- `docs/RESEARCH_TOOLS.md`: define the existing Brave verification path, metadata/hash capture, `data:` smoke, permitted RFC/Python/MDN research, negative egress/worker-denial tests; no installation as a prerequisite.
- `config/budget.json`: version an explicit research tool descriptor for a new baseline; preserve seeds, budgets and source contract, never replace pending hashes with made-up values.
- `tools/greenfield.py`: keep rights-gated HPI functions; either add a **non-mutating** Brave verification adapter with tests, or separate a read-only checker. The current Chromium installer must never run as an implicit Brave fallback.
- `tests/`: include the same proposed reserved-mode API/CLI acceptance test for all models, plus future offline mocked browser-compatibility/policy tests; initial parser acceptance is **expected to fail** until each agent implements the candidate.
- `docs/evaluation.md` and `docs/WORKSPACE_LAYOUT.md`: name the new exact freeze SHA only after approved review; preserve existing historical versions.

**No automatic Brave configuration changes or service restarts.** Where a required safeguard is absent, prepare an owner-reviewed change and independently re-probe that *specific* safeguard.

## D. Required audit artifacts and release gate

The coordinator should produce a private, redacted and independently reviewed:
- `brave-toolchain-manifest.json`: path, binary/package hashes, runtime versions, MCP schema/config fingerprint and local R00 pointers.
- `worker-isolation-audit.json`: per-worker permitted/denied browser and filesystem/egress probes; redacted evidence, no secrets.
- `browser-acceptance.json`: actual per-model MCP tool calls and results under an identical configuration.
- `preflight.json`: immutable baseline candidate SHA, approved budgets, model settings, optional TRAIN SHA and previous P1–P3 statuses.
- `freeze-decision.md`: owner approval + independent auditor sign-off; approval of a **toolchain design** is not a Phase-4 readiness PASS.

**Release decision:** `DEVIATION` until the Chromium-only contract is replaced by an approved new SHA. `BLOCKED` for starting Phase 4 until effective egress/worker confinement, verified equal agent MCP affordance and independent evaluator requirements are met. No worker may self-approve.

## E. Offline handoff

Only the **coordinator with GitHub access** fetches and freezes the eventual new source. The Spark has no GitHub access by design. Transfer a signed-off Git-free archive with SHA-256 receipt, validate it on both ends, instantiate independent worker sandboxes/seeds 41/42/43, and keep the original 22-file transfer and past Kolibri P1–P3 reports untouched.

**Current draft PR implementation:** [English reusable prompt](OFFLINE_AGENT_PROMPT.md), [ASCII candidate/build tree and reserved ML interface](BUILD_CONTRACT.md), proposed edits to `TASKS.md`, `AGENTS.md`, `docs/contract.md`, `docs/evaluation.md`, `MANIFEST.md`, `docs/WORKSPACE_LAYOUT.md`, `.gitignore`, and a **new** `tests/test_reserved_ml_mode.py`. This is only a future assignment proposal, **not** proof those new tests have passed. The **numeric** seed/time/token budgets in `config/budget.json` remain unchanged, but its research-tool metadata and reserved-mode interface are **changed on this proposal branch only** and still contain coordinator qualification placeholders. `tools/greenfield.py`, original preexisting tests/fixtures, `main`, historical baseline refs and all Spark runtime/evidence remain unchanged. A separate read-only Brave verifier, real per-worker isolation proof, source freeze and fresh SHA-256 offline export are still missing. The active operational contract still requires the original Chromium baseline until the newly approved Brave instructions and a new SHA have actually been qualified and frozen.
