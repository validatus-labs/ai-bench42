"""Create new release virtualenvs; never upgrade an existing model environment."""
import hashlib
import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from . import compatibility
from .common import atomic_json, run
from .profiles import ContractError, read_json


def prepare(ctx, release):
    if "kv_calibration" in ctx.model:
        # Borrow the exact qualified environment read-only. Retain the source
        # release permanently: the link is a dependency, not an install target.
        from . import lifecycle
        from .calibration import digest, validate_manifest
        spec = ctx.model["kv_calibration"]
        validate_manifest(spec["manifest"], spec["sha256"], ctx.model["revision"])
        previous = lifecycle.managed(ctx)
        source = Path(spec["source_release"])
        if not previous or previous["release"] != str(source):
            raise ContractError("Calibrated staging requires its exact baseline release")
        baseline = read_json(source / "profile.json")
        stripped = dict(ctx.model)
        stripped.pop("kv_calibration")
        if stripped != baseline["model"] or ctx.defaults != baseline["defaults"]:
            raise ContractError("Calibration may change only scale metadata")
        if digest(source / "requirements.lock") != spec["requirements_sha256"]:
            raise ContractError("Baseline environment lock changed")
        frozen = run([source / "venv/bin/python", "-B", "-m", "pip", "freeze", "--all"], env=ctx.environment())
        if frozen != (source / "requirements.lock").read_text():
            raise ContractError("Installed packages drifted from baseline lock")
        (release / "venv").symlink_to(source / "venv", target_is_directory=True)
        shutil.copy2(source / "requirements.lock", release / "requirements.lock")
        atomic_json(release / "environment-reuse.json", {"source_release": str(source),
                    "requirements_sha256": spec["requirements_sha256"], "mutations": 0,
                    "retention_required": True})
        ctx.event("qualified_environment_reused", source_release=str(source), packages_modified=False)
        return release / "venv/bin/python"
    python = release / "venv/bin/python"
    env = ctx.environment(python)
    log = ctx.log_root / (ctx.id + "-" + ctx.run_id + "-install.log")
    run([ctx.defaults["python"], "-B", "-m", "venv", str(release / "venv")],
        env=env, log=log)
    run([python, "-B", "-m", "pip", "install", "--index-url", ctx.defaults["index_url"],
         "pip==" + ctx.defaults["pip_version"]], timeout=600, env=env, log=log)
    ctx.event("dependency_install", log=str(log), packages=ctx.model["packages"])
    run([python, "-B", "-m", "pip", "install", "--index-url", ctx.defaults["index_url"],
         "--report", str(release / "installation.json")] + ctx.model["packages"],
        timeout=7200, env=env, log=log)
    check_dependencies(ctx, release, python, log)
    frozen = run([python, "-B", "-m", "pip", "freeze", "--all"], env=env)
    (release / "requirements.lock").write_text(frozen)
    ctx.event("owned_file_cache_advice", **compatibility.reclaim_owned_cache(ctx))
    facts = compatibility.environment(ctx, python)
    atomic_json(release / "compatibility.json", facts)
    ctx.event("backend_compatible", **facts)
    return python


def check_dependencies(ctx, release, python, log):
    result = subprocess.run([str(python), "-B", "-m", "pip", "check"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            universal_newlines=True, timeout=120, env=ctx.environment(python))
    with Path(log).open("a") as stream:
        stream.write(result.stdout)
    if result.returncode == 0:
        atomic_json(release / "dependency-check.json", {"pip_check_exit": 0, "exceptions": []})
        return
    lines = result.stdout.strip().splitlines()
    exceptions = ctx.defaults["wheel_metadata_exceptions"]
    if len(lines) != 1 or len(exceptions) != 1 or lines[0] != exceptions[0]["diagnostic"]:
        raise ContractError("Dependency check failed: " + result.stdout.strip())
    policy = exceptions[0]
    report = read_json(release / "installation.json")
    entry = next((x for x in report["install"] if x["metadata"]["name"].replace("_", "-") == policy["distribution"]), None)
    if not entry or entry["metadata"]["version"] != policy["version"]:
        raise ContractError("Vendor exception does not match installed package")
    info = entry["download_info"]
    url = urllib.parse.urlparse(info["url"])
    if url.scheme != "https" or url.hostname != "files.pythonhosted.org" or Path(url.path).name != policy["filename"] or info["archive_info"]["hashes"]["sha256"] != policy["sha256"]:
        raise ContractError("Vendor wheel source/hash does not match explicit exception")
    wheel = release / policy["filename"]
    with urllib.request.urlopen(info["url"], timeout=120) as response, wheel.open("xb") as out:
        shutil.copyfileobj(response, out)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != policy["sha256"]:
        raise ContractError("Vendor wheel bytes fail SHA256 check")
    site = release / "venv/lib/python3.12/site-packages"
    with zipfile.ZipFile(str(wheel)) as archive:
        for name in archive.namelist():
            if name.endswith("/") or name.endswith(".dist-info/RECORD"):
                continue
            path = site / name
            if ".." in Path(name).parts or Path(name).is_absolute() or path.is_symlink():
                raise ContractError("Unsafe installed vendor path")
            if not path.is_file() or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(archive.read(name)).digest():
                raise ContractError("Installed vendor file differs from pinned wheel: " + name)
        tags = [line[5:] for line in archive.read(next(n for n in archive.namelist() if n.endswith(".dist-info/WHEEL"))).decode().splitlines() if line.startswith("Tag: ")]
    if tags != [policy["metadata_tag"]]:
        raise ContractError("Vendor wheel metadata tag differs from explicit exception")
    library = site / policy["library"]
    with library.open("rb") as stream:
        header = stream.read(20)
    if header[:6] != b"\x7fELF\x02\x01" or int.from_bytes(header[18:20], "little") != 183:
        raise ContractError("Vendor binary is not little-endian ARM64 ELF")
    run([python, "-B", "-c", "import ctypes,sys,torch; ctypes.CDLL(sys.argv[1])", library], env=ctx.environment(python), timeout=60)
    facts = {"pip_check_exit": result.returncode, "exception": policy,
             "wheel_sha256": digest, "installed_files_match_wheel": True,
             "elf_machine": "AARCH64", "library_load": True,
             "wheel_rewritten": False}
    atomic_json(release / "dependency-check.json", facts)
    ctx.event("vendor_metadata_exception", warning=True, **facts)


def download(ctx, release, python):
    if "kv_calibration" in ctx.model:
        from .calibration import validate_manifest
        spec = ctx.model["kv_calibration"]
        # prepare() already hashes all shards; the launcher repeats that check
        # immediately before execution. Avoid an extra full checkpoint read here.
        manifest = validate_manifest(spec["manifest"], spec["sha256"], ctx.model["revision"], verify_weights=False)
        weights = read_json(Path(spec["source_release"]) / "weights.json")
        if weights["shards"] != manifest["original_shards"] or weights["snapshot"] != manifest["source_snapshot"]:
            raise ContractError("Calibrated overlay does not retain baseline weights")
        weights["snapshot"] = manifest["snapshot"]
        weights["calibration_manifest_sha256"] = spec["sha256"]
        atomic_json(release / "weights.json", weights)
        ctx.event("calibrated_checkpoint_overlay", original_weights_preserved=True, manifest_sha256=spec["sha256"])
        return
    # Public, pinned snapshot only; no token or untrusted remote Python code.
    code = '''import json, sys
from huggingface_hub import snapshot_download
path = snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2],
 allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "*.tiktoken", "*.jinja", "*.md"],
 token=False, max_workers=4)
print(json.dumps({"snapshot":path}))'''
    log = ctx.log_root / (ctx.id + "-" + ctx.run_id + "-download.log")
    ctx.event("model_download", repository=ctx.model["repository"], revision=ctx.model["revision"], log=str(log))
    run([python, "-B", "-c", code, ctx.model["repository"], ctx.model["revision"]],
        timeout=14400, env=ctx.environment(python), log=log)
    lines = log.read_text().splitlines()
    snapshot = Path(json.loads(next(x for x in reversed(lines) if x.startswith('{"snapshot":'))) ["snapshot"])
    expected = ctx.root / "models/huggingface/hub" / ("models--" + ctx.model["repository"].replace("/", "--")) / "snapshots" / ctx.model["revision"]
    if snapshot != expected:
        raise ContractError("Unexpected model cache snapshot path")
    config = read_json(snapshot / "config.json")
    compatibility.model_config(ctx, config)
    weight_index = read_json(snapshot / "model.safetensors.index.json")
    shards = sorted(set(weight_index["weight_map"].values()))
    metadata_url = "https://huggingface.co/api/models/{}/revision/{}?blobs=true".format(
        ctx.model["repository"], ctx.model["revision"])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(metadata_url, timeout=60) as response:
        metadata = json.load(response)
    if metadata.get("sha") != ctx.model["revision"]:
        raise ContractError("Weight metadata revision differs from pinned model")
    expected_files = {x["rfilename"]: x for x in metadata["siblings"]}
    records = []
    ctx.event("weights_integrity_check", shards=len(shards))
    for name in shards:
        if Path(name).name != name or not name.endswith(".safetensors"):
            raise ContractError("Invalid weight shard path")
        path = snapshot / name
        resolved = path.resolve()
        if not str(resolved).startswith(str(ctx.root / "models/huggingface/hub") + "/"):
            raise ContractError("Weight link escapes model cache")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
        # HF Hub 2.x global blob IDs are not necessarily file SHA256 values.
        # Compare against official LFS content metadata for the pinned revision.
        source = expected_files.get(name, {}).get("lfs", {})
        expected_hash = source.get("sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or source.get("size") != path.stat().st_size:
            raise ContractError("Missing or inconsistent pinned weight metadata: " + name)
        if expected_hash != digest.hexdigest():
            raise ContractError("Weight hash mismatch: " + name)
        records.append({"file": name, "bytes": path.stat().st_size, "sha256": digest.hexdigest(),
                        "official_lfs_sha256": expected_hash})
    atomic_json(release / "weights.json", {"snapshot": str(snapshot), "revision": metadata["sha"],
                "metadata_source": metadata_url, "shards": records})
    return snapshot


def snapshot_source(ctx, release):
    dest = release / "source"
    shutil.copytree(str(ctx.package), str(dest), ignore=shutil.ignore_patterns("tests", "__pycache__", "*.pyc"))
    # Effective configuration is retained separately from future source edits.
    atomic_json(release / "profile.json", ctx.profile)
