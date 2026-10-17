# Agent Contract — ModelBench / Melusense AgentBench

**Frozen candidate instruction.** Read [MANIFEST.md](MANIFEST.md), [TASKS.md](TASKS.md), [docs/contract.md](docs/contract.md), [docs/WORKSPACE_LAYOUT.md](docs/WORKSPACE_LAYOUT.md) and [docs/evaluation.md](docs/evaluation.md) before editing code.

## Core obligations

- The starter is deliberately **unimplemented**. You must independently build a rules-only parser. Do **not** add a classifier, FN training, LLM calls, automated deletion or unauthorized dependencies.
- Never change or tick `TASKS.md`, `AGENTS.md`, frozen `config/`, provided fixture/tests, public API schema or evaluation scripts. Store task progress and all command results in ignored `build/`.
- Preserve original message content, CRLF and Unicode codepoint spans. Safe MIME decoding and inert attachment **metadata only**. No fabricated raw-byte provenance, no unbounded regex or unreviewed cleanup. `authorized_removals=[]` always; uncertainty must ABSTAIN.
- Never access or copy the original `validatusinternal/melusense` implementation, competitors, another trial, the human Gold/BLIND corpus, hidden evaluation, other agent output, GitHub credentials or host secrets. Agent isolation is **enforced by the coordinator**; Git branches or worktrees alone are insufficient.
- Do not fetch reference code, publish raw EML, contact third-party services or circumvent network limitations. Follow pinned test/resource limits. No reset, stash, checkout or overwrite of unexpected work; fail closed and report conflicts.
- Report all failures honestly; no tests may be removed, weakened or silently skipped. All source comments, tests and reports in English.

## Required candidate source layout

Keep the original root task files untouched. Put the implementation in the package below; create missing folders and `__init__.py` files as needed:

```text
melusense/
├── __init__.py
├── api.py                 # Required public detect_text / detect_eml
├── models.py              # Candidate/evidence and spans
├── mime.py                # Inert EML MIME/charset decoding
├── canonical.py           # Original-source line view
├── boundary_reviewer.py   # Final deterministic arbitration
├── rules/
│   ├── __init__.py
│   └── registry.py        # Bounded regex + TOML loading
├── dictionaries/
│   ├── en.toml
│   ├── de.toml
│   ├── fr.toml
│   └── es.toml
└── processors/
    ├── __init__.py
    ├── reply.py
    ├── forward.py
    ├── signature.py
    └── footer.py

tests/
├── fixtures.json          # Frozen: DO NOT EDIT
├── test_scaffold.py       # Frozen: DO NOT EDIT
├── test_acceptance.py     # Frozen: DO NOT EDIT
└── test_*.py              # Your own tests, in the same directory

build/                     # Ignored; local run artifacts only
├── worker-report.json
└── ...                    # Logs, metrics, failures, decisions
```

Do not add wrapper folders such as `kolibri/` or `glm/` inside the candidate package. Model/seed identity belongs in **external sandbox path, Run-ID and result branch**. Extra private modules are permitted inside `melusense/` if they fit this architecture; do not rename required entry points or change the frozen public contract.

A candidate must not fork or copy code from competitor/reference projects even when such projects are linked in human-facing README background material. Use only frozen task instructions and the permitted standard library/tools.

## Work sequence and idempotence

1. Read instructions, report exact clean base SHA, frozen artifacts/hashes, model identity and run metadata.
2. Run scaffold checks and **expected failing** acceptance tests before implementation; record evidence without modifying tests.
3. Implement the modules under the required paths, run visible tests and add adversarial tests without changing the contract.
4. Store an English `build/worker-report.json` with final source SHA, tests, errors, design rationale, timings and available token/tool-call counts; stop for independent evaluation.
5. On rerun, check the same Run-ID/config fingerprint and immutable inputs; reuse verified results or **fail closed**. Never silently restart a changed trial or claim prior failures as PASS.

Only the coordinator may freeze the final candidate tree and move it to a unique `trial/<model-slug>/seed-<n>` branch. The worker sandbox must not contain shared Git refs, the evaluator, hidden Gold or other model branches.

See [Workspace layout and lifecycle](docs/WORKSPACE_LAYOUT.md) for the repository/worktree/output paths and [Task checklist](TASKS.md) for phases.
