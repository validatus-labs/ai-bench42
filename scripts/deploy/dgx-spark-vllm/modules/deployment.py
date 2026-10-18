"""Staged immutable releases with journaled owned-unit cutover and rollback."""
import hashlib
import json
import shutil
from pathlib import Path
from . import compatibility, environment, lifecycle, verifier
from .common import atomic_json, now, run, safe_path
from .profiles import ContractError, fingerprint, read_json


def rollback(ctx, transaction):
    previous = transaction["previous"]
    candidate = Path(transaction["candidate"])
    current = ctx.unit_path.read_bytes() if ctx.unit_path.exists() else None
    allowed = [Path(transaction["candidate_unit"]).read_bytes()]
    if previous:
        allowed.append((Path(previous["release"]) / "server.service").read_bytes())
    if current not in allowed and not (current is None and previous is None):
        raise ContractError("Rollback refused: systemd unit diverged; retained transaction needs inspection")
    if current is not None:
        lifecycle.systemctl(ctx, "stop")
    if previous:
        lifecycle.install_unit(ctx, Path(previous["release"]) / "server.service")
        atomic_json(ctx.state_path, previous)
        if transaction["was_active"]:
            old = ContextForPrevious(ctx, previous)
            lifecycle.systemctl(old, "start")
            verifier.wait(old)
    else:
        # Only the exact candidate unit installed by this transaction is removed.
        if current is not None:
            run(["sudo", "-n", "rm", "--", ctx.unit_path])
        run(["sudo", "-n", "systemctl", "daemon-reload"])
        if ctx.state_path.exists():
            ctx.state_path.unlink()
    transaction["phase"] = "rolled_back"
    transaction["rollback_verified"] = lifecycle.service_state(ctx)
    atomic_json(ctx.base / (ctx.id + "-transaction.json"), transaction)
    atomic_json(candidate / "transaction.json", transaction)
    ctx.event("rollback_verified", previous_release=previous["release"] if previous else None,
              service=transaction["rollback_verified"])


def ContextForPrevious(ctx, state):
    from .common import Context
    profile = read_json(Path(state["release"]) / "profile.json")
    return Context(Path(state["release"]) / "source", profile)


def recover_interrupted(ctx):
    path = ctx.base / (ctx.id + "-transaction.json")
    if path.exists():
        transaction = read_json(path)
        if transaction.get("phase") == "switching":
            ctx.event("interrupted_cutover_detected")
            rollback(ctx, transaction)


def deploy(ctx):
    recover_interrupted(ctx)
    previous = lifecycle.managed(ctx)
    digest = fingerprint(ctx.profile, ctx.package)
    if previous and previous["fingerprint"] == digest:
        if lifecycle.service_state(ctx).get("ActiveState") == "active":
            health = verifier.health(ctx)
            ctx.event("deployment_unchanged", release=previous["release"], health=health)
            return previous
        start(ctx)
        return previous
    ctx.event("preflight", facts=compatibility.host(ctx, starting=not previous))
    if not previous:
        lifecycle.ensure_free_port(ctx)
    releases = safe_path(ctx.base / "releases")
    releases.mkdir(exist_ok=True)
    release = releases / (ctx.id + "-" + digest[:12] + "-" + ctx.run_id)
    release.mkdir()
    atomic_json(release / "staging.json", {"owner": "AI-Model/dgx-spark-vllm/v1", "fingerprint": digest, "phase": "preparing"})
    try:
        environment.snapshot_source(ctx, release)
        python = environment.prepare(ctx, release)
        environment.download(ctx, release, python)
        unit = release / "server.service"
        unit.write_text(lifecycle.unit_text(ctx, release))
        run(["systemd-analyze", "verify", unit], timeout=60)
    except BaseException as exc:
        atomic_json(release / "failure.json", {"time": now(), "phase": "staging", "error": str(exc)})
        ctx.event("staging_failed", release=str(release), error=str(exc), current_server_preserved=True)
        raise
    # A concurrent edit to an existing unit is never overwritten at cutover.
    if lifecycle.managed(ctx) != previous:
        raise ContractError("Lifecycle state changed while staging")
    was_active = lifecycle.service_state(ctx).get("ActiveState") == "active"
    transaction = {"owner": "AI-Model/dgx-spark-vllm/v1", "time": now(), "phase": "switching",
                   "previous": previous, "candidate": str(release), "candidate_unit": str(unit),
                   "was_active": was_active}
    atomic_json(ctx.base / (ctx.id + "-transaction.json"), transaction)
    try:
        if previous:
            # Previous unit and state are retained before any stop or overwrite.
            atomic_json(release / "previous-state.json", previous)
            shutil.copy2(str(ctx.unit_path), str(release / "previous.service"))
            lifecycle.systemctl(ctx, "stop")
        compatibility.host(ctx, starting=True)
        lifecycle.ensure_free_port(ctx)
        lifecycle.install_unit(ctx, unit)
        state = {"owner": "AI-Model/dgx-spark-vllm/v1", "model": ctx.id, "release": str(release),
                 "fingerprint": digest, "unit_sha256": hashlib.sha256(unit.read_bytes()).hexdigest(),
                 "deployed_at": now(), "target_context": ctx.model["server"]["max_model_len"]}
        atomic_json(ctx.state_path, state)
        lifecycle.systemctl(ctx, "start")
        health = verifier.wait(ctx)
        smoke = verifier.smoke(ctx)
        transaction["phase"] = "committed"
        atomic_json(ctx.base / (ctx.id + "-transaction.json"), transaction)
        atomic_json(release / "transaction.json", transaction)
        atomic_json(release / "acceptance.json", {"health": health, "smoke": smoke, "time": now()})
        ctx.event("deployment_committed", release=str(release), health=health, smoke=smoke)
        return state
    except BaseException as exc:
        ctx.event("cutover_failed", error=str(exc))
        try:
            rollback(ctx, transaction)
        except BaseException as rollback_error:
            ctx.event("rollback_failed", error=str(rollback_error), transaction=str(ctx.base / (ctx.id + "-transaction.json")))
            raise ContractError("Deployment failed; rollback also failed: " + str(rollback_error)) from exc
        raise


def start(ctx, restart=False):
    state = lifecycle.managed(ctx)
    if not state:
        raise ContractError("Deploy the model before starting")
    if state["fingerprint"] != fingerprint(ctx.profile, ctx.package):
        raise ContractError("Profile/source changed; deploy a new isolated release first")
    facts = lifecycle.service_state(ctx)
    if facts.get("ActiveState") == "active" and not restart:
        ctx.event("start_unchanged", health=verifier.health(ctx))
        return
    if restart:
        lifecycle.systemctl(ctx, "stop")
    compatibility.host(ctx, starting=True)
    lifecycle.ensure_free_port(ctx)
    try:
        lifecycle.systemctl(ctx, "start")
        result = verifier.wait(ctx)
        ctx.event("server_started", health=result)
    except BaseException:
        lifecycle.systemctl(ctx, "stop")
        raise


def stop(ctx):
    state = lifecycle.managed(ctx)
    if not state:
        ctx.event("stop_unchanged", reason="not deployed")
        return
    if lifecycle.service_state(ctx).get("ActiveState") not in ("inactive", "failed"):
        lifecycle.systemctl(ctx, "stop")
    facts = lifecycle.service_state(ctx)
    if facts.get("MainPID") != "0" or facts.get("ActiveState") not in ("inactive", "failed"):
        raise ContractError("Server did not stop: " + json.dumps(facts))
    ctx.event("server_stopped", service=facts, environments_preserved=True)
