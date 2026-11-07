#!/usr/bin/env python3
"""Observe static Kolibri attention scales in a durable systemd job.

Run as validatus: python3 -B calibrate.py --spec /.../config/kolibri-calibration.json
Locks lifecycle and benchmarks; retains baseline/inputs/logs before stopping;
uses the existing pinned venv read-only; always restores the original service.
No weights, installed packages, host security or benchmark data are changed.
"""
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import signal
import os
import subprocess
from modules.common import Context, atomic_json, now
from modules.profiles import load, read_json, ContractError
from modules import lifecycle, compatibility, verifier
from modules.calibration import digest, prompts


def observe(command, env, log):
    child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        return child.wait(timeout=3600)
    except BaseException:
        # The EngineCore is a child process; terminating only its Python parent
        # can leave CUDA occupied and prevent baseline recovery.
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=30)
        raise


def create_overlay(folder, job, observations, python, env):
    source = Path(job["snapshot"])
    snapshot = folder / (job["spec"]["revision"] + "-calibrated")
    snapshot.mkdir()
    for path in source.iterdir():
        if path.is_file() and path.name != "model.safetensors.index.json":
            (snapshot / path.name).symlink_to(path.resolve())
    atomic_json(folder / "scales.json", observations["scales"])
    code = '''import json,sys,torch
from safetensors.torch import save_file
values=json.load(open(sys.argv[1]))
save_file({name+"."+field:torch.tensor(value,dtype=torch.float32) for name,row in values.items() for field,value in row.items()},sys.argv[2])'''
    subprocess.run([str(python), "-B", "-c", code, str(folder / "scales.json"), str(snapshot / "calibration.safetensors")],
                   env=env, check=True, timeout=60)
    index = read_json(source / "model.safetensors.index.json")
    for name, row in observations["scales"].items():
        for field in row:
            key = name + "." + field
            if key in index["weight_map"]:
                raise ContractError("Checkpoint already contains calibration scales")
            index["weight_map"][key] = "calibration.safetensors"
    index.setdefault("metadata", {})["total_size"] = index.get("metadata", {}).get("total_size", 0) + 50 * 4 * 4
    atomic_json(snapshot / "model.safetensors.index.json", index)
    files = [folder / "job.json", folder / "inputs.json", folder / "prepared-inputs.json", folder / "observations.json", folder / "scales.json",
             snapshot / "model.safetensors.index.json", snapshot / "calibration.safetensors"]
    files.extend(p for p in (folder / "export-derivation.json", folder / "loader-preflight.log", folder / "loader-exact-preflight.json",
                             folder / "backend-compatibility.json") if p.exists())
    for rel, checksum in job["source_sha256"].items():
        path = folder / "source" / rel
        if digest(path) != checksum:
            raise ContractError("Observer source changed during calibration")
        files.append(path)
    shard_hashes = {row["file"]: row["sha256"] for row in job["weights"]["shards"]}
    links = {p.name: {"target": str(p.resolve()), "sha256": shard_hashes.get(p.name) or digest(p),
                      "weight_shard": p.name in shard_hashes} for p in snapshot.iterdir() if p.is_symlink()}
    manifest = {"status": "CALIBRATED", "observed_at": now(), "revision": job["spec"]["revision"],
                "snapshot": str(snapshot), "source_snapshot": str(source), "baseline": job["baseline"],
                "spec": job["spec"], "scales": observations["scales"],
                "files": {p.relative_to(folder).as_posix(): digest(p) for p in files},
                "original_shards": job["weights"]["shards"],
                "linked_files": links,
                "derived_from": job.get("derived_from"),
                "scale_storage_dtype": job["spec"].get("scale_storage_dtype", "float32"),
                "scale_rounding": job["spec"].get("scale_rounding", "none"),
                "scale_scope": job["spec"].get("scale_scope", "qkv-prob"),
                "method_limit": "Project per-tensor minmax on 32 synthetic 2048-token prompts and 64 decode tokens, observed with native BF16 KV and original FP8 weights. Not llm-compressor or full-context calibration."}
    atomic_json(folder / "manifest.json", manifest)


def main():
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(ContractError("Calibration interrupted")))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", required=True, type=Path)
    args = ap.parse_args()
    package = Path(__file__).resolve().parent
    ctx = Context(package, load(package, "kolibri-1"))
    spec = read_json(args.spec)
    if spec != read_json(package.parents[2] / "config/kolibri-calibration.json"):
        raise ContractError("Use the maintained calibration specification")
    if spec["revision"] != ctx.model["revision"] or spec["context_tokens"] != 262144:
        raise ContractError("Calibration checkpoint/context mismatch")
    with ctx.locked(), (ctx.root / "tools/benchmark/benchmark.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (ctx.root / "tools/benchmark/active-run.json").exists():
            raise ContractError("Existing benchmark marker requires review")
        previous = lifecycle.managed(ctx)
        if not previous or previous["unit_sha256"] != spec["baseline_unit_sha256"]:
            raise ContractError("Expected exact preserved uncalibrated release")
        old_release = Path(previous["release"])
        old_profile = read_json(old_release / "profile.json")
        old = Context(old_release / "source", old_profile)
        # Health plus actual request counters: refuse a busy model.
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8000/metrics", timeout=15) as response:
            lines = response.read().decode().splitlines()
        if any(float(line.rsplit(" ", 1)[1]) != 0 for line in lines
               if line.startswith(("vllm:num_requests_running{", "vllm:num_requests_waiting{"))):
            raise ContractError("Existing model requests are active")
        folder = ctx.base / "calibration" / spec["experiment"]
        folder.mkdir(parents=True, exist_ok=False)
        folder.chmod(0o700)
        shutil.copy2(ctx.unit_path, folder / "baseline.service")
        observer_source = folder / "source"
        shutil.copytree(package, observer_source, ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
        weights = read_json(old_release / "weights.json")
        for shard in weights["shards"]:
            if digest(Path(weights["snapshot"]) / shard["file"]) != shard["sha256"]:
                raise ContractError("Original checkpoint shard changed")
        job = {"spec": spec, "baseline": previous, "snapshot": weights["snapshot"],
               "weights": weights, "original_profile": old_profile, "started_at": now(),
               "source_sha256": {p.relative_to(observer_source).as_posix(): digest(p)
                                 for p in observer_source.rglob("*") if p.is_file()}}
        atomic_json(folder / "job.json", job)
        atomic_json(folder / "inputs.json", prompts(spec))
        atomic_json(folder / "transaction.json", {"phase": "baseline-backed-up", "baseline": previous, "time": now()})
        python = old_release / "venv/bin/python"
        env = old.environment(python)
        env["PYTHONPATH"] = str(observer_source)
        # Validate the real tokenizer output for every input before any model
        # stop or GPU weight load. Transformers5 returns a dict by default.
        with (folder / "preparation.log").open("w") as log:
            preflight = subprocess.run([str(python), "-B", str(observer_source / "calibrate-worker.py"),
                        "--job", str(folder / "job.json"), "--prepare"], env=env,
                        stdout=log, stderr=subprocess.STDOUT, timeout=180)
        if preflight.returncode:
            atomic_json(folder / "failure.json", {"time": now(), "phase": "input-preflight", "baseline_untouched": True})
            raise ContractError("Input preflight failed; baseline untouched, see preparation.log")
        job["prepared_inputs_sha256"] = digest(folder / "prepared-inputs.json")
        atomic_json(folder / "job.json", job)
        try:
            lifecycle.systemctl(old, "stop")
            atomic_json(folder / "transaction.json", {"phase": "observing", "baseline": previous, "time": now()})
            compatibility.host(old, starting=True)
            with (folder / "observer.log").open("w") as log:
                result = observe([str(python), "-B", str(observer_source / "calibrate-worker.py"), "--job", str(folder / "job.json")], env, log)
            if result:
                raise ContractError("Observer failed, exit " + str(result) + "; see " + str(folder / "observer.log"))
            create_overlay(folder, job, read_json(folder / "observations.json"), python, env)
        except BaseException as exc:
            atomic_json(folder / "failure.json", {"time": now(), "error": str(exc)})
            raise
        finally:
            # Never overwrite a divergent unit or start a different model.
            if lifecycle.managed(old) != previous:
                raise ContractError("Baseline diverged; inspect retained transaction before recovery")
            lifecycle.systemctl(old, "start")
            health = verifier.wait(old)
            atomic_json(folder / "transaction.json", {"phase": "original-service-restored", "baseline": previous,
                        "time": now(), "health": health, "calibration_manifest_exists": (folder / "manifest.json").exists()})
        print(json.dumps({"manifest": str(folder / "manifest.json"), "sha256": digest(folder / "manifest.json"), "status": "OBSERVED_BASELINE_RESTORED"}))


if __name__ == "__main__":
    main()
