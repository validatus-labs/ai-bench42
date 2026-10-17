# Melusense Rule-First Coding Benchmark

**Fresh benchmark assignment — NOT STARTED.** All tasks are open and no candidate implementations or scores are claimed for this baseline.

**Start:** [TASKS.md](TASKS.md) (ASCII parser architecture and complete unchecked assignment), [MANIFEST.md](MANIFEST.md), [AGENTS.md](AGENTS.md), [API contract](docs/contract.md), [Evaluation rules](docs/evaluation.md), [Budget](config/budget.json).

## Purpose

Three coding models (Kolibri, Mistral, Qwen) independently implement the same deterministic, multilingual email-structure parser from an unimplemented Python starter. We compare **code quality, functionality, safety, efficiency, reproducibility and total generated tokens**; general serving/reasoning/tool-call metrics remain separate phases.

Rule-based parsing remains useful even when an LLM provides higher-level document understanding: recognized MIME/header/quote structures can be extracted without generative inference. The proposed benefit—fewer LLM calls and higher determinism—must be verified empirically. This project is a *coding-agent benchmark*, not a document AI deployment.

## What is and is not here

- **Included:** immutable task, four-phase plan, bounded API safety contract, artificial fixtures, deliberately unimplemented `melusense/api.py`, visible tests and scaffold verifier.
- **Excluded:** working reference parser, private corpus and Gold, model-classifier checkpoints, successful benchmark run claims, raw mail, agent output and private credentials.
- **No trained FN classifier or LLM inference** in the target parser. No authorized content removal.

## Baselines and idempotence

`benchmark/base-v2` is the new candidate starting snapshot; **record the exact commit SHA from Git** before running. Historic `benchmark/base-v1` remains preserved and must never be retargeted. The coordinator must freeze equal inputs, tools, seeds and budgets and isolate each coding agent from solutions and private Gold. Repeating preparation with identical state verifies/reuses the same run; changing any material input requires a new run identity.

To inspect the untouched starter locally (Python 3.12+):

```bash
python3 -B tools/verify_scaffold.py
python3 -B -m unittest discover -s tests -p 'test_scaffold.py'
python3 -B -m unittest discover -s tests -p 'test_acceptance.py'
```

**Expected clean-start behavior:** scaffold checks PASS, acceptance tests FAIL because the parser is intentionally unimplemented. This is not a completed model trial. Progress is recorded in separate `build/` reports, **never by ticking frozen TASKS.md**.

Old analysis and earlier setup reports remain in historical Git commits, **not part of this new benchmark's results**.
