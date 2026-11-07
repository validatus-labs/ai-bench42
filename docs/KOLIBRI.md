# Run the Kolibri benchmark

Kolibri can be evaluated on its own. Mistral, GLM and Qwen are optional later
comparisons, not release prerequisites. Keep four separate questions: speed,
answer quality, tool use and delivery of the complete Melusense parser.

The standard-library coordinator uses the existing host-local vLLM endpoint.
It never installs software, restarts a model or sends prompts to a hosted API.
Run as the existing normal account on the Spark, with Python 3.10 or newer.

Before live measurements, check the downloaded coordinator package with Python3.12:

```bash
python3 -B scripts/verify-package.py --output build/package-acceptance
```

This runs all coordinator suites in separate processes, retains their logs and
reuses only a hash-matching completed receipt. It includes the formerly omitted
legacy compatibility inputs. Legacy `config/benchmark.json` and its seeds41/42/43
are retained for those older entrypoints; the active Kolibri profile uses1/2/3.
The intentionally empty parser is not declared correct by package acceptance.
Native localhost socket access is needed for the test fixtures.

```bash
# Validate inputs and describe scope; no model request.
python3 -B scripts/kolibri-benchmark.py plan

# Small live transport check: one speed request, two answer tasks,
# one actual tool call plus a follow-up model response. No coding trial.
python3 -B scripts/kolibri-benchmark.py run --run-id kolibri-smoke-001 --smoke

# Collect the pinned P1-P3 diagnostics and delegate configured real P4.
python3 -B scripts/kolibri-benchmark.py run --run-id kolibri-001

# Verify retained evidence; no model or metadata requests.
python3 -B scripts/kolibri-benchmark.py verify --run-id kolibri-001
```

Read `build/kolibri-benchmark/kolibri-001/report.md` and `report.json`.
Exact requests, model responses, tool results, timings and hashes remain private
in the same run directory. A low answer score is still a measured result.
Exit 0 means requested execution completed, not that model quality is high.
An incomplete or missing dimension returns exit 2 and an explicit partial report.

## What is measured

| Dimension | Fixed protocol | Interpretation |
|---|---|---|
| P1 speed | Streaming requests, concurrency 1/2/4, three repetitions; server-reported token counts | TTFT and end-to-end tokens/second, not isolated GPU decode or cold-cache capacity |
| P2 answer quality | Eight synthetic exact-answer/JSON tasks, seeds 1/2/3 | 24 observations covering instructions, arithmetic, extraction, German, evidence, untrusted text and logs |
| P3 tool use | Three allowlisted pure tools, seeds 1/2/3 | Nine genuine model-to-tool-to-model round-trips; tool arguments and final answers checked |
| P4 coding | Existing isolated Kilo/Melusense controller, seeds 1/2/3 | The actual challenge, readiness gates, visible tests and independent evaluator; never replaced by a toy coding question |

P1-P3 are **diagnostics**, not NVIDIA AIPerf, IFEval, MMLU-Pro, BBH, BFCL or
SWE-bench leaderboard results. The opaque lookup tool tests whether the model
uses feedback instead of guessing. A successful pure-tool test does not prove
browser MCP access or Kilo worker isolation. The configured 262,144 context is
verified against the API; these short prompts do not test 256K retrieval quality.
Sampling and output ceilings are retained exactly. Truncated quality answers
fail rather than receiving extra tokens or an unreported retry. The server's
existing reasoning defaults apply; no reasoning-effort or calibration change
is silently sent. Calibration/weight provenance requires separate pinned evidence.

## Connect the real coding challenge

The shipped [profile](../config/kolibri-benchmark.json) has `coding_config: null`.
This deliberately produces **BLOCKED** for P4; it is not a completed four-phase
result. Prepare the actual qualified coordinator profile following
[the full pipeline guide](PIPELINE.md), then copy the diagnostic profile into
private `build/coordinator/kolibri.json` and set:

```json
"coding_config": {
  "path": "/absolute/private/path/to/coding-coordinator.json",
  "sha256": "the-actual-64-character-SHA256-of-that-file"
}
```

Use `--config build/coordinator/kolibri.json` with every command for that Run-ID.
The coding coordinator must have `deployment.enabled: false`, all its standard
suite `enabled` flags false, the same model/context and approved TRAIN/source/
toolchain pins. Its existing C00 and evaluator gates remain binding. This avoids
reinstalling the model or repeating P1-P3. Missing TRAIN rights, actual visible
Kilo attachment or independent worker isolation cannot be replaced by a boolean
claim. Preserve reports outside the blind assignment. Missing qualified Gold
means held-out accuracy remains unmeasured.

Future coding profiles default to `coding.elapsed_only: true`. The effective
candidate wall/CPU limit is recorded as null, without changing the archived
numeric task budget. Other resource, transport, token and tool limits remain.
Historical runs retain their own recorded policies.

An existing owned vLLM installation can be registered without redeployment:

```bash
python3 -B scripts/deploy/adopt-existing.py --runtime-root /actual/runtime \
  --source-package /actual/existing/dgx-spark-vllm
# Inspect the plan, then repeat with --apply to register its sealed source copy.
```

Paths above are placeholders: use the actual existing installation. The helper
checks the source's own deployment/profile, account, calibration manifest and
live PID. Conflicts are preserved. Repeating a matching adoption keeps registry
bytes and mtimes, and bootstrap model reuse issues no service command.

## Repetition and interruption

Each Run-ID binds the complete profile, task definitions, controller hashes
and observed backend identity. Before a request leaves, its case is marked
`RUNNING`. Results and all their evidence files are hashed after completion.
Repeating a completed run verifies and reuses it with **zero model requests**,
even if the old model process has since stopped. A clean partial checkpoint
continues only pending cases and requires the same backend instance. An
uncertain in-flight request is never replayed automatically. Retain it and
investigate before assigning a new trial ID. Changed inputs require a new ID.

`--smoke` is a different input fingerprint and must not share a full-run ID.
Individual connect/idle/request bounds remain enforced. These diagnostics do
not introduce a total wall deadline for the separately managed coding trial.

The existing [full controller](PIPELINE.md) remains available for official
standard-suite adapters. Publish a concise reviewed interpretation, not private
raw prompts, mail data, file paths or host identities.

## Package acceptance and native updates

The complete coordinator check now includes bootstrap adoption, monitoring,
scoring adapters, interrupted-run recovery and subprocess cleanup. It does not
run the deliberately failing starter-parser acceptance tests as if they should
already pass. A second identical invocation verifies and reuses its logs.

After an APT browser/Node update, old hash-bound proofs become stale. Use
[scripts/deploy/requalify-existing.py](../scripts/deploy/requalify-existing.py)
with a reviewed JSON profile containing the exact observed native hashes, a new
`browser_runtime`, a new `destination_runtime` and the preserved `controller_source`.
`inspect` is read-only; `apply` creates private launcher/registration files and
executes a real sandbox/MCP proof; `verify` checks the retained evidence. Repeat
`apply` with identical inputs returns `UNCHANGED`. No browser/npm installation,
model generation, model restart or historical-registry overwrite is involved.
The launcher uses `--sandbox --headless --isolated --block-service-workers`.
This host proof does not qualify an isolated coding worker.

Optional suites may be explicitly disabled in a **new** experiment profile.
`NOT_REQUESTED` is shown as excluded, while unavailable requested evaluation
remains `BLOCKED`/`NOT_EVALUATED`. Disabling coding reads no private TRAIN bundle
and supplies no coding/held-out score. Never present a completed selected-suite
smoke run as completion of the full four-phase benchmark.
