# ModelBench — standardized candidate build contract

**Status:** Owner-approved build/API task structure; exact offline package and runtime readiness still require independent verification. This is a **coding task**, not model training. The agent builds a reproducible rule-only parser, with an inert classifier extension point for a later separate study.

## A. ASCII folder tree — same for every model/seed

```text
modelbench/                                  # same approved Git-free offline package
├── README.md
├── AGENTS.md                                # task policy, read-only to workers
├── TASKS.md                                 # P1–P4 / C00–C07, read-only
├── MANIFEST.md                              # package fingerprint
├── pyproject.toml                           # candidate packaging contract
├── config/
│   ├── budget.json                          # model-neutral resource limits
│   ├── models.json                          # model examples, not live endpoints
│   └── toolchain.json                       # PROPOSED: verified Brave/MCP identity
├── docs/
│   ├── contract.md                          # public API/safety contract
│   ├── evaluation.md                        # independent score contract
│   ├── RESEARCH_TOOLS.md                    # pinned browser/research contract
│   ├── OFFLINE_AGENT_PROMPT.md              # English copy/paste assignment
│   ├── BUILD_CONTRACT.md                    # this directory/flag contract
│   └── WORKSPACE_LAYOUT.md
├── tools/
│   ├── verify_scaffold.py                   # non-mutating structural check
│   └── preflight.py                         # PROPOSED: non-mutating tool qualifier
├── melusense/                               # DELIBERATELY EMPTY starter
│   ├── __init__.py
│   └── api.py                               # intentionally NotImplemented
├── tests/                                   # frozen visible acceptance tests
│
├── build/                                   # LOCAL/generated, Git ignored
│   └── runs/
│       └── <run-id>/
│           └── workspace/                   # the *only* tree worker can access
│               ├── AGENTS.md, TASKS.md, MANIFEST.md
│               ├── config/, docs/, tools/, tests/, pyproject.toml
│               ├── melusense/              # model-generated candidate modules
│               │   ├── __init__.py
│               │   ├── api.py              # detect_text / detect_eml
│               │   ├── __main__.py         # proposed: python -m melusense
│               │   ├── cli.py              # proposed: --ml-mode off|recover
│               │   ├── models.py           # candidate spans/evidence
│               │   ├── mime.py             # safe charset/MIME ingestion
│               │   ├── canonical.py        # immutable Unicode/CRLF view
│               │   ├── boundary_reviewer.py
│               │   ├── rules/
│               │   │   ├── __init__.py
│               │   │   └── registry.py     # bounded structural regex/TOML registry
│               │   ├── dictionaries/
│               │   │   ├── en.toml
│               │   │   ├── de.toml
│               │   │   ├── fr.toml
│               │   │   └── es.toml
│               │   └── processors/
│               │       ├── __init__.py
│               │       ├── reply.py
│               │       ├── forward.py
│               │       ├── signature.py
│               │       ├── footer.py
│               │       └── recovery_hook.py  # RESERVED only; no ML execution
│               ├── tests/
│               │   ├── fixtures.json      # immutable
│               │   ├── test_acceptance.py  # immutable
│               │   ├── test_scaffold.py    # immutable
│               │   └── test_*.py           # worker's additional tests
│               └── build/
│                   ├── worker-report.json # only worker-authored run report
│                   ├── logs/              # bounded/sanitized diagnostics
│                   └── dist/              # optional deterministic wheel/sdist
│
├── evidence/                                # generated, coordinator-only, Git ignored
│   ├── preflight/<run-id>/
│   └── runs/<run-id>/
│       ├── manifest.json                   # exact source/tool/model/seed
│       ├── browser-acceptance.json
│       ├── isolation-audit.json
│       ├── metrics.json
│       └── checksums.sha256
└── reports/                                 # generated, coordinator/evaluator only
    ├── readiness.md
    ├── runs/<run-id>/
    │   ├── worker-report.json              # retained from candidate
    │   └── evaluator-report.json           # independent score
    └── comparison.md

evaluator-private/                           # completely outside worker mounts
└── hidden-tests-and-approved-Gold/
```

**The candidate-visible path should appear simply as `/workspace`, not the host's `modelbench/`.** Never mount the coordinator root, other `build/runs`, `evidence`, `reports`, host HOME, Git objects, secrets or `evaluator-private` in the worker. Directory naming **does not itself provide isolation**: verify actual denial from a worker. File paths marked `PROPOSED` or `RESERVED` do not exist by virtue of this document.

The root `melusense/api.py` is an immutable *empty starter*. The generated `build/runs/.../workspace/melusense/` holds the candidate's implementation. No `kolibri/`, `mistral/` or `glm/` directory inside the candidate Python package; identity is the Run-ID/manifest/outer workspace.

## B. Reserved classifier mode: same naming as reference CLI, *without* its implementation

The existing production Melusense public CLI accepts `--ml-mode off|recover`, default `off`. Its Python functions also expose `ml_mode="off"`; it is **not** a Boolean `classifier=on/off` switch. Production `--mode A|B` is separate and is **not** classifier activation. For scientific comparability, this future candidate contract reserves the same two mode names without shipping or copying any reference source.

Required candidate Python signatures in the **approved task contract** (actual offline source and runtime still need qualification):

```python
def detect_text(text: str, locale: str = "auto", *, ml_mode: str = "off") -> dict: ...
def detect_eml(raw: bytes, locale: str = "auto", *, ml_mode: str = "off") -> dict: ...
```

Required behavior:
1. **Default or explicit `off`:** run **only** deterministic MIME/canonical/regex/TOML/four-processor/BoundaryReviewer path. Both invocations must produce identical results; no ML weights, runtime or remote LLM may be accessed.
2. **Reserved `recover`:** a recognized but **not implemented** extension point. Raise a documented, deterministic `NotImplementedError` carrying `ml_mode=recover is not implemented` at the public API boundary **before any inference or original-input changes**. A CLI should emit a concise error and exit nonzero; do **not** return a fabricated successful parser response, silently downgrade to `off`, or call a classifier.
3. **Unknown mode:** reject with a clear `ValueError`, not a fallback.
4. **Final safety is unchanged:** `authorized_removals=[]`, preserved input, exact source spans, abstention rather than destructive cleanup.
5. **Future hook:** include `melusense/processors/recovery_hook.py` with only an extension interface/explicit unsupported stub. It must not contain an inference model, trained weights, logits, optimizer, dataset loader, activation policy, threshold learner or remote network call.
6. **No required trained model:** tests exercise the switch **only**. Applied benchmark scoring uses the rules-only `off` path exclusively; `recover` is deliberately **not scored as ML functionality**.

Approved CLI contract (minimal, standard-library `argparse`, no network, local files only):

```bash
python -m melusense sample.eml --ml-mode off --output result.json
python -m melusense sample.eml --ml-mode recover  # explicit unsupported/nonzero
```

Do not silently overwrite `result.json`; because it may hold private mail data, create it with restricted permissions and fail if it exists. `__main__.py` should only dispatch to `cli.main()`. Use the already available packaging environment; do not introduce a new dependency merely for the CLI.

## C. Visible acceptance cases and fair scoring

The checked-in `tests/test_reserved_ml_mode.py` provides the **same** visible tests for every model. They are expected to fail while the starter is empty:
- `detect_text(s)` equals `detect_text(s, ml_mode="off")`, likewise `detect_eml(raw)` equals explicit `off`, including JSON-compatible output and safety.
- `ml_mode="recover"` raises the documented unsupported exception, **without any email mutation, model import or network call**.
- `ml_mode="on"` and other unrecognized values are rejected (do not accept silent aliases).
- `python -m melusense ... --ml-mode off` works on a **synthetic** test email; `recover` exits nonzero and writes no output.
- Both APIs preserve exact Unicode/CRLF and return `authorized_removals=[]` in `off`.
- All frozen prior visible tests stay unmodified and intact. New tests must be included in **the same reviewed/new baseline** for every model.

Candidate grading can assign a small, separate `extensibility/API-discipline` rubric entry, but **never count a reserved stub as classifier accuracy**. No classifier training is in scope. Hidden tests / independent Gold remain evaluator-only and rights-gated.

## D. Build/evidence discipline and freeze gate

The worker owns only source changes in `/workspace/melusense/`, new tests, and `/workspace/build/`; the coordinator creates immutable `evidence` and `reports` records **outside** that mount. Identical model-neutral tasks and tooling apply per seed `41,42,43`, no GitHub needed on Spark. Reused complete fingerprint -> verify/reuse, changed input -> new Run-ID.

The current approved repository contract includes the new mode interface and visible tests, but older `base-v1`, `base-v2` and previously transferred `031f0cfa` packages cannot be relabeled as implementing them. The coordinator must verify the exact approved source SHA, package it into a **new** Git-free archive, and independently qualify real model-to-tool/inference isolation before any C01 run. **Do not** edit historical baselines, run P4, install/modify Brave, or overwrite local Spark evidence as a side effect.
