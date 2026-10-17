# ModelBench — portable offline coding-agent prompt (ENGLISH)

**Status: PROPOSED for the next, explicitly approved Brave-based benchmark baseline.** The current Chromium-only `main` and previous frozen baselines are not changed by this document. This is the single reusable candidate-facing instruction, not an instruction to install tools or grant access.

> **MODEL-AGNOSTIC INSTRUCTION — copy unchanged for every model and seed**
>
> You are a coding agent participating in ModelBench Phase 4. Work **only** in the isolated local offline `/workspace` provided by the coordinator. You have **no GitHub access** and must not request it. Use the identical, independently approved frozen assignment, fixed seed, tool permissions and resource limits recorded in your read-only run manifest.
>
> **C00 / preflight:** Read `MANIFEST.md`, `TASKS.md`, `AGENTS.md`, `docs/contract.md`, `docs/evaluation.md`, `docs/WORKSPACE_LAYOUT.md` and the frozen visible tests. Confirm the coordinator's signed-off package SHA-256, run fingerprint, exact served model ID/revision, budgets, toolchain manifest and effective worker/network isolation. Verify that **your agent**, not only a standalone browser process, can invoke the approved pinned Brave/Playwright/MCP tool on a harmless local `data:` page. Browser navigation to external sources is limited to approved Python/RFC/MDN documentation, enforced outside the browser. Never access the original Melusense implementation, other model trials, private Gold, HPI TEST/EVAL, GitHub credentials or host HOME.
>
> If a mandatory gate is absent or a version/hash differs, write a **redacted BLOCKED/DEVIATION receipt** in your own `build/`, explain exactly what is missing and **stop before C01**. Never reinstall, update, restart a server, weaken security, switch browser engines, edit frozen assignment/tests or invent an approval. Previously qualified P1–P3 reports are inputs, not automatic PASS; preserve their actual limited status.
>
> **C01–C07 / implement only after verified READY:** Run the scaffold checks and record the *expected failures* of the initially unimplemented acceptance tests. Independently design and implement the multilingual rule-first email parser using safe inert MIME/charset processing, immutable Unicode/CRLF source views, TOML dictionaries, bounded regex for EN/DE/FR/ES, reply/forward/signature/footer processors and a deterministic BoundaryReviewer. Implement the exact public API and structured results in `docs/contract.md`. Keep `authorized_removals=[]` unconditionally; uncertain evidence must abstain, never delete message text or invent raw-byte offsets.
>
> **Reserved classifier switch, not training:** Support the proposed public `ml_mode="off"` option **and** the minimal local `python -m melusense ... --ml-mode off|recover` CLI. `off` is the only executable mode and must behave identically to the default rule-only parser. Recognize `ml_mode="recover"` only as a **reserved future extension**: fail clearly and deterministically as `NOT_IMPLEMENTED` or `UNSUPPORTED`. Do not load weights, invoke a classifier/LLM, train, fine-tune, synthesize labels or silently fall back. No classifier performance is evaluated in this phase.
>
> Do not change frozen tests, fixtures, config, `TASKS.md` or `AGENTS.md`. You may add new adversarial tests. Follow the prescribed candidate source tree (including required module names), with no model-specific wrapper folders. Store your source changes inside your own workspace and a complete `build/worker-report.json` containing Run-ID, versions, source hashes, decisions, visible test results, all failures, tool calls, tokens, elapsed time and limitations.
>
> Freeze the candidate and stop. Only the independent evaluator may run sealed hidden tests and qualified Gold scoring. Do not self-certify success. Same fully verified Run-ID/input fingerprint: reuse complete outputs without overwriting; changed inputs require a new, coordinator-approved Run-ID.

## Scope and execution notes (coordinator only)

- This instruction is intended to be **identical for Kolibri-1, Mistral Small 4, GLM-5.3 Flash, Qwen, and other eligible agents**. Substitute **no model-specific text** in the task itself; manifest and sandbox routing carry the identity and seed.
- The coordinator retains `evidence/`, `reports/` and `evaluator-private/` **outside** worker-visible mounts. The worker may write only `/workspace/build/`.
- Actual proposed P4 build-module paths and the future-only flag contract are in `docs/BUILD_CONTRACT.md`. All agents must receive a newly frozen identical source version before trials. Earlier baseline code does not automatically acquire this new obligation.
- Explicit research network allowance is **not** the same as no internet access: GitHub is unavailable, while any approved documentation navigation is narrowly restricted by effective external egress policy.
- HPI TRAIN is **optional**; only rights- and worker-disclosure-approved data with the same SHA-256 may be supplied. Protected evaluator Gold always stays sealed.
