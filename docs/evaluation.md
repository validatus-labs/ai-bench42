# Trial protocol

Each model starts from the identical full `benchmark/base-v1` commit SHA, with
[budget.json](../config/budget.json), TASKS.md and visible tests unchanged.
Three independent runs are mandatory; preserve every failure, no best-run-only
reporting. Record model checkpoint/quantization, tokenizer/chat-template hashes,
server options, decoding parameters, agent version, tools, token/time budgets,
seed, Run-ID and final commit/tree hashes. Do not claim deterministic model output.

Separate metrics: serving performance; IFEval/MMLU-Pro/BBH; coding/tool calling;
Melusine correctness and authorized-removal safety. Compare code quality and
architecture independently; equal function is not equal source code.

Git branches/worktrees isolate edits, not access. Before any candidate trial,
use a dedicated unprivileged sandbox with only its checkout, scratch output and
allowlisted model/tool access. Deny reference/corpus/Gold/other trials, shared Git
object stores, host HOME and GitHub credentials. Pin allowed network sources;
block reference/API retrieval. Evaluator runs separately with held-out data.
No agent trial is READY until these isolation checks actually pass.

Worktree preparation must refuse an existing changed checkout and require the
recorded base SHA. Repeating preparation verifies the same state; it must never
reset/delete unexpected work. Freeze candidate results before independent scoring.
No rollback or container isolation is claimed by the existence of this scaffold.

Current state: starter only. Reference freeze, Gold qualification, trial isolation
and hidden evaluator are pending. No candidate run or completed phase is claimed.
