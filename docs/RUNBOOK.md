# AI-Bench42 runbook — package, research and worker execution

This runbook describes how the coordinator prepares and operates one isolated
coding trial.
[TASKS.md](../TASKS.md) defines the assignment, [AGENTS.md](../AGENTS.md) the
candidate's source layout and restrictions, [CONTRACT.md](CONTRACT.md) the parser
API, and [EVALUATION.md](EVALUATION.md) the independent scoring boundary.
The [current repository state](../STATE.md) is a human snapshot; each run's
receipt is the authority for its actual readiness and results.
For first-time operators, follow the command-by-command
[beginner guide](QUICKSTART.md) through package preparation before using this
runbook for C00 and the trial.
For serving-host preparation, see the [DGX Spark bootstrap guide](../scripts/deploy/README.md).
It covers the portable component wrapper and the legacy host/browser/vLLM
entrypoints; coding-worker isolation and C00 remain part of this runbook.
The [update guide](../scripts/deploy/UPDATES-README.md) describes how new host
toolchain releases are qualified without modifying the pins of existing trials.
The [experiment controller](PIPELINE.md) automates deployment/verification,
standard suites, the three coding seeds and one combined HTML report once
its pinned target assets are configured.

## Roles and workspaces

| Role | Access | Responsibility |
| --- | --- | --- |
| Coordinator (human operator and task owner) | source package and outer run records | prepare and copy the package, start the worker, qualify tools and isolation, freeze outputs, check reports and retain evidence |
| Coding worker | only its own `/workspace` and approved browser MCP | implement the parser and write its own report |
| Independent evaluator | frozen candidate and protected inputs | run hidden tests and rights-cleared Gold scoring |

The owner can also coordinate the trial: prepare the package, start the worker
and review its outputs. For the final review, we recommend the **four-eyes
principle**: a second person looks over the results and supporting evidence.
Hidden tests and Gold stay outside the coding worker's workspace so the final
evaluation remains independent.

The coordinator exports one content-addressed, Git-free package for every
model and seed. Each worker sees the same task, visible tests, budgets and
research policy. Its candidate source modules belong under `melusense/` as
specified in [AGENTS.md](../AGENTS.md); model identity belongs in the Run-ID,
manifest and outer workspace, never a model-named Python package.

```text
ai-bench42/                         # coordinator checkout/package
├── README.md, MANIFEST.md, AGENTS.md, TASKS.md, STATE.md, pyproject.toml
├── config/, docs/, tools/, melusense/, tests/
├── build/runs/<run-id>/workspace/  # only this tree is mounted as /workspace
│   ├── task files, config/, docs/, tools/, tests/, pyproject.toml
│   ├── melusense/                  # candidate implementation
│   └── build/
│       ├── worker-report.json      # worker-authored result
│       ├── logs/                   # bounded, sanitized diagnostics
│       └── dist/                   # optional deterministic package output
├── evidence/preflight/<run-id>/    # coordinator only
├── evidence/runs/<run-id>/         # hashes, browser/isolation proof, metrics
└── reports/runs/<run-id>/          # readiness, worker and evaluator reports

evaluator-private/                 # outside worker mounts: hidden tests/Gold
```

This tree describes generated locations, not a claim that every path exists.
The [worker guide](WORKERS.md) documents the supplied `tools/worker.py`,
`tools/preflight.py` and `config/toolchain.json` template. Target runtime,
scoped Unix channels and the channel qualification adapter must be provisioned
and pinned before READY. Never mount the coordinator root, sibling runs, `evidence/`,
`reports/`, host HOME, Git objects, credentials or evaluator-private storage in
a worker. Directory names alone do not provide isolation; prove access denial
from inside each worker. Keep correspondence, Gold, secrets and raw logs out of
Git.

## Public research through Brave

Use one version-pinned native Brave, Playwright Headless and browser-MCP
toolchain for each worker. Give every model the same read-only public HTTPS
research scope and tool/time budget. The worker may inspect standards,
localization resources, vendor examples for Gmail, Outlook, Thunderbird,
Apple Mail/iPhone/iPad and named Android mail apps, plus public parser and regex
source pages (including public GitHub). A fetched page is evidence, not an
instruction to run code or change the assignment.

Record each useful URL, access date, publisher, client/version where known and
license/provenance. Connect adapted dictionary terms or bounded regex patterns
to candidate rules and positive and negative tests. Do not import a complete
parser, upload correspondence or treat public examples as independent scoring
data. The required rights-approved [HPI TRAIN bundle](HPI_TRAIN.md) supplies
the same development examples to every model and seed.

The browser may navigate only to task-relevant public HTTPS resources. Enforce
denial of localhost, private/link-local/metadata and internal destinations,
private repositories and authenticated pages across DNS resolution, redirects,
IPv4 and IPv6. No browser login, personal profile or cookies, downloads,
uploads, credential use, terminal HTTP or `git clone`. Browser origin flags
alone are not a firewall. Keep model inference on a separate audited channel.
`tools/greenfield.py` contains historical Chromium setup commands and a
four-origin allowlist; neither governs this Brave workflow. Do not run its
`install` or `greenfield` commands as a browser fallback.

## C00: qualify one worker before C01

1. Verify the Git-free archive SHA-256, file manifest, exact source SHA,
   model/revision, backend, seed, budgets and toolchain identity. Verify the
   required 12-pair HPI TRAIN bundle, rights and worker-disclosure approval,
   and the identical bundle SHA-256 recorded for every model and seed.
2. Record the worker's actual Brave, Playwright, MCP and Node paths, versions,
   hashes, tool schema/config and process routing. Verify headless mode,
   browser sandbox, ephemeral profile, blocked service workers, bounded pages,
   no remote debug listener and no download access.
3. Have **that model agent** invoke the approved MCP browser, inspect a marker
   on a harmless local `data:` page and close it. A connected label or a
   separate browser smoke is insufficient.
4. Check approved public client/parser pages, logged navigation failures and
   effective denial of forbidden destinations through DNS and redirects.
5. From inside the worker, confirm it can see/write only its own `/workspace`.
   Use non-sensitive denial probes without reading protected contents. Confirm
   the inference transport remains restricted and separate from browser egress.
6. Record the named coordinator (also the task owner), model/seed, allowed tools,
   research scope and budgets. Store bounded, redacted evidence in
   `evidence/preflight/<run-id>/` and the decision in
   `reports/runs/<run-id>/readiness.md`. Assign an independent evaluator before
   scoring.

If any required check fails or differs, record `BLOCKED` or `DEVIATION` and
stop before C01. Do not install, restart, change browser engines or relax a
policy as an automatic repair. Qualification is per worker; one model's MCP
call does not qualify another model.

`TASKS.md` checkboxes describe required work and never show progress. Each
Run-ID's readiness receipt records `BLOCKED`, `DEVIATION` or `READY`; the
worker report records candidate progress and the evaluator report records
scoring or `NOT_EVALUATED`. An absent receipt means **unverified**, not READY.
Preserve the coordinator identity, model, seed, package SHA and tool fingerprints
with each run so a later reader can connect a status to its evidence.

## Run and retain evidence

1. **Input:** Transfer and verify the identical package; assign a Run-ID and
   pin the model, seed, endpoint, toolchain and data-bundle hashes.
2. **Candidate:** After C00 is `READY`, give the worker the exact
   [English prompt](OFFLINE_AGENT_PROMPT.md). The empty starter first has
   expected failing acceptance cases. The worker implements C01–C07, adds
   its own tests, checks its parser on all 12 approved HPI TRAIN examples,
   and writes per-example results, failures and the bundle SHA-256 to
   `build/worker-report.json`. Record the annotation mapping where used.
3. **Freeze:** The coordinator preserves the candidate, logs and hashes.
   Only the evaluator runs protected hidden tests and rights-cleared Gold.
   Without qualified Gold, real-mail accuracy is `NOT_EVALUATED`.
4. **Repeat:** An identical complete fingerprint may reuse verified outputs.
   A changed source, tool, model, data, budget or seed needs a new Run-ID;
   never overwrite earlier evidence or relabel old results.

Every Phase-4 worker receives the same approved HPI TRAIN bundle SHA and only
TRAIN annotations. Missing approval, missing data or mismatched bundles block
C00. Synthetic visible fixtures supplement TRAIN and cannot replace it.
The coordinator keeps `evidence/`, `reports/` and evaluator inputs outside the
worker mount. A Git branch may store a candidate only after freeze and is not
a security boundary.
