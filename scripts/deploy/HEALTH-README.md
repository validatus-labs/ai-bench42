# Health monitoring: why it exists and how to use it

The health bridge helps answer **why the local model is slow or unavailable**:
is the host short of memory, is the GPU reporting trouble, has the model
service stopped, or are requests waiting? It collects these observations in
one place so operators and monitoring tools can distinguish the causes.

This component belongs to the **DGX Spark / NVIDIA / Kolibri vLLM bootstrap**.
It monitors `ai-model-vllm-kolibri-1.service` at `http://127.0.0.1:8000`.

## How it works

```text
Host memory, pressure, filesystem, kernel, GPU, systemd and local vLLM
                              |
                              v
dgx-spark-health.timer -> bounded collection (default interval: 60s)
                              |
                              v
/var/lib/dgx-spark-health/report.json   # Atomically replaced snapshot
           |-- history/*.jsonl        # Local observations, default 30 days
                              |
                              v
Exporter: http://127.0.0.1:9817
    |-- /healthz   # Is the monitoring snapshot current?
    `-- /metrics   # What did each check observe?
                              |
                              v
Operator / existing Prometheus -> dashboards and alerts
```

Collection starts about 30 seconds after boot, then 60 seconds after the
previous collection finishes by default. HTTP requests only read the cached
snapshot; they do not run the probes again. Collection calls vLLM's `/health`
and `/metrics`, but never asks it to generate tokens or runs a benchmark.
Monitoring reports problems; it does not restart the model, clear memory,
change GPU settings or reboot the host.

## History and retention

The latest snapshot remains in `report.json`. Each new collection also saves
its observations in private, UTC-hour JSONL files under
`/var/lib/dgx-spark-health/history/`. This history starts after rollout of this
version; earlier overwritten snapshots cannot be recovered.

Choose retention when installing or updating health monitoring:

```bash
# Default on a fresh installation: keep 30 days.
python3 -B scripts/bootstrap.py --health --on

# Explicit choices: 7, 30, 90, 180 or 365 days.
python3 -B scripts/bootstrap.py --health --retention 90 --plan
python3 -B scripts/bootstrap.py --health --retention 90 --on

# Keep history indefinitely; disk usage will grow.
python3 -B scripts/bootstrap.py --health --retention forever --on
```

`forever` means **never delete history**, not live-only monitoring.
`--retention never` and the short form `--never` are aliases for `forever`.
There is no live-only history mode in this version. Repeating installation
without a retention flag preserves the saved setting; the fresh-install
default is 30 days. Use the same `--runtime-root` as before when applicable.

Retention is saved as `retention_days` in the root-owned health configuration.
Each collection removes archived snapshots older than the selected number of
24-hour days, by their collection timestamps. Complete expired hourly files
are removed; the boundary hour is trimmed atomically. When monitoring is
stopped, cleanup also stops and catches up at the next collection. Shortening
retention takes effect at the installation's collection and deletes expired
history; selecting `forever` later does not restore it. Reducing retention is
not part of the configuration rollback: already deleted history stays deleted.

Only the owned health-history directory is pruned. The latest snapshot,
installation backups, system journal and external Prometheus database have
separate lifecycles. Prometheus uses **its own retention setting**; this flag
does not configure it. HTTP endpoints continue to serve only the latest
snapshot; read historical JSONL on the host as an administrator. Files are
root-only and contain observations, not raw kernel logs. Hourly writes are
atomic and bounded to 16 MiB; an unexpected file or damaged history fails
collection and requires inspection rather than being silently erased.

## The two HTTP routes

Both routes are available **on the serving host only**, at loopback port 9817.
Installation opens no firewall port. `127.0.0.1` on another machine or inside a
container refers to that machine or container, not the serving host.

| Route | Response | Meaning |
| --- | --- | --- |
| `/healthz` | HTTP 200, `ready` | A readable snapshot matches the configuration and current boot and is fresh. Individual checks may still report critical problems. |
| `/healthz` | HTTP 503, `stale` | The snapshot is too old, dated in the future, or from a previous boot. |
| Either route | HTTP 503, `health snapshot unavailable` | The snapshot is missing, unreadable, invalid or from a different configuration. Inspect the checker logs. |
| `/metrics` | HTTP 200, Prometheus text | Check statuses and observations. A stale snapshot still returns 200, but sets the stale metric and makes every check unknown. |

Other paths return HTTP 404. With the default 60-second interval, a snapshot
becomes stale after **210 seconds** (`3 × interval + 30 seconds`). Stale
numeric observations are omitted rather than presented as current readings.

## What the 16 checks mean

Status values are `0` OK, `1` informational, `2` warning, `3` critical and
`-1` unknown. Unknown means the observation could not be made; it is not a
successful check. Thresholds are operational heuristics, not benchmark scores.

| Check ID | Observation and current thresholds |
| --- | --- |
| `memory.uma_pressure` | Available host memory as a percentage of total unified memory: warning below 10%, critical below 5%. This is not discrete GPU VRAM usage. |
| `memory.swap` | Swap used in bytes; any usage warns. This does not diagnose the cause. |
| `pressure.cpu` | Linux PSI `some avg10`: warning at 25%, critical at 50%. |
| `pressure.memory` | PSI `some avg10`: warning at 5%, critical at 20%. |
| `pressure.io` | PSI `some avg10`: warning at 10%, critical at 30%. |
| `storage.space` | Available filesystem space: warning below 10%, critical below 5%. See the path limitation below. |
| `storage.inodes` | Available filesystem inodes, with the same 10% / 5% thresholds and path limitation. |
| `kernel.oom_events` | Matching OOM kernel log messages in the last 10 minutes; any match is critical. Counts messages, not unique incidents. |
| `gpu.xid_error` | Matching NVIDIA Xid kernel log messages in the last 10 minutes; any match is critical. |
| `gpu.nvml_available` | `nvidia-smi` can query the expected GB10 and driver. This is not full NVML/DCGM qualification. |
| `gpu.temperature` | GPU temperature in °C: warning at 80, critical at 90. |
| `gpu.power_telemetry` | Reported GPU power in watts. Availability is checked, with no power alarm threshold; this is not total host power. |
| `vllm.service` | The Kolibri systemd unit is active and has a main process; otherwise critical. |
| `vllm.health` | The local model `/health` returns HTTP 200; request failures become unknown. No generation is attempted. |
| `vllm.queue` | Waiting requests from vLLM metrics: warning at 2, critical at 8. Running requests are also retained in the JSON snapshot. |
| `cuda.torch_cpu_only` | Reads the active model interpreter's PyTorch metadata and checks CUDA library mappings in its cgroup. A CPU-only build is critical; unavailable evidence is unknown. It does not execute user Python as root or allocate GPU memory. |

**Current path limitation:** the two storage checks still inspect the imported
project path `/home/validatus/workspace/AI-Model`. The wrapper records the
selected `runtime_root` for interpreter validation, but these two probes do
not yet use it. If that old path is absent, they report unknown; if present,
they measure its filesystem, which may differ from the model storage.

## Install, inspect and stop

From the repository root, as your normal account on the supported Spark host:

```bash
# Preview, then install only monitoring through the common wrapper.
python3 -B scripts/bootstrap.py --health --plan
python3 -B scripts/bootstrap.py --health --on

# Inspect the installed snapshot and its explanations.
bash /usr/local/lib/dgx-spark-health/bootstrap.sh status

# Read freshness and check values on the serving host.
curl --fail --show-error http://127.0.0.1:9817/healthz
curl --fail --show-error http://127.0.0.1:9817/metrics

# Inspect scheduling, exporter and recent collection logs.
systemctl status dgx-spark-health.timer dgx-spark-health-exporter.service
journalctl -u dgx-spark-health.service -n 50 --no-pager

# Request a collection now rather than waiting for the timer.
sudo bash /usr/local/lib/dgx-spark-health/bootstrap.sh run-once

# Stop monitoring and disable its startup; keep configuration and snapshots.
python3 -B scripts/bootstrap.py --health --off
```

Use the same `--runtime-root` as the original installation if you selected a
custom runtime. The wrapper handles installation privileges and ownership as
described in the [bootstrap guide](README.md). The collector runs as root for
host observations; the HTTP exporter uses a separate systemd dynamic user.

## Read the metrics and connect Prometheus

For example, `dgx_health_check_status{check_id="vllm.service"} 3` means the
observed model service is not active with a main process. `/healthz` can still
say `ready` because the monitoring itself is working and its result is fresh.

The exported metric names are:

- `dgx_health_check_status{check_id="..."}` — status of each check.
- `dgx_health_observation{check_id="..."}` — numeric value when available;
  units differ by check as described above, so do not sum these values.
- `dgx_health_snapshot_stale` — `1` for stale, `0` for fresh.
- `dgx_health_snapshot_age_seconds` — age of the collection start time.
- `dgx_health_last_collection_timestamp_seconds` — collection start timestamp.
- `dgx_health_collection_duration_seconds` — elapsed collection time.

To print a scrape configuration for an **existing, host-local Prometheus**:

```bash
bash /usr/local/lib/dgx-spark-health/bootstrap.sh config
```

Add its output under the existing `scrape_configs` list. The suggested scrape
interval is 30 seconds; collecting the same snapshot twice between probes is
expected. Installation neither installs nor edits Prometheus. Alert separately
on exporter connection failures, stale/unavailable snapshots, unknown checks
and warning/critical statuses; an HTTP 200 alone does not establish model health.

## Installed files

```text
/etc/default/dgx-spark-health                # Root-owned JSON configuration
/etc/systemd/system/
|-- dgx-spark-health.service                 # One bounded collection
|-- dgx-spark-health.timer                   # Repeated collection
`-- dgx-spark-health-exporter.service        # Cached HTTP exporter
/usr/local/lib/dgx-spark-health/
|-- bootstrap.sh                            # Installed implementation
`-- installed.json                          # Managed file ownership/hashes
/var/lib/dgx-spark-health/
|-- report.json                             # Latest snapshot and explanations
|-- history/                                # Root-only UTC-hour JSONL, retention
|   |-- owner.json                          # Managed history identity
|   `-- YYYYMMDDTHH0000Z.jsonl               # One JSON snapshot per line
`-- private/                                # Locks and installation records/backups
```

The snapshot includes collection time, boot/configuration identity, check
details and available numeric observations. Raw kernel messages are not
published. These observations support operations; parser quality, generation
correctness and benchmark worker readiness require their own checks.

Implementation: [dgx-spark-health-bootstrap.sh](dgx-spark-health-bootstrap.sh).
