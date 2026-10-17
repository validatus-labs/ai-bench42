# ModelBench — one portable offline workbench

**Status: OWNER-APPROVED DIRECTORY CONTRACT; WORKER DEPLOYMENT NOT YET QUALIFIED.**
This is the approved directory convention for the current assignment. It replaces an earlier multi-root proposal with one predictable offline workbench. Historical branches, Spark worktrees, receipts and reference/corpus repositories remain untouched.

## The idea

One frozen, Git-free **offline assignment package** can be copied to any eligible machine. The agent does **not** need GitHub access. A coordinator supplies the package and its SHA-256 receipt, and independently qualifies runtime security. The model receives the same assignment, a real pinned Brave/Playwright MCP connection, the same allowed documentation sources and budgets. It may proceed only after a verified readiness decision. **No model training, classifier, FN-Recovery or online-LLM parser is part of Phase 4.**

Brave working in the historical Melusine/Kilo session is **not** proof that a new benchmark worker is filesystem/network isolated. A browser sandbox is not a worker sandbox.

## Standard ASCII directory tree

```text
modelbench/                               # identical Git-free offline package
├── README.md
├── MANIFEST.md                            # package provenance / source hash
├── TASKS.md                               # immutable C00–C07 assignment
├── AGENTS.md                              # immutable agent restrictions
├── config/
│   ├── budget.json                        # unchanged seeds / budgets
│   ├── models.json                        # model catalog, NOT endpoint evidence
│   └── toolchain.json                     # PROPOSED: approved Brave/MCP pins
├── docs/
│   ├── contract.md                        # parser API / KEEP_ALL
│   ├── evaluation.md                      # independent evaluator contract
│   ├── RESEARCH_TOOLS.md
│   ├── HPI_TRAIN.md
│   ├── OFFLINE_AGENT_PROMPT.md           # one identical English task
│   ├── BUILD_CONTRACT.md                 # full source tree + reserved ML flag
│   └── WORKSPACE_LAYOUT.md                # this document
├── tools/
│   ├── verify_scaffold.py                 # existing structural verification
│   ├── greenfield.py                      # existing script; DO NOT auto-install
│   └── preflight.py                       # PROPOSED read-only Brave/MCP verifier
├── melusense/
│   └── api.py                             # deliberately unimplemented starter
├── tests/                                 # frozen visible tests / fixtures
│   └── test_reserved_ml_mode.py           # PROPOSED off-only / recover stub checks
│
├── build/                                 # GENERATED, local, Git-ignored
│   └── runs/
│       └── <run-id>/
│           └── workspace/                 # ONLY this run is exposed to worker
│               ├── AGENTS.md, TASKS.md, config/, docs/, tools/
│               ├── melusense/             # candidate independently writes code
│               ├── tests/                 # frozen tests + own additional tests
│               └── build/
│                   └── worker-report.json # only worker-writable report
│
├── evidence/                              # GENERATED, coordinator-only, ignored
│   ├── preflight/<run-id>/
│   └── runs/<run-id>/
│       ├── manifest.json                  # input/tool/model/budget fingerprints
│       ├── browser-acceptance.json        # actual worker MCP call evidence
│       ├── worker-isolation-audit.json    # allowed AND denied access probes
│       ├── metrics.json                   # tokens, time, vLLM / Prometheus
│       └── checksums.sha256               # immutable artifact SHA-256 records
│
└── reports/                               # GENERATED, coordinator-only, ignored
    ├── readiness.md                       # PASS / DEVIATION / BLOCKED + reasons
    ├── runs/<run-id>/
    │   ├── worker-report.json             # retained verbatim from worker
    │   └── evaluator-report.json          # independent; never worker-readable
    └── comparison.md                      # only after independently scored runs

evaluator-private/                         # SEPARATE protected storage/mount
└── hidden-tests-and-Gold/                 # never visible to coding workers
```

**Reality check:** `config/toolchain.json` and `tools/preflight.py` remain **proposed**, not implemented merely because they appear in this tree. The generated `build/`, `evidence/` and `reports/` paths are already ignored by Git; naming them does not mean they exist or contain qualified results. Never commit correspondence, Gold, secrets or raw logs.

`build/runs/<run-id>/workspace/` is an illustrative **coordinator filesystem path**. Inside a properly isolated container, present only that candidate tree at e.g. `/workspace`. **Do not mount the coordinator root**, sibling runs, reference code, private evaluator files, host HOME or Git credentials. Use independently enforced read-only / writable mounts and deny access by actual negative tests. Merely nesting directories is not security.

## One command/prompt per model: same sequence everywhere

The normative candidate module layout, generated build/dist location, and future-only `--ml-mode off|recover` contract are in [BUILD_CONTRACT.md](BUILD_CONTRACT.md). For a standalone copy/paste instruction in English, use [OFFLINE_AGENT_PROMPT.md](OFFLINE_AGENT_PROMPT.md). Do not use different prompts for different models; Run-ID/manifest carries identity. No classifier training or inference is permitted.

1. **INPUT:** Coordinator transfers one explicitly approved, content-addressed offline package; checks its archive and file hashes and records an immutable Run-ID with exact model revision, backend, KV calibration status and seed (41/42/43). No agent GitHub access.
2. **C00 / PREFLIGHT:** Verify installed Brave executable, Playwright, MCP server/runtime/config hashes, actual agent-issued browser tool calls, headless/sandbox/isolation, service-worker block and the four allowed documentation origins; verify effective DNS/redirect/IPv4/IPv6 egress denial and filesystem denial **outside the candidate sandbox**. The previously successful Kolibri/Kilo host-open session does not itself satisfy this gate.
3. **RESULT:** If any mandatory test is absent or different, write `evidence/preflight/<run-id>/` + `reports/readiness.md` as `DEVIATION` or `BLOCKED`. **Stop before C01**; do not install, auto-repair, switch browsers or silently change the frozen task.
4. **P4 / C01–C07 only if READY:** Worker starts from the same frozen empty `melusense/api.py`, runs the initially *expected failing* acceptance tests, implements the rules-only EN/DE/FR/ES MIME/regex/TOML/BoundaryReviewer parser, keeps `authorized_removals=[]`, and adds its own adversarial tests without modifying provided tests or the task. The public `ml_mode` defaults to `off`; `recover` must fail explicitly as unimplemented (no weights/training/inference), including the minimal local CLI. Worker writes only its own `build/worker-report.json`.
5. **EVALUATION:** Coordinator freezes worker outputs; a distinct evaluator scores hidden tests/rights-cleared Gold if available. Missing qualified Gold means `NOT_EVALUATED`, never perfect recall or 0 failures. TRAIN is optional and only available with explicit rights/privacy/worker-disclosure approval and an identical bundle hash.
6. **REPEAT:** Identical complete Run-ID/fingerprint -> verify/reuse; changed model, version, baseline, toolchain, data, budget or seed -> new Run-ID, no overwrite, no reset. Previous P1–P3 receipts are reused with their precise original scope; `PARTIAL` and `BLOCKED` stay as such.

## One reusable English agent prompt

Use **[OFFLINE_AGENT_PROMPT.md](OFFLINE_AGENT_PROMPT.md)** verbatim for every model and seed. This stand-alone file contains the full C00 through C07 handoff and the non-executable `ml_mode=off|recover` compatibility obligation. The complete ASCII candidate package tree is in **[BUILD_CONTRACT.md](BUILD_CONTRACT.md)**. Short summaries are not a substitute for the normative frozen task and contract.

## Roles, security and retention

| Role | Access | Responsibility |
| --- | --- | --- |
| Coordinator | package + outer build/evidence/reports | offline transfer, hash/version pinning, sandbox/egress proofs, immutable run archive |
| Coding worker | only its own isolated `/workspace` + approved browser tools | independently implement task, produce own report |
| Independent evaluator | frozen candidate + protected evaluator inputs | hidden tests, qualified Gold scoring, review; never grants workers Gold access |

The active repository contract now specifies Brave and the reserved classifier-mode interface; Chromium-only `base-v2` is a **historical** branch, not the current assignment. A new exact-SHA Git-free offline package and live model-to-tool/inference isolation checks still require coordinator verification and independent approval. Do not start a coding run merely because this documentation is merged. The user-approved cleanup scope is **GitHub-only**; preserve all local DGX Spark runs, measurements and calibration records.
