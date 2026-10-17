# Evaluation and freeze contract — base-v2

**Status: NOT STARTED.** The coordinator pins the exact `benchmark/base-v2` SHA outside the frozen candidate tree. Old `benchmark/base-v1` and its results are not part of this new trial.

1. Verify the exact frozen tree, budget and fixture hashes before preparing trials. Any unexpected file, dirty checkout, changed SHA, wrong model, missing isolation or incompatible context must fail closed. An identical rerun checks/reuses the existing Run-ID; never reset/delete unexpected work.
2. Give each candidate the **same** task, contracts, tests, fixed starting SHA, tools, model gateway contract and budgets. Three independent seeds 41/42/43, with each worker in its own isolated unprivileged runtime. Branches and worktrees are not security boundaries.
3. Block worker access to reference implementation, comparator source, corpus/human Gold, hidden tests, other runs, shared Git objects, host HOME, Git credentials and unrelated network services.
4. Keep raw outputs and progress in isolated `build/`; include command exit codes, generated tokens, wall time, tool calls, memory, errors and all unsuccessful attempts. Never tick `TASKS.md`.
5. Candidate first runs scaffold integrity and records **expected initial acceptance failures**. It then implements `detect_text` and `detect_eml` without changing the visible contract and freezes its final source tree.
6. Only an independent evaluator may access rights-approved hidden HPI Gold after candidate freeze. Do not train or tune on EVAL/BLIND, invent human labels or publish private mail. Report TP/FP/FN/F1 per qualified set, exact-span accuracy, abstentions and `authorized_removals=[]`.
7. Evaluate implementation code quality, safety and runtime independently of general IFEval/MMLU-Pro/BBH, SWE-bench Verified, BFCL and serving performance. Equal functionality is not equal software-engineering quality.
8. Deterministic **procedure** does not imply deterministic LLM output. A repeated run must use the same inputs and separate immutable evidence; no best-run-only reporting.

No candidate trial has been executed for base-v2 at this clean start; no metric or platform readiness is inferred from earlier pilots.
