# Isolated workers: prepare, qualify, run

This guide covers `tools/worker.py`, `tools/preflight.py` and
`config/toolchain.json`. These coordinator tools prepare one isolated Kilo
coding trial. The [host bootstrap](../scripts/deploy/README.md) installs
serving/browser prerequisites; it does not launch a coding trial.

## Isolation and acceptance

```text
Coordinator host                              Worker namespace
|-- approved source archive  --selected copy-> /workspace (read-only)
|-- approved TRAIN bundle -------------------> /workspace/build/hpi-train-visible.jsonl (read-only)
|-- pinned, clean runtime image -------------> / (read-only)
|-- inference Unix broker -------------------> /run/inference.sock -> loopback HTTP :18080
|-- isolated browser MCP broker -------------> /run/browser.sock -> MCP stdio adapter
|-- run.json, C00 evidence, logs               /workspace/melusense/ (writable)
|   and readiness.json (never mounted)         /workspace/tests/ (new tests writable;
|                                                               originals read-only)
`-- other runs, home, Git, Gold (not mounted)   /workspace/build/ (writable outputs)
```

The launcher supports an explicitly selected native namespace constructor and
a legacy bubblewrap backend. Both require separate user, PID, mount, network,
IPC, UTS and cgroup namespaces. The native backend never falls back to bubblewrap. It drops capabilities, disables nested user
namespaces, clears inherited environment variables and supplies a fresh
temporary home. Direct host/LAN/Internet networking is unavailable. No host
`/usr`, `/etc`, home or repository root is mounted: binaries and libraries come
from the pinned runtime image. Original fixture/test files are individual
read-only mounts; candidates can add tests. Task files/configuration stay read-only.

Acceptance requires fresh denial probes, matching package/tool/model/TRAIN
identities, a real model-issued browser canary and independent verification
of both channels. Missing pins, unsupported namespaces or failed/absent checks
produce `BLOCKED`. Isolation-only success is **not READY**.

## Target prerequisites

The repository supplies the launcher and gate, **not a prequalified runtime
image or public-web gateway**. Provision these inputs on the actual target:

1. Linux with reviewed native namespace support (see below), or the legacy
   unprivileged bubblewrap backend. Selection must be explicit. A denied legacy
   backend never automatically switches to sudo or weakens host policy.
2. A reviewed, credential-free runtime rootfs containing `/usr/bin/python3`,
   the pinned Kilo executable and its libraries. Build it from reviewed runtime
   image/package sources, not a personal home or host-root copy. Remove
   setuid/setgid bits from this dedicated image. Devices, sockets and escaping
   links are refused by the inventory. Include no credentials, Gold or other trials.
3. Two **separate coordinator-managed Unix services**: a scoped local-inference
   broker and an externally isolated browser MCP broker. The browser must not
   access host home or candidate correspondence. A personal browser is unsuitable.
4. A reviewed, executable channel qualification adapter for the actual broker
   implementation and Kilo event format. Its contract is below.
5. The approved HPI TRAIN bundle and its original rights-review record.

The inference broker accepts HTTP/1.x over Unix, including streaming responses.
It must restrict methods, paths, model and backend; retain API keys outside
the worker; and enforce total output/tool/turn budgets for this Run-ID. The
worker's private loopback listener only relays to that socket.

The browser socket uses MCP JSON-lines, with an independent session per
connection. Kilo invokes this in-worker stdio adapter:

```text
/usr/bin/python3 /opt/modelbench/worker_inner.py mcp
```

The adapter relays MCP; the external service must enforce the runbook's DNS,
redirect, IPv4/IPv6, read-only, service-worker and host-file rules. The existing
bootstrap's stdio Brave launcher alone does not prove those controls or supply
these Unix services. It is not automatically adopted.

## 1. Fill a private toolchain configuration

From the repository root:

```bash
mkdir -p build/coordinator
chmod 700 build/coordinator
cp config/toolchain.json build/coordinator/toolchain.json
chmod 600 build/coordinator/toolchain.json
```

Edit the copy with actual paths, hashes, model/backend identity and argument
arrays. The checked-in JSON is a template: **null pins cannot pass C00**.
Use `sha256sum /actual/file` for regular artifacts and this for the rootfs:

```bash
python3 -B tools/worker.py hash-rootfs /absolute/path/to/clean-rootfs
```

The tree hash covers bytes, modes and link targets without following directory
links. Recheck after any image change. Artifact paths must identify real files,
not host symlinks. The entire runtime, Kilo configuration and instruction set
must remain identical across compared models, except explicitly recorded model
selection and seed.

`agent.argv` and `agent.canary_argv` are literal argument arrays for your pinned
Kilo version. Their first argument is an absolute executable path **inside the
rootfs**. Each must contain exactly one literal `{prompt}` argument, replaced
without a shell by the common assignment or canary. Select the Code agent and
local model explicitly; no hosted fallback or interactive picker.

Each `agent.config_files` entry has `path`, `sha256` and `destination` below
`/home/worker/.config/kilo/`. These files are read-only. Configure only the
selected provider and browser MCP using the schema accepted by your Kilo build.
The provider base URL inside the worker is `http://127.0.0.1:18080/v1`; keys stay
outside. Custom environment keys are limited to `KILO_` and `MODELBENCH_` and
cannot override sandbox identity/transport variables.

For each channel, record the socket path, server UID, executable SHA-256 and
SHA-256 of its exact `/proc/<server-pid>/cmdline` bytes. Preflight obtains the
live peer with `SO_PEERCRED`. The independent adapter also verifies the broker's
loaded policy/configuration/dependencies; hashing Python/Node alone cannot
identify the program they run.

```bash
python3 -B tools/worker.py check-toolchain --toolchain build/coordinator/toolchain.json
```

`PINS_VALID_NOT_READY` confirms local pins only, not working channels or C00.

## 2. Prepare one model and seed

Use the reviewed [source package](QUICKSTART.md#3-make-and-check-the-git-free-package)
and [HPI bundle](HPI_TRAIN.md). Replace the placeholders with recorded values:

```bash
python3 -B tools/worker.py prepare \
  --run-id K42-1 \
  --source-sha FULL_40_CHARACTER_COMMIT_SHA \
  --package /absolute/path/source.tar \
  --package-sha256 PACKAGE_SHA256 \
  --train-bundle /private/hpi-train-visible.jsonl \
  --train-sha256 TRAIN_BUNDLE_SHA256 \
  --rights-record /private/hpi-rights.json \
  --approve-worker-disclosure \
  --toolchain build/coordinator/toolchain.json \
  --model EXACT_SERVED_MODEL_ID --seed 1
```

The archive must contain repository files at its root, as `git archive`
produces. Traversal/absolute paths, links, special files, duplicate selected
paths and oversized input are refused. Only assignment files/directories are
copied; host deployment scripts and outer evidence are excluded. TRAIN count
and seeds come from the pinned package budget. Rights-review details stay on
the coordinator; only the approval hash and TRAIN bundle enter the run identity.

Preparation publishes `build/runs/K42-1/` atomically without overwriting a
concurrent run. Identical inputs verify/reuse it; changed inputs need a new
Run-ID. Before C01, candidate source must still match the prepared package.

## 3. Inspect, qualify, then start

```bash
python3 -B tools/worker.py plan \
  --run build/runs/K42-1 --toolchain build/coordinator/toolchain.json

python3 -B tools/worker.py probe \
  --run build/runs/K42-1 --toolchain build/coordinator/toolchain.json

python3 -B tools/preflight.py \
  --run build/runs/K42-1 --toolchain build/coordinator/toolchain.json

python3 -B tools/worker.py run \
  --run build/runs/K42-1 --toolchain build/coordinator/toolchain.json
```

Use the persistent execution session for remote work. `probe` checks isolated
mounts, read-only inputs, writable candidate storage, separate PID/network
namespaces, denied connections and a synthetic host-only marker. It reads no
protected Gold or credential contents. IPv4 probes cover loopback, private,
metadata and a documentation address; IPv6 includes loopback. Browser
DNS/redirect/IPv6 controls require the separate C00 checks.

Preflight starts the **actual Kilo/model** in the sandbox and asks it to read
a fresh `data:` page marker through browser MCP and close the page. Canary
source/test mounts are read-only; C01 permits candidate edits and new tests.
The channel adapter must validate real model-issued tool calls and broker
traces, not just a marker repeated in assistant text.

READY lasts **15 minutes**, bound to this boot, input fingerprint, preflight
version, evidence hashes and broker processes. Launch verifies it again and
runs another isolation probe. Requalification archives the previous decision;
a failure cannot leave old READY active. Once a candidate starts, this Run-ID
cannot silently start it again. Inspect retained evidence or create a new run.

## Channel qualification adapter contract

`qualification.path` names a reviewed, hash-pinned coordinator executable,
not a candidate script. Preflight sends one JSON request on stdin: Run-ID,
fingerprint, fresh challenge, actual canary transcript path/hash, exact model,
budget, peers, artifacts, policy, private `evidence_directory` and
`required_checks`. The adapter performs the checks for its implementation,
writes bounded evidence files there and returns **one JSON object on stdout**.

The returned object requires `schema_version: 1`, `status: "PASS"`, exactly
the request's `fingerprint`, `challenge`, `canary_sha256` and complete `model`
object, plus `checks`. Every name from `required_checks` must map to:

```json
{"passed": true, "evidence_file": "relative-report.json", "sha256": "ACTUAL_REPORT_SHA256"}
```

This illustrates the schema, not usable evidence. Checks may share a genuine
report. Every evidence file must be private, coordinator-owned, within the
attempt directory and match its hash. A booleans file is not a substitute for
an adapter that inspects live controls and the actual transcript.

The complete set is defined in [preflight.py](../tools/preflight.py): tool
identities/schema; headless/sandbox/profile/service-worker behavior;
upload/download/auth denial; public HTTPS and private/DNS/redirect/IPv6
controls; browser host-file denial; scoped local inference/backend; enforced
budgets; genuine model-issued marker and page-close calls. Missing or
unsupported observations must fail.

No provider-specific adapter is bundled: neither the checkout nor the imported
bootstrap establishes a fully qualified external browser-egress boundary.
Provision and review the adapter for the actual gateway. Do not substitute an
always-PASS script or mark a generic browser ping as qualification.

## Records and limits

```text
tools/
|-- worker.py                    # Outer prepare/launch/namespace controller
|-- worker_inner.py              # In-namespace probe and channel adapters
`-- preflight.py                 # C00 orchestration and evidence validation

build/runs/K42-1/
|-- run.json                     # Immutable input and frozen-file identities
|-- workspace/                   # Only candidate source/data mount
|-- c00-<attempt>/               # Private isolation/canary/channel evidence
|-- readiness.json               # Latest successful, short-lived C00 decision
|-- candidate-start.json         # Prevent silent duplicate execution
|-- candidate.log                # Private harness output, not a public report
`-- candidate-result.json        # Exit code, not evaluator PASS
```

Evidence stays outside worker mounts and ignored by Git. Export only reviewed,
redacted summaries. Limits cover wall time, address space, output-file size,
open files, processes and CPU time; they are not cgroup resource reservations.
The process rlimit also depends on other processes of the same host UID.
Token/turn/tool budgets require broker/harness enforcement and adapter proof.
A lost controller kills its namespace child. The launcher does not install
a systemd service or resume a half-finished candidate after reboot.

When artifact pins refer to managed `tools/toolchains/releases/<id>/` paths,
the outer launcher and C00 checker acquire that store's shared benchmark and
activity leases. The benchmark lease prevents automatic acquisition/builds;
the activity lease prevents model canaries during the worker's lifetime.
Independent tool/model consumers should use the
[update guide's lease wrapper](../scripts/deploy/UPDATES-README.md#separate-prepare-qualification-and-promotion).

A native synthetic inspection passed the namespace probes on the target Spark.
This is infrastructure evidence only: neither that inspection nor a filled
template, successful `--help` or Kilo health response is a C00 result.

## Freeze and run visible acceptance

After candidate execution, the coordinator can freeze and assess the result:

```bash
python3 -B tools/worker.py freeze --run build/runs/K42-1 --toolchain build/coordinator/toolchain.json
python3 -B tools/worker.py verify-candidate --run build/runs/K42-1 --toolchain build/coordinator/toolchain.json
```

The freeze stores candidate/test file hashes and a private deterministic tar
archive outside the worker. Assessment mounts code/tests/build read-only in a
fresh namespace with no inference/browser sockets or Kilo configuration.
It runs the four supplied test suites plus candidate test files, preserving
counts, failures, errors and skips. Empty/skipped/expected-failure suites do
not count as acceptance. A matching completed assessment is hash-checked and
reused, not rerun. It is visible synthetic evidence, not held-out accuracy.
Changed code, source, launcher or evidence requires a new Run-ID.

The [experiment controller](PIPELINE.md) invokes preparation, C00, execution,
freeze and assessment for all three seeds and binds independent evaluator
results to each frozen candidate's hash.


## Native Spark backend and reconnectable inspection

```text
tools/native_runtime.py       existing pinned public binaries -> sealed clean rootfs
tools/native_namespace.py     bounded sudo constructor -> private namespaces -> nonroot
tools/native_gui.py backend   owned systemd unit -> persistent isolated Kilo server
tools/native_gui.py attach    actual VS Code extension -> authenticated private UI
                             (closing the view preserves the backend)
```

The native constructor is an explicit coordinator privilege boundary, not an
unprivileged sandbox claim. It requires pre-existing noninteractive sudo and
reviewed hash-pinned source. It sets up namespaces and mounts, then drops all
capabilities, enforces no-new-privileges, denies nested namespace syscalls and
runs the worker as the normal account. It installs no AppArmor profile, SUID
helper, package or global setting. Never run an unreviewed worker-owned constructor.

Build using native Python3.12 and a private JSON profile with exactly
`schema_version: 1`, `python`, `node`, `kilo` and `ripgrep`. Each artifact is an
existing executable with `path` and `sha256`. No home, previous agent state or
user Python startup hook enters the runtime:

```bash
python3.12 -B tools/native_runtime.py \
  --profile /private/reviewed-runtime.json \
  --destination /private/new-sealed-runtime
```

An identical repeat checks the full byte/mode inventory and reuses it. Changed
inputs or partial builds fail closed and require a fresh destination. This is
an execution substrate, not a blank-host installer or readiness certificate.

For `tools/worker.py`, add a reviewed private `native_namespace` object with
`constructor` and `python` artifact pins, plus the actual nonroot `uid`/`gid`.
The constructor path must be this checkout's `tools/native_namespace.py`.
The rootfs path remains `rootfs.path`; the complete rootfs hash remains mandatory.
GUI inspection additionally pins `gui_inner` to `tools/native_gui_inner.py`.

`native_gui.py` supports **INSPECTION_NO_INFERENCE** plus the separately bounded
**C00_SCHEMA_CAPTURE** and **C00_TOOL_CANARY** diagnostic modes. It has no C01
mode. Its private
settings bind the rootfs tree, sources, provider configuration, run record and
run identity. The actual extension launches `attach --configuration PATH` with
its ephemeral UI credential; it is not an interactive shell command. The owned
backend starts once under systemd. Reattaching verifies the existing invocation;
a stopped, changed or uncertain backend never restarts automatically. Inspection
expires after 900 seconds; this is a qualification cap, not a coding time limit.
No candidate request is authorized, no inference socket is supplied and MCP is
not enabled. Do not relabel this as a completed model-to-tool integration.

The synthetic Spark inspection used installed Kilo7.8.17 and passed all13
namespace/filesystem/network denial checks in its persistent process. Its actual
VS Code viewer attached; closing and reopening the view preserved the backend
invocation and receipt. The extension's Git/worktree helpers emit harmless
warnings because the assignment is deliberately Git-free; adding Git history to
silence them would defeat the assignment boundary. These observations do not
qualify the browser gateway, TRAIN access, full coding trial or hidden scoring.


The reusable inspection preparer accepts one private JSON profile and never
starts a service or model request:

```bash
python3.12 -B tools/native_inspection.py --profile /private/inspection-profile.json
```

Its exact profile fields are `schema_version: 1`, `run_id`, `destination`,
`rootfs`, `rootfs_tree_sha256`, the `python` artifact pin, `extension` and
`extension_tree_sha256`. Both tree hashes use `tools/worker.py hash-rootfs`.
The extension must be an already installed Kilo Code release. Preparation copies
its public files into a separate derived UI, verifies the original full tree,
changes only the launch/shim metadata and seals the complete derived tree.
It creates synthetic markers only: no real TRAIN, assignment or inference socket.
An identical repeat preserves sealed bytes/mtimes; drift and partial preparation
are retained and rejected. Closing or reattaching a view is separate from
preparation and never turns inspection into a candidate trial.

## Scoped native browser and inference channels

`tools/native_browser.py --profile FILE` runs a separate offline Brave/MCP
namespace using sealed copies of the existing browser and npm assets. Its only
tools are navigate, snapshot and tab list/close. Research uses the pinned public
snapshot catalog; the browser has no direct host network or candidate/TRAIN
mount. Service Workers and downloads are disabled. Chromium's own user-namespace
sandbox remains enabled; no new host AppArmor or sysctl rule is installed.
The browser's private proc permits its own UID/GID mapping writes; global proc
controls remain read-only/masked. The worker's separate proc remains read-only.

The tools-only virtual MCP server strips client capabilities before forwarding
initialization, so browser MCP cannot request worker roots. It supports bounded
cancellation notifications; synchronous tool work remains bounded by its
120-second response deadline. Established diagnostic channels allow 900 seconds
of idle model reasoning; initial admission is 30 seconds. Auto-named snapshot
YAML files are returned as bounded inline text after no-follow, regular-file,
single-link, owner, size and stable-stat checks. Arbitrary file output is denied.

`tools/inference_transport.py host --policy FILE --directory PRIVATE_DIR` exposes
only POST `/v1/chat/completions` through a private Unix socket to fixed host-local
Kolibri. Exact model, sampling, output limits and tool schemas are checked;
streaming usage and tool counts are retained. Incomplete requests stay uncertain
and are never silently replayed. Inner UI and inference header parsing have
accepted-socket deadlines. These channels are not a general HTTP proxy.

On 6 November, the current visible Kilo worker completed actual model-issued
navigate, DOM snapshot and tab-close calls. Independent review accepted that
integration sub-proof. A fourth final-answer request outlasted the diagnostic
service lifetime and retained uncertain usage; do not call the entire run cleanly
completed or full C00 accepted. The model server remained unchanged and idle
after the bounded qualification services expired. Future qualification should
stop at the required tool proof and use a smaller declared diagnostic output
budget; the coding budget and 262144-token context remain separate.

## Outcome-free assignment export

```bash
python3.12 -B tools/assignment.py --source /path/to/coordinator-checkout \
  --source-sha EXACT_APPROVED_40_CHARACTER_SHA --output /private/new-assignment
```

The exporter uses an explicit allowlist and compares every copied task, prompt,
API, test and budget byte against the exact source commit. It derives only
candidate navigation, coordinator-operation placeholders and two runbook links;
the receipt records these changes. The original prompt's conflicting final
write-scope sentence is explicitly clarified: implementation under `melusense/`,
added tests under `tests/`, progress artifacts under `build/`. Frozen inputs stay
unchanged. This supplies no solution or prior model result.

The deterministic Git-free archive passes the scaffold checks and records
expected failures of its empty parser. Identical repeats preserve the archive
and verify all logs; changed inputs or altered evidence require a new destination.
Preparation is `PREPARED_NOT_READY`, not a new freeze or candidate authorization.


## Prepared native session and bounded visible canary

[Native session controller](../tools/native_session.py) provides `inspect`,
`prepare`, `start`, `status` and `stop` with a private, explicitly pinned JSON
profile. It seals the current outcome-free assignment, approved TRAIN rights/data,
original and derived extension, runtime, ten actual Kilo/MCP schema identities,
model identity and future exact channel command lines before starting services.
Identical preparation verifies the existing receipt and preserves its files;
partial or divergent states are retained and never automatically replayed.

The owned coordinator holds the exclusive benchmark lease through cleanup and
checks actual model-idle gauges before launch. Its channels and separately bound
Kilo backend have no total coding wall deadline. Existing token/tool/resource and
per-operation limits remain. Shutdown targets only verified owned invocations;
stop/status continue to work after original installation files change. Failed
cleanup remains failed, with no success receipt.

[Browser controls](../tools/native_controls.py) run before GUI attachment through
the same scoped MCP broker. The successful Spark control observed a pinned RFC
snapshot, seven forbidden URL rejections, local-page IPv4/IPv6/DNS fetch failures,
nine namespace checks and tab closure. Service-worker/download blocking remains
explicit effective-configuration evidence. Redirect-query denial is not a live
redirect or rebinding exercise. Renderer filters are checked on actual renderer
processes; browser/zygote privileges are recorded separately.

A real RFC-page crash exposed missing fonts in the initial minimal runtime.
[Runtime builder](../tools/native_runtime.py) can now copy three explicitly pinned,
already installed DejaVu TTFs and generate a minimal private font configuration.
No package installation or host security modification is involved. Historical
fontless runtimes and failed controls remain unchanged.

[Visible canary collector](../tools/native_visible.py) requires an actual dedicated
VS Code attachment and submits once, then polls the same session. It correlates
three ordered model-issued browser calls with raw MCP arguments/output and the
shared usage ledger. The gateway permits only three qualification generations,
with an explicit 2048-token output cap, before any readiness decision; a fourth
is refused before reservation. Qualification counts toward the unchanged shared
coding ceilings. This collector cannot write READY or start C01. Full current
native readiness/evaluator wiring remains required before a coding trial.

### Native readiness and visible candidate continuation

The external [readiness adapter](../tools/native_readiness.py) consumes the sealed
worker's completed model-to-MCP proof, current unit/model/channel identities and
21 explicitly mapped checks. `inspect` captures evidence without new inference.
`promote` requires an independent review bound to the exact index hash; it writes
immutable receipts and publishes the inference gate last. Identical repeats keep
all bytes, timestamps and the original qualification age. Partial conflicting
state is retained. Configuration-based SW/headless checks and offline-network
construction are distinguished from actual browser observations.

The external [candidate controller](../tools/native_candidate.py) uses that same
visible backend; it supplies the unchanged English assignment, existing scope
clarification and immutable inline run manifest. Only the seven pinned SDK tools
and three pinned browser tools are enabled. All other SDK tools are denied.
`start` submits once; repeated or interrupted submissions never replay. `status`
observes the same session. `watch --session-profile <original-profile>` measures
elapsed duration without a total wall deadline and invokes `finish` only when
idle and fully accounted. The original coordinator is stopped with verified
backend/channel cleanup before the candidate is frozen and visible tests run.
Those tests remain separate from qualified hidden/reference/Gold evaluation.

These controllers do not modify sealed workers or historical assignments. Their
source tests and independent reviews are prerequisites, not proof that a new
candidate has completed. Native pipeline integration must use explicit pinned
profiles and return pending/failed states rather than fall back to a CLI worker.

For an already submitted controller, a separately reviewed
[capture-only resume adapter](../tools/native_candidate_resume.py) can replace
only transcript capture while retaining the exact original controller and launch
identity. It has no start action. The current Kilo relay strips opaque pagination
headers, so the capture reads only the existing own-session message IDs through
read-only SQLite and fetches each body with the supported per-message API.
It never queries credential tables. Counts, per-response and total evidence sizes
remain bounded. Both source versions, adapter and independent review are pinned.

The [native pipeline branch](../scripts/modelbench/native_pipeline.py) binds
explicit per-seed prepared profiles, configurations and controller hashes.
A per-seed `resume_adapter` may supply separately pinned `controller` and `profile`
for observation/finish of an existing run. Start remains with its original
once-only controller. Pending calls return `AWAITING_NATIVE_CANDIDATE`; repeats
verify the prior sealed reference and continue observation without a new prompt.
The pipeline and native worker share the exact benchmark workload lock; ordinary
P1–P3 inference is refused during a native candidate. Existing independent C00,
approved TRAIN and visible attachment remain prerequisites. Missing other-seed
profiles are explicit blockers, never automatically qualified copies.

Visible tests alone never authorize full C01–C07 success. The native pipeline
waits for `independent-development-review.json` outside the worker workspace.
The review binds the exact candidate tree/archive, report and fingerprint;
acceptance additionally requires verified worker TRAIN checks and explicit
completion of the full task. Concrete review findings return FAILED. Missing
review returns DEVELOPMENT_REVIEW_REQUIRED, with the completed candidate reused.
A corrected assessment is separately pinned, including its namespace, raw result
and test log; later external evidence drift prevents completed-result reuse.

A script-path bug in the original read-only assessment omitted `/workspace` from
Python's import path. New worker helpers include that path explicitly. Historical
candidates retain their original helper and failed receipt; the independently
reviewed [assessment-only adapter](../tools/native_assessment.py) changes only the
entrypoint in the same read-only offline namespace. It can reuse corrected
results without running inference. [Supplemental probes](../tools/native_probe_payload.py)
check public synthetic contracts and approved TRAIN safety; these are neither
worker-completed C07 nor real-mail accuracy or Gold scores.
