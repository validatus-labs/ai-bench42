"""Owned runtime paths, atomic records, bounded commands and JSON events."""
import contextlib
import datetime
import fcntl
import json
import os
import pwd
import subprocess
import uuid
from pathlib import Path
from .profiles import ContractError


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("x") as stream:
        os.chmod(str(temp), 0o600)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(str(temp), str(path))


def safe_path(path):
    path = Path(path)
    for parent in [path] + list(path.parents):
        if parent.is_symlink():
            raise ContractError("Symlink in managed path: " + str(parent))
    return path


def run(argv, timeout=120, env=None, log=None):
    if list(map(str, argv))[:2] == ["sudo", "-n"]:
        from .privileged import request
        output = request(argv[2:], timeout)
        if output is not None:
            return output
    if log:
        with Path(log).open("ab") as stream:
            result = subprocess.run(list(map(str, argv)), stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, env=env)
        output = "see " + str(log)
    else:
        result = subprocess.run(list(map(str, argv)), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, universal_newlines=True,
                                timeout=timeout, env=env)
        output = result.stdout
    if result.returncode:
        # No complete command/env dump: dependency and subprocess logs stay in runtime.
        raise ContractError("{} exited {} ({})".format(Path(argv[0]).name, result.returncode,
                                                      output if log else result.stderr[-1500:]))
    return output


class Context:
    def __init__(self, package, profile):
        self.package = Path(package).resolve()
        self.profile = profile
        self.defaults = profile["defaults"]
        self.model = profile["model"]
        self.root = safe_path(self.defaults["runtime_root"])
        self.base = safe_path(self.root / "build/dgx-spark-vllm")
        self.id = self.model["id"]
        self.unit = "ai-model-vllm-" + self.id + ".service"
        self.unit_path = Path("/etc/systemd/system") / self.unit
        self.state_path = self.base / (self.id + ".json")
        self.log_root = safe_path(self.root / "logs/dgx-spark-vllm")
        self.run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
        self.events = self.log_root / (self.id + "-" + self.run_id + ".jsonl")

    def identity(self):
        if os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != self.defaults["user"]:
            raise ContractError("Run as {} without sudo; the controller uses sudo -n only for its owned systemd unit".format(self.defaults["user"]))
        if os.environ.get("HOME") != pwd.getpwuid(os.geteuid()).pw_dir:
            raise ContractError("HOME does not match deployment account")

    def initialize(self):
        self.identity()
        for path in (self.base, self.log_root, self.root / "models/huggingface", self.root / "tmp/vllm-cache"):
            safe_path(path).mkdir(parents=True, exist_ok=True)
            if path.stat().st_uid != os.geteuid():
                raise ContractError("Wrong runtime owner: " + str(path))

    def event(self, event, **fields):
        record = {"time": now(), "run_id": self.run_id, "model": self.id, "event": event}
        record.update(fields)
        with self.events.open("a") as stream:
            os.chmod(str(self.events), 0o600)
            stream.write(json.dumps(record, sort_keys=True) + "\n")
        print(json.dumps(record, sort_keys=True), flush=True)

    @contextlib.contextmanager
    def locked(self):
        self.initialize()
        lock_path = safe_path(self.base / ".lifecycle.lock")
        with lock_path.open("a+") as stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ContractError("Another model lifecycle operation is running")
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def environment(self, python=None):
        # Do not inherit arbitrary VLLM_*, PYTHONPATH, HF_TOKEN or serving overrides.
        user = pwd.getpwnam(self.defaults["user"])
        env = {"HOME": user.pw_dir, "USER": user.pw_name, "LANG": "C.UTF-8",
               "PATH": "/usr/local/cuda/bin:/usr/local/bin:/usr/bin:/bin",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
               "HF_HOME": str(self.root / "models/huggingface"),
               "HF_MODULES_CACHE": str(self.root / "models/huggingface/modules"),
               "HF_HUB_DISABLE_TELEMETRY": "1", "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
               "XDG_CACHE_HOME": str(self.root / "tmp/vllm-cache"),
               "XDG_CONFIG_HOME": str(self.root / "tmp/vllm-config"),
               "TMPDIR": str(self.root / "tmp/vllm-cache"),
               "PIP_CACHE_DIR": str(self.root / "tmp/vllm-cache/pip"),
               "PIP_CONFIG_FILE": "/dev/null", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
               "TORCH_EXTENSIONS_DIR": str(self.root / "build/torch-extensions"),
               "TRITON_CACHE_DIR": str(self.root / "build/triton-cache"),
               "TORCHINDUCTOR_CACHE_DIR": str(self.root / "build/inductor-cache"),
               "NUMBA_CACHE_DIR": str(self.root / "build/numba-cache"),
               "CUDA_CACHE_PATH": str(self.root / "build/cuda-cache"),
               "VLLM_CACHE_ROOT": str(self.root / "build/vllm-cache"),
               "FLASHINFER_WORKSPACE_BASE": str(self.root / "build/flashinfer"),
               "FLASHINFER_CUBIN_DIR": str(self.root / "build/flashinfer-cubin")}
        env.update(self.defaults["environment"])
        if python is not None:
            binary_dir = Path(python).parent
            env["PATH"] = str(binary_dir) + ":" + env["PATH"]
            env["VIRTUAL_ENV"] = str(binary_dir.parent)
        return env
