# Workspace layout and candidate lifecycle

**Audience:** coordinator and coding workers. **Status:** directory contract for future trials; it does not provision containers, secure sandboxes or a model server.

## Three distinct layers

```text
source repository: validatusinternal/melusense-benchmark (private)
  main                       # Living human-facing docs and future revisions
  benchmark/base-v1          # ONLY active frozen baseline; tasks + tests + budgets
  trial/<model>/seed-<n>     # Candidate output branch, after coordinator freeze

coordinator working storage (outside candidate sandboxes)
  bases/
    base-v1-<full-sha>/      # Git-free export of the exact frozen tree
  trials/
    <model-slug>/
      seed-41/               # Isolated worker, fixed source, local build/
      seed-42/
      seed-43/
  results/
    <run-id>/
      manifest.json          # Model/deployment/tool/dataset SHA, config
      metrics.json           # Serving, quality and tool/coding metrics
      worker-report.json     # Unedited candidate report and failures
      evaluator-report.json  # Independent pass/fail and Gold scoring
      logs/                  # Bounded non-secret raw diagnostics
  evaluator-private/         # Gold and hidden fixtures: worker has NO access
```

The exact coordinator root is deployment-specific (DGX Spark or a remote controller) and must be recorded in the run manifest. Paths above illustrate the required separation, **not** already-created directories.

## Why branches *and* isolation?

One output branch per **model × seed** is useful for reviewing, comparing and preserving code without mixing solutions. But branches/worktrees share a Git object database and are **not** a security boundary. Workers receive isolated Git-free exports or rigorously separated containers with only their own base and scratch files, never repository credentials, reference source or private Gold.

**Proposed output naming:**
- `trial/kolibri-1/seed-41`, `.../seed-42`, `.../seed-43`
- `trial/mistral-small-4/seed-41`
- `trial/glm-5.3-flash/seed-41`
- `trial/qwen/seed-41`
- New profile: `trial/<validated-model-slug>/seed-<validated-seed>`

Names are *conventions*, not evidence that a trial has been run. Coordinator records the exact served model name, checkpoint revision and all quantization/KV/backend settings in `results/<run-id>/manifest.json`.

## Candidate module layout

The coding agent **must** create this package tree within its isolated starter, not add a model-specific top-level folder:

```text
melusense/
  __init__.py
  api.py
  models.py
  mime.py
  canonical.py
  boundary_reviewer.py
  rules/{__init__.py,registry.py}
  dictionaries/{en,de,fr,es}.toml
  processors/{__init__.py,reply.py,forward.py,signature.py,footer.py}
tests/
  fixtures.json             # immutable
  test_scaffold.py          # immutable
  test_acceptance.py        # immutable
  test_*.py                 # candidate additions only
build/
  worker-report.json        # ignored and collected externally
```

The actual frozen API in [contract.md](contract.md) prevails over module aesthetics. The solution must have exact Unicode spans, bounded regex, safe MIME, source evidence and `authorized_removals=[]`.

## Idempotent run state machine

```text
DRAFT ASSIGNMENT
    |
    v
REVIEW + FROZEN BASE SHA
    |
    v
PREFLIGHT (model, context, safe sandbox, hashes, budget)
    | -- mismatch --> BLOCKED (no silent changes)
    v
PREPARED (Run-ID + identical frozen source)
    |
    v
WORKER EXECUTION (capture failures and outputs)
    |
    v
FROZEN CANDIDATE TREE
    |
    v
INDEPENDENT EVALUATION (private Gold)
    |
    v
IMMUTABLE REPORT + optional approved trial branch
```

Same Run-ID and matching fingerprint: **verify/reuse**. Any changed model/config/code/base/tests: **new Run-ID**. If an existing branch or output has conflicting data, **stop**, never reset/force push. Three seeds must remain distinct. Neither task checkboxes nor frozen task files are ever edited to record progress.

## Preflight checks (not a benchmark launch)

```bash
git rev-parse benchmark/base-v1
git rev-parse HEAD
git status --porcelain
python3 -B tools/verify_scaffold.py
python3 -B -m unittest discover -s tests -p 'test_scaffold.py'
python3 -B -m unittest discover -s tests -p 'test_acceptance.py'
```

Acceptance is **expected to fail on the untouched candidate**. Confirm container and model endpoint isolation externally. No evaluation success is implied by this documentation.
