#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manage owned DGX Spark vLLM releases as validatus, with validated JSON profiles.

Usage: python3 -B vllmctl.py deploy kolibri-1
Inputs: config/defaults.json, config/schema.json, models/<id>.json.
Effects: isolated runtime env/cache/logs and narrowly owned systemd integration.
  JSON -> identity/lock/compatibility -> stage -> systemd -> health -> commit
                                           failure -> preserve/rollback
Status is read-only. Verify sends requests and writes runtime evidence. No SSH,
system-wide pip, context fallback or deletion of model environments occurs.
"""
import argparse
import json
import signal
import subprocess
import sys
from pathlib import Path
from modules.common import Context
from modules.profiles import load, ContractError, fingerprint
from modules import compatibility, deployment, lifecycle, verifier


def main(argv=None):
    def interrupted(signum, frame):
        raise ContractError("Lifecycle operation interrupted by signal {}".format(signum))
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["deploy", "start", "stop", "restart", "status", "verify"])
    parser.add_argument("model")
    parser.add_argument("--long-context", action="store_true", help="verify a real 262112+32 token request (verify only)")
    args = parser.parse_args(argv)
    if args.long_context and args.command != "verify":
        parser.error("--long-context is only valid with verify")
    ctx = None
    try:
        package = Path(__file__).resolve().parent
        ctx = Context(package, load(package, args.model))
        ctx.identity()
        if args.command == "status":
            state = lifecycle.managed(ctx)
            print(json.dumps({"model": ctx.id, "deployment": state, "service": lifecycle.service_state(ctx),
                              "profile_matches": bool(state and state["fingerprint"] == fingerprint(ctx.profile, package)),
                              "target_context": ctx.model["server"]["max_model_len"],
                              "full_context_request_verified": None,
                              "verification_evidence_directory": str(ctx.log_root)}, indent=2))
            return 0
        with ctx.locked():
            ctx.event("operation_started", command=args.command)
            if args.command == "deploy":
                deployment.deploy(ctx)
            elif args.command in ("start", "restart"):
                deployment.start(ctx, restart=args.command == "restart")
            elif args.command == "stop":
                deployment.stop(ctx)
            else:
                state = lifecycle.managed(ctx)
                if not state or state["fingerprint"] != fingerprint(ctx.profile, package):
                    raise ContractError("Verify requires the current validated profile/source to be deployed")
                verifier.verify(ctx, long_context=args.long_context)
            ctx.event("operation_completed", command=args.command)
        return 0
    except (ContractError, OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as exc:
        if ctx and ctx.log_root.exists():
            ctx.event("operation_failed", error=str(exc))
        else:
            print(json.dumps({"event": "operation_failed", "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
