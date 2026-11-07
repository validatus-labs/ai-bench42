"""Exact owned-unit checks and systemd state operations; no unrelated service mutation."""
import hashlib
import os
import shlex
import socket
import subprocess
from pathlib import Path
from .common import run, safe_path
from .profiles import ContractError, read_json


def service_state(ctx):
    result = subprocess.run(["systemctl", "show", ctx.unit, "--property=LoadState,ActiveState,SubState,MainPID,ExecMainStatus,FragmentPath,MemoryCurrent,MemorySwapCurrent,MemorySwapMax"],
                            capture_output=True, text=True, timeout=30)
    facts = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if result.returncode and facts.get("LoadState") != "not-found":
        raise ContractError("Cannot inspect model service state")
    return facts


def managed(ctx):
    safe_path(ctx.state_path)
    if not ctx.state_path.exists():
        if ctx.unit_path.exists() or service_state(ctx).get("LoadState") != "not-found":
            raise ContractError("Unmanaged systemd unit collision: " + ctx.unit)
        return None
    state = read_json(ctx.state_path)
    if state.get("owner") != "AI-Model/dgx-spark-vllm/v1" or state.get("model") != ctx.id:
        raise ContractError("Invalid lifecycle ownership record")
    release = safe_path(Path(state["release"]))
    if release.parent != ctx.base / "releases" or not release.is_dir():
        raise ContractError("Managed release path is invalid")
    expected = safe_path(release / "server.service").read_bytes()
    if hashlib.sha256(expected).hexdigest() != state.get("unit_sha256"):
        raise ContractError("Owned release unit was modified")
    if not ctx.unit_path.exists() or ctx.unit_path.is_symlink() or ctx.unit_path.read_bytes() != expected:
        raise ContractError("Remote unit diverged; preserve and investigate")
    facts = service_state(ctx)
    if facts.get("FragmentPath") != str(ctx.unit_path):
        raise ContractError("systemd loaded a different unit path")
    dropins = run(["systemctl", "show", ctx.unit, "--property=DropInPaths", "--value"], timeout=30).strip()
    if dropins:
        raise ContractError("Unmanaged systemd drop-ins must be reviewed")
    return state


def ensure_free_port(ctx):
    server = ctx.model["server"]
    with socket.socket() as sock:
        # Match the server's restart semantics: completed HTTP connections can
        # retain TIME_WAIT after its listener has closed. This does not permit
        # binding over an existing TCP listener (SO_REUSEPORT is never enabled).
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((server["host"], server["port"]))
        except OSError:
            raise ContractError("Configured port is occupied; existing server preserved")


def systemctl(ctx, action):
    if action not in ("start", "stop", "restart", "reset-failed"):
        raise ContractError("Unsupported service action")
    run(["sudo", "-n", "systemctl", action, ctx.unit], timeout=180)


def unit_text(ctx, release):
    # systemd escaping is not shell escaping; fixed safe paths contain neither % nor whitespace.
    if any(c in str(release) for c in "%\n\r\t \"\\"):
        raise ContractError("Unsupported runtime path for systemd")
    env = ctx.environment(release / "venv/bin/python")
    lines = ["# Managed by AI-Model/dgx-spark-vllm/v1", "[Unit]",
             "Description=AI-Model vLLM " + ctx.id, "After=network-online.target",
             "Wants=network-online.target", "[Service]", "Type=exec",
             "User=" + ctx.defaults["user"], "WorkingDirectory=" + str(release),
             "ExecStart=/usr/bin/python3 -B " + str(release / "source/modules/launch.py"),
             "Restart=no", "TimeoutStopSec=120", "KillMode=control-group",
             "UMask=0077", "NoNewPrivileges=yes", "PrivateTmp=yes", "LimitNOFILE=65536",
             "MemoryAccounting=yes", "MemorySwapMax=0",
             "StandardOutput=append:" + str(ctx.log_root / (release.name + "-server.log")),
             "StandardError=inherit"]
    for key, value in sorted(env.items()):
        if any(c in value for c in '\n\r%"\\'):
            raise ContractError("Unsafe service environment")
        lines.append('Environment="{}={}"'.format(key, value))
    lines += ["[Install]", "WantedBy=multi-user.target", ""]
    return "\n".join(lines)


def install_unit(ctx, source):
    source = safe_path(source)
    # Called only after managed() or the initial unmanaged-collision check.
    # Root integration is limited to this exact named project unit.
    run(["sudo", "-n", "install", "-o", "root", "-g", "root", "-m", "0644", source, ctx.unit_path])
    run(["sudo", "-n", "systemctl", "daemon-reload"])


def server_argv(profile, release):
    model = profile["model"]
    server = model["server"]
    snapshot = read_json(Path(release) / "weights.json")["snapshot"]
    argv = [str(Path(release) / "venv/bin/vllm"), "serve", snapshot,
            "--served-model-name", model["id"], "--host", server["host"],
            "--port", str(server["port"]), "--max-model-len", str(server["max_model_len"]),
            "--max-num-seqs", str(server["max_num_seqs"]),
            "--kv-cache-dtype", server["kv_cache_dtype"],
            "--gpu-memory-utilization", str(server["gpu_memory_utilization"]),
            "--max-num-batched-tokens", str(server["max_num_batched_tokens"]),
            "--reasoning-parser", server["reasoning_parser"],
            "--tool-call-parser", server["tool_call_parser"],
            "--enable-chunked-prefill"]
    for field in ("enable_auto_tool_choice", "enforce_eager", "enable_prefix_caching"):
        if server[field]:
            argv.append("--" + field.replace("_", "-"))
    if "kv_calibration" in model:
        argv += ["--worker-cls", "modules.calibration_worker.CalibratedWorker"]
    return argv
