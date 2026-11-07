# Native Brave sandbox, versioned Playwright MCP updates

Keep native Brave/Node under APT and build each npm/MCP update separately.
This host updater uses **Brave --sandbox**, with no Bubblewrap, extra AppArmor
profile, SUID helper or sysctl change. It does not qualify a coding worker.

```text
native Brave + Node hashes + installed-package inventory
                      + exact npm dependency lock
                                  |
                       separate retained npm release
                                  |
                 real browser sandbox + MCP + model canary
                                  |
                      atomic stable pointer / no-op repeat
```

## Commands

Run as the ordinary account, with the same explicit project runtime:

```bash
python3 -B scripts/bootstrap.py --runtime-root /absolute/runtime --check-updates
python3 -B scripts/bootstrap.py --runtime-root /absolute/runtime --update
python3 -B scripts/toolchain.py --runtime-root /absolute/runtime status
```

`check` fetches npm metadata, resolves the complete dependency graph into a
private lock and records actual native identities; it does not upgrade APT
packages, install a candidate or switch the active pointer. `update` uses that
exact lock with `npm ci --ignore-scripts`. Browser downloads and npm lifecycle
scripts are disabled; package URLs must use the HTTPS npm registry and carry
SHA512 integrity. Direct and transitive versions are sealed, along with module
bytes, native Node/Brave hashes, npm's own tree and installed-package versions.

Brave stays at `/opt/brave.com/brave/brave`, using its existing Ubuntu security
attachment. Node stays at `/usr/bin/node`; the approved Node22+ package must
supply npm. Fresh headless profiles use `--isolated --sandbox` and blocked
Service Workers. A short private browser temporary root can be set through
`browser_temporary_root` in policy to respect Unix-domain-socket path limits.

## Qualification and selection

A candidate must show actual namespace/seccomp renderer sandbox state, a
local `data:` marker, real MCP initialize/tools/navigate/snapshot/close and a
local-model structured tool round trip. Each model canary makes two bounded
synthetic inference requests; it does not send mail, Gold or reference code.
Qualification binds boot, native binaries/package inventory, controller,
policy and actual MCP schema. No hosted fallback or model-server restart.

Only success can select a new `active.json`; failures retain candidate/logs and
the previous pointer. A matching repeated update keeps pointer bytes and mtime.
Model work respects both store activity leases and the configured external
benchmark lock. Unregistered GUI activity is outside that lock protocol.

The Node/MCP coordinator runs as the normal host account. `--sandbox` protects
Chromium browser processes; it does **not** isolate MCP filesystem access,
network egress, reference data or other workers. C00 must separately prove that
boundary. Host qualification is never scored-worker readiness.

## Native integration and schedule

To install only the root-owned updater code/hook/units, without migrating
maintenance, model, health or existing client registration:

```bash
python3 -B scripts/toolchain.py --runtime-root /absolute/runtime install-updater
# After the initial qualified update and repeat checks:
python3 -B scripts/toolchain.py --runtime-root /absolute/runtime install-updater --activate
```

The normal CLI submits a private source-hash-bound sudo job. Scheduled updates
run as the normal account using root-installed code. Reapplying preserves
matching files and backs up changed owned generations; unknown drift stops.
The installed paths are `/usr/local/libexec/modelbench-toolchains/`,
`/etc/modelbench-toolchain-updates.json`,
`/etc/apt/apt.conf.d/98modelbench-toolchain-events`,
`/var/lib/modelbench-toolchain-updates/` and three
`modelbench-toolchain-update.*` units. APT hooks write empty event markers only.

Checks are throttled to24hours, with daily06:00UTC and five-minute boot catch-up.
Berlin is08:00 in summer/07:00 in winter. APT/dpkg activity delays the job.
Existing security22:00/daily and general Sunday03:00 Europe/Berlin schedules
remain unchanged. Native APT still performs Brave/Node updates; npm does not.

```bash
systemctl status modelbench-toolchain-update.path modelbench-toolchain-update.timer
journalctl -u modelbench-toolchain-update.service -n 50 --no-pager
```

## Native changes, pinning and recovery limits

A native Brave/Node/package change invalidates the old qualification. A new
native-hash-bound npm release must qualify before use; an old release must
never silently execute against changed native bytes. Old npm directories,
locks, caches and reports remain retained. This is **not** a private native
OS image: it cannot restore old APT packages automatically. Rollback to old npm
requires matching native identities and a fresh successful qualification.

The generated `tools/toolchains/client.json` selects stable once per MCP process.
Existing user/client registrations are not overwritten by a separate runtime.
For a benchmark export a pinned fragment and use the same release for every
model/seed; do not let scored trials follow a moving stable pointer:

```bash
python3 -B scripts/toolchain.py --runtime-root /absolute/runtime client \
  --release RELEASE_ID --output /absolute/private/pinned-kilo-client.json
python3 -B scripts/toolchain.py --runtime-root /absolute/runtime rollback --release OLD_RELEASE_ID
```

`export`/`import`/`restore` retain and validate npm/controller payloads with
SHA256 and member limits. Native Brave/Node are prerequisites, not contained
in that recovery bundle; a different host needs matching native installation
and fresh qualification. No automatic deletion of old releases or failed runs.
Offline recovery still requires a separately observed rehearsal.

Policy is versioned at `config/toolchain-updates.json`; secrets stay in private
`model_canary.auth_file`, never JSON values/logs. After changing controller code,
reapply the updater-only installer so manual and scheduled generations agree.

References: [Playwright MCP installation](https://playwright.dev/mcp/installation),
[Playwright MCP configuration](https://github.com/microsoft/playwright-mcp#configuration),
[npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci/).

## Existing Spark qualification — 18 October 2026

AI-Model rollout `browser-updater-20261018-v9` passed14native updater tests,
ordinary and hardened real Brave/MCP/Kolibri canaries, unchanged pointer
bytes/mtime and0-file native reinstall. A pinned client completed actual
navigate/snapshot/close; a held benchmark lease refused inference. The installed
scheduled service exited0, path/timer enabled/active, daily06:00UTC. Existing
Berlin security22:00/general Sunday03:00 remain unchanged.

Native Brave155.1.97.59 and Node24.22.0 were reused; MCP0.0.83 and its full
Playwright1.64alpha dependency tree are separately locked. Release:
`02deac72bbc6a1150ae2ad2ab2bef606a193f411aa5b8fc44943517b779ef8bf`.
Source/runtime are beneath
`/home/validatus/workspace/AI-Model/runtime/spark-a922/tools/browser-updates/`
(`source-v9`, `runtime`, `rollout-20261018-v9/result.json`,
`postchecks-v9/result.json`). AI-Model indexed evidence is
`artifacts/evidence/browser-updater-20261018.json`.

Ten synthetic model requests across retained attempts459→469; no model restart,
native package upgrade or security-policy change. Existing old MCP client,
adoption registry, health and calibration remain preserved. Existing client/
benchmark freezes do not automatically follow the new stable pointer. This is
an existing-host tool qualification, not fresh-machine/worker readiness or a
rollback/offline-recovery rehearsal. C01–C07 remain stopped.
