#!/usr/bin/env python3
"""Install isolated benchmark clients and loopback Prometheus as validatus on Spark.

Inputs: --runtime PATH, sibling metrics.py. Never touches model units or environments.
Run: python3 -B setup-metrics.py --runtime /.../runtime/spark-a922/tools/benchmark
Flow: identity -> pinned downloads/checksum -> private venvs -> validate -> owned
user units -> health. Divergent units fail; old files and failed staging survive.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import urllib.request
import uuid


def publish_config(path, desired, legacy, promtool):
    """Only explicit exact legacy→health migration; validate before publication."""
    if any(p.is_symlink() for p in [path]+list(path.parents)):raise RuntimeError('Prometheus config symlink refused')
    if path.exists() and (not path.is_file() or path.stat().st_uid!=os.geteuid()):
        raise RuntimeError('Prometheus config ownership/type differs')
    old=path.read_bytes() if path.exists() else None
    mode=path.stat().st_mode&0o777 if old is not None else 0o600
    if old==desired:return False,old
    if old is not None and old!=legacy:raise RuntimeError('Preserve divergent Prometheus config')
    candidate=path.with_name('.prometheus-'+uuid.uuid4().hex+'.candidate')
    with candidate.open('xb') as out:
        os.fchmod(out.fileno(),mode);out.write(desired);out.flush();os.fsync(out.fileno())
    run(str(promtool),'check','config',str(candidate))
    if old is not None:
        backup=path.parent/'config-backups';backup.mkdir(exist_ok=True)
        prior=backup/(hashlib.sha256(old).hexdigest()+'.json')
        if prior.exists():
            if prior.read_bytes()!=old:raise RuntimeError('Config backup diverged')
        else:
            with prior.open('xb') as out:out.write(old)
    if (path.read_bytes() if path.exists() else None)!=old:raise RuntimeError('Config changed during validation')
    candidate.replace(path)
    return True,old

VERSION = "3.15.0"
SHA256 = "f1f90ec08e849d494ca66c611470afc50192f0355f1a61c33f2cbde02d067823"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def immutable(path, content):
    if path.exists():
        if path.read_text() != content:
            raise RuntimeError("Refusing divergent existing file: " + str(path))
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runtime", type=Path, required=True)
    selection=ap.add_mutually_exclusive_group()
    selection.add_argument("--clients-only", action="store_true")
    selection.add_argument("--metrics-only", action="store_true", help="Do not install AIPerf/LightEval clients")
    ap.add_argument("--include-health", action="store_true", help="Explicit known two→three scrape-job migration")
    args = ap.parse_args()
    if args.clients_only and args.include_health:ap.error('--include-health requires metrics installation')
    if os.getuid() != 1001 or platform.machine() != "aarch64":
        ap.error("Run as validatus UID1001 on Spark ARM64")
    base = args.runtime.resolve()
    expected = Path("/home/validatus/workspace/AI-Model/runtime/spark-a922/tools/benchmark")
    if base != expected:
        ap.error("Runtime must be " + str(expected))
    base.mkdir(parents=True, exist_ok=True)
    os.environ.update({"PIP_CACHE_DIR": str(base / "cache/pip"), "TMPDIR": str(base / "tmp"),
                       "HF_HOME": str(base / "cache/huggingface"), "PYTHONDONTWRITEBYTECODE": "1"})
    (base / "tmp").mkdir(exist_ok=True)
    for name, requirements in ([] if args.metrics_only else [("aiperf-0.13.0", ["aiperf==0.13.0"]),
                               ("lighteval-0.13.0", ["lighteval==0.13.0", "langdetect==1.0.9", "emoji==2.15.0", "syllapy==0.7.2"])]):
        dependency_lock = Path(__file__).with_name("benchmark-" + name + ".lock.txt")
        if not dependency_lock.exists():
            dependency_lock = Path(__file__).resolve().parents[2] / "config" / dependency_lock.name
        if not dependency_lock.is_file():
            raise RuntimeError("Missing reviewed dependency lock: " + str(dependency_lock))
        venv = base / "venvs" / name
        complete = venv / "installed.json"
        if not complete.exists():
            run("python3", "-m", "venv", str(venv))
            python = str(venv / "bin/python")
            run(python, "-m", "pip", "install", "pip==25.3")
            if name.startswith("lighteval"):
                run(python, "-m", "pip", "install", "torch==2.8.0", "--index-url", "https://download.pytorch.org/whl/cpu")
            run(python, "-m", "pip", "install", "--requirement", str(dependency_lock))
            run(python, "-m", "pip", "check")
            freeze = subprocess.check_output([python, "-m", "pip", "freeze"], text=True)
            immutable(venv / "requirements.lock.txt", freeze)
            complete.write_text(json.dumps({"requirements": requirements, "python": python}, indent=2) + "\n")
        else:
            if json.loads(complete.read_text())["requirements"] != requirements:
                raise RuntimeError("Existing environment profile differs")
            run(str(venv / "bin/python"), "-m", "pip", "check")
        current = subprocess.check_output([str(venv / "bin/python"), "-m", "pip", "freeze"], text=True)
        if current != dependency_lock.read_text():
            raise RuntimeError("Environment drift against reviewed dependency lock: " + name)
    if args.clients_only:
        return
    archive = base / ("prometheus-" + VERSION + ".linux-arm64.tar.gz")
    if not archive.exists():
        partial = archive.with_suffix(".partial")
        with urllib.request.urlopen("https://github.com/prometheus/prometheus/releases/download/v" + VERSION + "/" + archive.name, timeout=60) as r, partial.open("wb") as f:
            shutil.copyfileobj(r, f)
        if hashlib.sha256(partial.read_bytes()).hexdigest() != SHA256:
            raise RuntimeError("Prometheus archive checksum mismatch; partial retained")
        partial.rename(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Existing archive checksum mismatch")
    release = base / ("prometheus-" + VERSION + ".linux-arm64")
    release.mkdir(exist_ok=True)
    with tarfile.open(str(archive), "r:gz") as tf:
        for name in ("prometheus", "promtool"):
            member = tf.getmember(release.name + "/" + name)
            if not member.isfile() or member.size > 512 * 1024 * 1024:
                raise RuntimeError("Unsafe release member")
            data = tf.extractfile(member).read()
            target = release / name
            if target.exists() and target.read_bytes() != data:
                raise RuntimeError("Existing binary differs")
            if not target.exists():
                target.write_bytes(data)
                target.chmod(0o755)
    config = base / "prometheus.json"
    prometheus_config = {"global": {"scrape_interval": "5s", "evaluation_interval": "5s"}, "scrape_configs": [
        {"job_name": "vllm", "static_configs": [{"targets": ["127.0.0.1:8000"], "labels": {
            "host": "spark-a922", "model_id": "kolibri-1", "revision": "258cae8ffffc8c12db670bdbc6ac01bcf8826c87",
            "quantization": "fp8", "context_tokens": "262144", "max_num_seqs": "1"}}]},
        {"job_name": "benchmark-host", "static_configs": [{"targets": ["127.0.0.1:9199"]}]}]}
    legacy=(json.dumps(prometheus_config,indent=2)+'\n').encode()
    if args.include_health:
        prometheus_config['scrape_configs'].append({'job_name':'dgx-spark-health',
            'scrape_interval':'30s','static_configs':[{'targets':['127.0.0.1:9817']}]})
    desired=(json.dumps(prometheus_config,indent=2)+'\n').encode()
    config_changed,old_config=publish_config(config,desired,legacy if args.include_health else desired,release/'promtool')
    run(str(release / "promtool"), "check", "config", str(config))
    exporter = base / "metrics.py"
    immutable(exporter, Path(__file__).with_name("metrics.py").read_text())
    common = "\nRestart=on-failure\nRestartSec=5\nNoNewPrivileges=yes\nPrivateTmp=yes\nUMask=0077\nNice=10\nMemoryMax=768M\nCPUQuota=100%\n\n[Install]\nWantedBy=default.target\n"
    units = {
        "ai-model-benchmark-prometheus.service": "[Unit]\nDescription=AI-Model benchmark Prometheus (loopback only)\n\n[Service]\nExecStart=" + str(release / "prometheus") + " --config.file=" + str(config) + " --web.listen-address=127.0.0.1:9090 --storage.tsdb.path=" + str(base / "tsdb") + " --storage.tsdb.retention.time=3d --storage.tsdb.retention.size=512MB" + common,
        "ai-model-benchmark-metrics.service": "[Unit]\nDescription=AI-Model benchmark host and run metadata\n\n[Service]\nExecStart=/usr/bin/python3 -B " + str(exporter) + " --runtime " + str(base) + common}
    changed = False
    for name, body in units.items():
        changed = immutable(Path.home() / ".config/systemd/user" / name, body) or changed
    linger = subprocess.check_output(["loginctl", "show-user", "validatus", "-p", "Linger", "--value"], text=True).strip()
    if linger != "yes":
        run("sudo", "-n", "loginctl", "enable-linger", "validatus")
    if subprocess.check_output(["loginctl", "show-user", "validatus", "-p", "Linger", "--value"], text=True).strip() != "yes":
        raise RuntimeError("User manager must survive logout")
    if changed:
        run("systemctl", "--user", "daemon-reload")
    for name in units:
        run("systemctl", "--user", "enable", "--now", name)
        run("systemctl", "--user", "is-active", "--quiet", name)
    if config_changed and old_config is not None:
        try:
            run('systemctl','--user','kill','--kill-who=main','--signal=HUP','ai-model-benchmark-prometheus.service')
            import time
            for attempt in range(15):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:9090/api/v1/status/config',timeout=3) as response:
                        actual=json.load(response)['data']['yaml']
                    if 'job_name: dgx-spark-health' in actual:break
                except (OSError,ValueError,KeyError):pass
                time.sleep(1)
            else:raise RuntimeError('Prometheus did not load health scrape job')
        except BaseException:
            if config.read_bytes()!=desired:raise RuntimeError('Config diverged; automatic rollback refused')
            recovery=config.with_name('.prometheus-recovery-'+uuid.uuid4().hex)
            with recovery.open('xb') as out:
                os.fchmod(out.fileno(),config.stat().st_mode&0o777);out.write(old_config)
            recovery.replace(config)
            run('systemctl','--user','kill','--kill-who=main','--signal=HUP','ai-model-benchmark-prometheus.service')
            raise
    run("loginctl", "show-user", "validatus", "-p", "Linger")
    print("Installed benchmark clients and loopback metrics; no model unit changed.")


if __name__ == "__main__":
    main()
