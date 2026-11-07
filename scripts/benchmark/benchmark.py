#!/usr/bin/env python3
"""Inventory and bounded AIPerf runs, as validatus on Spark; JSON profiles only.

Run: python3 -B benchmark.py --config config/benchmark.json inventory
     python3 -B benchmark.py --config config/benchmark.json perf --model kolibri-1
Flow: validate -> exclusive lock -> idle/health/context -> unique run -> snapshots
-> bounded AIPerf -> health/PID/counter checks -> receipt. Errors remain evidence.
No model restart/configuration/cache reset, system changes or corpus access.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import time
import urllib.parse
import urllib.request
import uuid


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path, data):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    temp.replace(path)


def load_config(path):
    config = json.loads(path.read_text())
    if config["version"] != "benchmark-v1" or not re.fullmatch(r"[a-f0-9]{40}", config["base_sha"]):
        raise ValueError("Invalid version/base SHA")
    perf = config["performance"]
    if perf["concurrency"] != [1, 2, 4] or len(set(perf["seeds"])) != 3:
        raise ValueError("Common concurrency/repetition contract violated")
    if not 1 <= perf["requests"] <= 12 or not 1 <= perf["output_tokens"] <= 128 or not 1 <= perf["input_tokens"] <= 2048:
        raise ValueError("Not a bounded pilot profile")
    for model in config["models"].values():
        if not model["enabled"]:
            continue
        u = urllib.parse.urlsplit(model["url"])
        if u.scheme != "http" or u.hostname != "127.0.0.1" or u.username or u.password:
            raise ValueError("Only credential-free loopback model endpoints permitted")
        if model["context_tokens"] != 262144 or not re.fullmatch(r"[a-f0-9]{40}", model["revision"]):
            raise ValueError("Unpinned model or context reduction")
    for task in config["general"]["tasks"]:
        if not re.fullmatch(r"[a-f0-9]{40}", task["revision"]):
            raise ValueError("Unpinned dataset")
    return config


def fetch(url, json_body=True):
    with urllib.request.urlopen(url, timeout=15) as response:
        body = response.read().decode()
        return json.loads(body) if json_body else body


def metric_sum(text, name):
    return sum(float(line.rsplit(" ", 1)[1]) for line in text.splitlines()
               if line.startswith(name + "{") or line.startswith(name + " "))


def host_memory():
    return {line.split(":")[0]: int(line.split()[1]) * 1024
            for line in Path("/proc/meminfo").read_text().splitlines()}


def unit_status(unit):
    output = subprocess.check_output(["systemctl", "show", unit, "-p", "MainPID", "-p", "ActiveState", "-p", "ControlGroup"], universal_newlines=True)
    return dict(line.split("=", 1) for line in output.splitlines())


def inventory(config, model_id):
    model = config["models"][model_id]
    if not model["enabled"]:
        raise RuntimeError("Model disabled: " + model["reason"])
    listed = fetch(model["url"] + "/v1/models")["data"]
    advertised = next(x for x in listed if x["id"] == model_id)
    if advertised.get("max_model_len") != model["context_tokens"]:
        raise RuntimeError("Advertised context mismatch; never reduce silently")
    if model["revision"] not in advertised.get("root", ""):
        raise RuntimeError("Server checkpoint path is not the pinned revision")
    state = unit_status(model["unit"])
    if state["ActiveState"] != "active":
        raise RuntimeError("Model service is not active")
    metrics = fetch(model["url"] + "/metrics", False)
    state_path = Path(config["runtime"]).parents[1] / "build/dgx-spark-vllm" / (model_id + ".json")
    deployed = json.loads(state_path.read_text())
    release = Path(deployed["release"])
    installed_snapshot = json.loads((release / "profile.json").read_text())
    installed_profile = installed_snapshot["model"]
    for key in ("max_num_seqs", "max_model_len"):
        expected = model["max_num_seqs"] if key == "max_num_seqs" else model["context_tokens"]
        if installed_profile["server"][key] != expected:
            raise RuntimeError("Installed serving configuration mismatch: " + key)
    if installed_profile["quantization"] != model["quantization"] or installed_profile["revision"] != model["revision"]:
        raise RuntimeError("Installed quantization/revision mismatch")
    versions = json.loads(subprocess.check_output([str(release / "venv/bin/python"), "-B", "-c",
                          "import json,importlib.metadata as m; print(json.dumps({x:m.version(x) for x in ['vllm','torch','aleph-alpha-inference','transformers']}))"], text=True))
    memory = host_memory()
    cgroup = Path("/sys/fs/cgroup") / state["ControlGroup"].lstrip("/")
    cgroup_values = {f: (cgroup / f).read_text().strip() for f in ("memory.current", "memory.swap.current", "memory.max") if (cgroup / f).exists()}
    return {"observed_at": now(), "host": platform.node(), "architecture": platform.machine(),
            "model_id": model_id, "profile": model, "advertised": advertised, "unit": state,
            "deployed": deployed, "installed_profile": installed_profile, "packages": versions,
            "host_memory_bytes": memory, "cgroup": cgroup_values,
            "requests_running": metric_sum(metrics, "vllm:num_requests_running"),
            "requests_waiting": metric_sum(metrics, "vllm:num_requests_waiting"),
            "metrics": metrics}


def check_idle(inv, config):
    if inv["requests_running"] or inv["requests_waiting"]:
        raise RuntimeError("Existing model requests active; refuse interference")
    if inv["host_memory_bytes"]["MemAvailable"] < config["performance"]["minimum_available_bytes"]:
        raise RuntimeError("Available memory below benchmark reserve")
    if int(inv["cgroup"].get("memory.swap.current", "0")):
        raise RuntimeError("Model cgroup uses swap")


def bounded_client(command, env, log, timeout):
    process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        return process.wait(timeout=timeout)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            pass
        raise


def run_once(config, model_id, concurrency, seed, config_path):
    base = Path(config["runtime"])
    before = inventory(config, model_id)
    check_idle(before, config)
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + model_id + "-c" + str(concurrency) + "-s" + str(seed) + "-" + uuid.uuid4().hex[:8]
    folder = base / "runs" / run_id
    folder.mkdir(parents=True, exist_ok=False)
    write_json(folder / "before.json", before)
    (folder / "before.prom").write_text(before["metrics"])
    perf, model = config["performance"], config["models"][model_id]
    cli = str(base / "venvs" / ("aiperf-" + perf["aiperf_version"]) / "bin/aiperf")
    ipc = base.parents[1] / "tmp" / ("perf-" + uuid.uuid4().hex[:8])
    ipc.mkdir(parents=True, mode=0o700, exist_ok=False)
    command = [cli, "profile", "--model", model_id, "--url", model["url"],
               "--endpoint-type", "chat", "--streaming", "--tokenizer", model["repository"], "--tokenizer-revision", model["revision"],
               "--concurrency", str(concurrency), "--request-count", str(perf["requests"]),
               "--synthetic-input-tokens-mean", str(perf["input_tokens"]), "--synthetic-input-tokens-stddev", "0",
               "--output-tokens-mean", str(perf["output_tokens"]), "--output-tokens-stddev", "0",
               "--random-seed", str(seed), "--extra-inputs", "temperature:0", "--extra-inputs", "ignore_eos:true",
               "--extra-inputs", "seed:" + str(seed), "--artifact-dir", str(folder / "aiperf"),
               "--zmq-ipc-path", str(ipc), "--ui-type", "simple"]
    receipt = {"run_id": run_id, "phase": "performance-pilot", "model_id": model_id, "concurrency": concurrency,
               "seed": seed, "started_at": now(), "command": command, "status": "RUNNING",
               "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
               "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "profile": config, "classification": perf["classification"], "server_max_num_seqs": model["max_num_seqs"],
               "interpretation": "Client concurrency above max_num_seqs includes server queuing, not simultaneous decode."}
    write_json(folder / "receipt.json", receipt)
    active = base / "active-run.json"
    write_json(active, {k: receipt[k] for k in ("run_id", "model_id", "phase", "concurrency")})
    env = dict(os.environ)
    env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                "HF_HOME": str(base / "cache/huggingface"), "HF_HUB_CACHE": str(base.parents[1] / "models/huggingface/hub"),
                "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1", "XDG_CACHE_HOME": str(base / "cache/xdg"),
                "MPLCONFIGDIR": str(base / "cache/matplotlib"), "TIKTOKEN_CACHE_DIR": str(base / "cache/tiktoken"),
                "TMPDIR": str(base / "tmp"), "TOKENIZERS_PARALLELISM": "false"})
    try:
        time.sleep(6)  # Let the independent 5s Prometheus scrape observe the Run-ID.
        version = subprocess.check_output([str(base / "venvs" / "aiperf-0.13.0/bin/python"), "-c", "import importlib.metadata; print(importlib.metadata.version('aiperf'))"], text=True).strip()
        if version != perf["aiperf_version"]:
            raise RuntimeError("AIPerf version mismatch")
        receipt["aiperf_version"] = version
        with (folder / "client.log").open("w") as log:
            exit_code = bounded_client(command, env, log, perf["timeout_seconds"])
        receipt["exit_code"] = exit_code
        if exit_code:
            raise RuntimeError("AIPerf failed; see retained client.log")
        exports = list((folder / "aiperf").rglob("profile_export_aiperf.json"))
        if len(exports) != 1:
            raise RuntimeError("AIPerf produced no unique metrics export despite successful exit")
        receipt["aiperf_export"] = str(exports[0].relative_to(folder))
        after = inventory(config, model_id)
        write_json(folder / "after.json", after)
        (folder / "after.prom").write_text(after["metrics"])
        receipt["pid_unchanged"] = before["unit"]["MainPID"] == after["unit"]["MainPID"]
        delta = metric_sum(after["metrics"], "vllm:request_success_total") - metric_sum(before["metrics"], "vllm:request_success_total")
        receipt["server_success_delta"] = delta
        receipt["external_request_contamination"] = delta != perf["requests"]
        if delta < perf["requests"]:
            raise RuntimeError("Fewer server successes than expected; client exit alone is not success")
        if not receipt["pid_unchanged"]:
            raise RuntimeError("Model PID changed during trial")
        check_idle(after, config)
        receipt["prometheus_targets"] = fetch(config["prometheus_url"] + "/api/v1/targets")
        query = urllib.parse.urlencode({"query": 'benchmark_run_info{run_id="' + run_id + '"}'})
        receipt["prometheus_run_series"] = fetch(config["prometheus_url"] + "/api/v1/query?" + query)
        if not receipt["prometheus_run_series"]["data"]["result"]:
            raise RuntimeError("Run-ID not observed by Prometheus")
        receipt["status"] = "CONTAMINATED" if receipt["external_request_contamination"] else "COMPLETED"
    except BaseException as exc:
        receipt["status"] = "FAILED"
        receipt["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        receipt["finished_at"] = now()
        receipt["files"] = {str(p.relative_to(folder)): {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                            for p in folder.rglob("*") if p.is_file() and p.name != "receipt.json"}
        write_json(folder / "receipt.json", receipt)
        active.unlink(missing_ok=True)
        print(json.dumps({"run_id": run_id, "status": receipt["status"], "receipt": str(folder / "receipt.json")}), flush=True)
    return receipt


def main():
    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(SystemExit("Benchmark job terminated")))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    sub = ap.add_subparsers(dest="command", required=True)
    for name in ("inventory", "perf"):
        p = sub.add_parser(name)
        p.add_argument("--model", default="kolibri-1")
    args = ap.parse_args()
    config = load_config(args.config)
    if os.getuid() != 1001 or platform.node() != "spark-a922":
        ap.error("Execute as validatus on spark-a922")
    base = Path(config["runtime"])
    if base != Path("/home/validatus/workspace/AI-Model/runtime/spark-a922/tools/benchmark"):
        ap.error("Unexpected runtime location")
    base.mkdir(parents=True, exist_ok=True)
    with (base / "benchmark.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.command == "perf" and (base / "active-run.json").exists():
            raise RuntimeError("Stale active Run-ID; preserve and review interrupted run before restarting")
        if args.command == "inventory":
            inv = inventory(config, args.model)
            path = base / ("inventory-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
            write_json(path, inv)
            print(path)
        else:
            for concurrency in config["performance"]["concurrency"]:
                for seed in config["performance"]["seeds"]:
                    run_once(config, args.model, concurrency, seed, args.config)


if __name__ == "__main__":
    main()
