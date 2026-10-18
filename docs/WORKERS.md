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

The launcher uses Linux **bubblewrap**, with separate user, PID, network, IPC,
UTS and cgroup namespaces. It drops capabilities, disables nested user
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

1. Linux with working unprivileged bubblewrap namespaces. No sudo fallback is
   attempted when kernel, container or AppArmor policy denies them.
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
A lost controller kills its bubblewrap child. The launcher does not install
a systemd service or resume a half-finished candidate after reboot.

When artifact pins refer to managed `tools/toolchains/releases/<id>/` paths,
the outer launcher and C00 checker acquire that store's shared benchmark and
activity leases. The benchmark lease prevents automatic acquisition/builds;
the activity lease prevents model canaries during the worker's lifetime.
Independent tool/model consumers should use the
[update guide's lease wrapper](../scripts/deploy/UPDATES-README.md#separate-prepare-qualification-and-promotion).

No live worker was qualified during this implementation. A filled template or
successful `--help` is not a C00 result.

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
