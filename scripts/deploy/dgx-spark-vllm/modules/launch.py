#!/usr/bin/env python3
"""Systemd-only launcher: validate retained JSON -> host/RAM gates -> exec vLLM.

Runs as the profile user. Inputs are the immutable release's JSON profiles;
effects are a GPU server and runtime logs. Called by the owned server.service.
No network transport or context fallback occurs on failure.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.profiles import load, read_json, ContractError
from modules.common import Context
from modules import compatibility, lifecycle


def main():
    package = Path(__file__).resolve().parents[1]
    release = package.parent
    retained = read_json(release / "profile.json")
    profile = load(package, retained["model"]["id"])
    if retained != profile:
        raise ContractError("Retained profile diverged from validated release source")
    ctx = Context(package, profile)
    compatibility.host(ctx, starting=True)
    compatibility.cuda_budget(ctx, release / "venv/bin/python")
    argv = lifecycle.server_argv(profile, release)
    env = ctx.environment(release / "venv/bin/python")
    if "kv_calibration" in ctx.model:
        from modules.calibration import validate_manifest
        spec = ctx.model["kv_calibration"]
        validate_manifest(spec["manifest"], spec["sha256"], ctx.model["revision"])
        compatibility.host(ctx, starting=True)
        # Only this immutable release's owned worker extension is importable.
        env["PYTHONPATH"] = str(package)
    os.execve(argv[0], argv, env)


if __name__ == "__main__":
    main()
