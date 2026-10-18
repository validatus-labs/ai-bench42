# Updates and recovery: keep pins, publish a new toolchain

Pins describe one exact release. An update builds and checks **another**
release, then changes a small `active.json` pointer. It never edits an old
release's lockfile, browser binary or benchmark evidence.

This lifecycle covers **Brave + Node + Playwright/MCP and their full native/npm
dependency closure** on Ubuntu 24.04 ARM64. Model weights, vLLM, PyTorch,
CUDA/ROCm drivers and the parser assignment are not upgraded by this command.
The existing local model is used for the compatibility canary.

## Normal use, including six months from now

Run from the repository root as your normal account on the supported host:

```bash
# Refresh the already configured, trusted APT repositories if needed.
sudo apt update

# Resolve current versions and the complete npm dependency graph.
python3 -B scripts/bootstrap.py --check-updates

# Build a separate candidate, run the canaries and select it only on success.
python3 -B scripts/bootstrap.py --update

# Inspect the stable release and previous releases.
python3 -B scripts/toolchain.py status
```

Use the same `--runtime-root /absolute/path` as your installation when it is
custom. Put it before the action with `toolchain.py`. Long operations belong
in the persistent execution session. No sudo is used by the release builder.

`check` does not install/upgrade system packages or change the active release.
It may download/cache `.deb` files to construct its private resolver runtime,
and writes plans and a metadata-only npm lock. Both direct and transitive npm
updates are checked. Preparation uses exactly that resolved lock with `npm ci`,
not a second, potentially different resolution.

Fresh `--playwright --on` installations build a current qualified release when
none is active. Repeating component installation uses the selected release;
it does not implicitly move an existing installation to newer package versions.
Use `--update` or the automatic job to choose a newer release. When Kolibri and
Playwright are selected together, Kolibri is deployed first so the model
canary has a backend.

## What happens during an update

```text
APT package metadata + npm dist tags
                   |
                   v
Exact .deb versions/hashes + full resolved npm lock
                   |
                   v
Private, versioned runtime + cached recovery artifacts
                   |
                   v
Brave namespace/seccomp sandbox and visible marker
                   |
                   v
Real MCP initialize / tools / navigate / snapshot / close
                   |
                   v
Local model -> structured tool call -> actual MCP marker -> model answer
                   |
             all checks pass?
             |             |
            yes            no
             |             `--> retain failure evidence; keep previous stable
             v
Atomic active.json switch; old releases and sessions remain
```

The model canary makes **two inference requests**. The model must call a
function to obtain a fresh browser marker and then return the actual tool
result. The marker is not supplied in its original prompt. This is a real API
tool round-trip, not a canned successful response. A loading/unavailable model
is allowed to become ready within the configured timeout; wrong credentials,
alias or incompatible tool responses fail the candidate.

This proves host-toolchain compatibility. It does **not** qualify Kilo worker
isolation or public-web egress. Each scored worker still needs
[C00](../../docs/WORKERS.md), including the actual harness/model/broker trace.
The host-toolchain MCP runs in its own filesystem/PID namespace with fresh
home/profile, but shares host networking. It is not the benchmark's filtered
public-research gateway and never replaces that gateway automatically.

## Policy and trust

Settings are in [config/toolchain-updates.json](../../config/toolchain-updates.json).
They select the platform, APT runtime packages, npm dist tags, minimum Node
version, check interval, qualification age and local model endpoint. By default
the endpoint is `http://127.0.0.1:8000/v1`, model `kolibri-1`.

For manual operations, copy this file into private storage, edit it and use:

```bash
python3 -B scripts/toolchain.py --policy /private/toolchain-updates.json update
```

For the automatic service, set the desired source policy **before** installing
`--maintenance`; the installer copies it into the root-owned
`/etc/modelbench-toolchain-updates.json`. Reapplying the installer migrates
owned policy/code with backups. Unexpected manual drift is reported rather
than overwritten. Keep API-key values outside JSON/Git: `model_canary.auth_file`
can reference a private, account-owned key file. Only its path enters policy;
the key contents and authorization header are never archived or logged.

After updating the repository's **controller code**, reapply
`--maintenance --on` once to migrate the installed updater too. Manual and
scheduled controllers must use the same code generation; a mismatch stops
updates instead of letting an old service overwrite a newer selection. This
root installation is separate from routine, unprivileged package discovery.

APT selects from the administrator's configured trusted repositories. Each
download must match the SHA-256 in package metadata, package name, version and
architecture. The resolver includes the complete native dependency closure,
not just whichever libraries happen to be installed on this host. Maintainer
scripts are not executed: packages are extracted into the private runtime.

The selected Node package must include npm and meet the configured minimum;
the existing approved Node 22+ source remains a host prerequisite. Repository
key rotations and incompatible future Node major versions require an explicit
source/policy update. The updater never trusts an unknown key, adds an APT
origin or disables sandbox checks to make a candidate pass.

The npm resolver allows only the HTTPS npm registry, requires integrity values,
and disables lifecycle scripts and Playwright browser downloads. A direct
`latest` tag pointing to a prerelease is rejected. Exact transitive versions,
the npm cache and the installed modules are retained. A failed candidate is
reported, not silently replaced with another browser or package range.

## Automatic updates through maintenance

```bash
python3 -B scripts/bootstrap.py --maintenance --on
```

This installs the APT event hook and a systemd service/path/timer. The hook
only touches a root-owned pending marker after successful list updates or
dpkg transactions. Marker failures do not abort APT. The normal-user update
job waits for APT/dpkg locks to clear before doing its own work.

The updater runs at most once per configured interval, **24 hours** by default.
Failed scheduled checks may retry after one hour when another event arrives.
It also catches up five minutes after boot and daily at **06:00 UTC**
(Berlin: **07:00 in winter, 08:00 in summer**). A reboot bypasses the previous
boot's check throttle and renews the host qualification. Initial model
readiness is bounded by `model_canary.timeout_seconds` (default 20 minutes).

```bash
systemctl status modelbench-toolchain-update.path modelbench-toolchain-update.timer
journalctl -u modelbench-toolchain-update.service -n 100 --no-pager
```

The service executes a root-installed copy of the updater as the normal
account. It does not execute mutable checkout scripts as root. Root installs
only managed hook/service/code files, retaining backups and an interrupted
installation journal. Reapplying bootstrap completes a committed generation
or restores the previous generation before retrying. A pending native
transaction prevents the service from running mixed generations.

`--maintenance --off` stops/disables the updater service/path/timer alongside
the existing maintenance timers. Installed hooks and data remain; a marker
cannot start a job while its path/timer are disabled. Existing model and MCP
sessions are not stopped by the release controller.

## Separate prepare, qualification and promotion

```bash
python3 -B scripts/toolchain.py prepare
python3 -B scripts/toolchain.py qualify --release RELEASE_ID
python3 -B scripts/toolchain.py promote --release RELEASE_ID
```

Use the 64-character release ID printed by `prepare`. Setting
`automatic_promotion` to `false` leaves successful `update` candidates qualified
but inactive until an explicit `promote`.

Qualification is host/boot/controller/policy bound. Promotion and scheduled
renewal require evidence no older than 24 hours by default. Runtime MCP use
accepts an older successful receipt while boot, code, package epoch and sandbox
binary are unchanged, so a long session is not broken merely by the clock.
MCP startup never issues hidden inference requests. After an offline period, use
`qualify --release ID` to renew it without checking upstream versions.
Native package events and a changed bubblewrap binary also invalidate old
qualification. Those events bypass the normal daily throttle. Synthetic API
responses and MCP traces are retained privately with hashes for diagnosis.

Live MCP sessions hold a shared activity lease. Managed workers automatically
hold shared benchmark and activity leases when their pinned artifact paths
identify this release store. The benchmark lease blocks the whole automatic
update, including downloads/builds, during a timed worker run; qualification
also needs an exclusive activity lease. Busy workloads produce
`DEFERRED_ACTIVE_WORKLOAD` before any canary inference. Candidates and the old
stable release are retained. Close the workload, then rerun `--update`, or let
the next automatic window try again.

For another harness sharing the model, register its full lifetime explicitly:

```bash
python3 -B scripts/toolchain.py lease -- python3 -B tools/worker.py run \
  --run build/runs/K42-1 --toolchain build/coordinator/toolchain.json
```

Consumers outside this lease protocol cannot be discovered reliably from a
browser connection alone. Wrap those coordinator commands too, so background
canaries do not compete with their inference or evict their prefix cache.

The ordinary generated Kilo fragment selects `stable` **once per MCP process**.
Promotion affects subsequent processes; existing ones retain their namespace
and release. For a frozen comparison, export an explicit client and record its
release ID, schema/lock/binary hashes and the full worker toolchain config:

```bash
python3 -B scripts/toolchain.py client --release RELEASE_ID --output build/pinned-kilo-client.json
```

Do not let a scored run follow `stable`. The same fixed release must be used
by every compared model/seed. No existing C00 record is repinned automatically.

## Rollback and offline recovery

```bash
# Requalify the old retained release against this host/model, then select it.
python3 -B scripts/toolchain.py rollback --release OLD_RELEASE_ID
```

Rollback holds the replaced selection so the next automatic check cannot
immediately promote it again. A newer, different selection can still be
evaluated. To allow the held selection again explicitly:

```bash
python3 -B scripts/toolchain.py unhold --release HELD_RELEASE_ID
```

Export a toolchain recovery bundle into ignored local storage:

```bash
python3 -B scripts/toolchain.py export --release RELEASE_ID --output build/toolchain-recovery.tar.xz
```

Keep its printed SHA-256 through a trusted transfer path. This bundle contains
the runtime, original `.deb` packages, npm modules/lock/cache, controller source
and manifest. It contains no model weights, mailbox, Gold or API-key contents.
An exported toolchain is not the full benchmark source package.

On another matching platform, using the source package and configured local
model/key, restore without fetching APT or npm artifacts:

```bash
python3 -B scripts/toolchain.py restore --archive build/toolchain-recovery.tar.xz --sha256 ARCHIVE_SHA256
```

Restore verifies the archive and every retained entry, runs fresh host/model
qualification, then promotes. For import without activation, use `import`
instead. A checksum received only from the same untrusted archive is not
independent authenticity evidence. Use the trusted recorded export checksum.

Old recovery bundles preserve earlier environments; new comparisons should
use a currently qualified release. Releases, failed attempts and caches are
not automatically deleted because they may be evidence for frozen trials.
Storage exhaustion blocks preparation with the old stable intact. Export
retained releases to your backup storage as part of normal operations.

## Files and states

```text
scripts/
|-- bootstrap.py                         # --check-updates / --update shortcuts
|-- toolchain.py                         # Public lifecycle and recovery CLI
`-- deploy/
    |-- UPDATES-README.md                # This guide
    |-- toolchain_lifecycle.py           # Resolve/build/check/promote/archive
    |-- toolchain_canary.py              # MCP + real model/tool round-trip
    |-- toolchain_browser_probe.cjs      # Browser and renderer sandbox probe
    `-- toolchain_native.py              # Owned root hook/service installation

<runtime>/tools/toolchains/
|-- active.json                         # Atomic stable selection
|-- client.json                         # Normal-session MCP fragment
|-- held.json                           # Selections held after rollback
|-- plans/                              # Exact APT/npm graphs and release mapping
|-- resolvers/                          # Verified native resolver runtimes
|-- objects/                            # SHA-256-addressed .deb cache
|-- releases/<id>/                      # Retained complete release
|   |-- manifest.json
|   |-- rootfs/
|   |-- packages/
|   |-- npm/                            # package-lock.json + node_modules
|   |-- npm-cache/
|   `-- controller/                     # Source used to create this release
|-- qualifications/                     # Host/model proofs, separate from release
|-- attempts/                           # Staging and retained failures
|-- events/                             # Pointer change history
`-- sessions/                           # Per-process private output directories
```

Native paths are `/usr/local/libexec/modelbench-toolchains/`,
`/etc/modelbench-toolchain-updates.json`,
`/etc/apt/apt.conf.d/98modelbench-toolchain-events` and
`/var/lib/modelbench-toolchain-updates/`. Pending signals and interrupted
installation records contain no credentials.

This implementation has syntax/CLI/documentation checks. A live ARM64
acquisition, browser/model qualification, hook rollout and offline recovery
have not been executed in this workspace; no successful release is claimed.

Reference behavior: [APT hooks](https://manpages.debian.org/bookworm/apt/apt.conf.5.en.html),
[npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci/),
[Playwright MCP options](https://github.com/microsoft/playwright-mcp#configuration).
