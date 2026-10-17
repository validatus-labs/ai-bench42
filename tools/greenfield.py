#!/usr/bin/env python3
"""Idempotent ModelBench greenfield toolchain and rights-gated HPI TRAIN import.

Installs a pinned Playwright MCP + matching Chromium into an ignored private root.
Does not contact the network except on explicit 'install' / 'hpi-import'.
Outputs an MCP client configuration; workers must still be isolated externally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tarfile
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
ROOT_DEFAULT = PROJECT / "build" / "greenfield-playwright"
HPI_DEFAULT = PROJECT / "build" / "hpi-asf-train"
MCP = "@playwright/mcp"
MCP_VERSION = "0.0.83"
NODE_PIN = "22.22.2"
NODE_ARCHIVE_SHA256 = {
    "aarch64": "e9e1930fd321a470e29bb68f30318bf58e3ecb4acb4f1533fb19c58328a091fe",
    "x86_64": "88fd1ce767091fd8d4a99fdb2356e98c819f93f3b1f8663853a2dee9b438068a",
}
HPI_REPO = "HPI-Information-Systems/Quagga"
HPI_REF = "4ba5be0fd4a0a5954527ea93cf6592f54f4fc3f0"
ALLOWED_ORIGINS = (
    "https://docs.python.org",
    "https://www.rfc-editor.org",
    "https://datatracker.ietf.org",
    "https://developer.mozilla.org",
)
# Original body and matching .ann Git blob IDs at immutable HPI commit.
HPI_TRAIN = {
    "train_10": ("6641c7a04f792c25f0b3133dc23919e0ae6093df", "a9de02139173d4bbe35ac2b3ea32e579fe1da233"),
    "train_1011": ("bb932c82201e417143389996ea558263aabf1797", "4e1bb72e9bdf69fef7ede08fb59c9722ea5e05d6"),
    "train_1088": ("f61f782ba2837da48168e648f694686afa5d8005", "74d5fdde80d870b3a47fdf3f92f9785a161f5049"),
    "train_1089": ("162f4d51aec65934ac628934072c0b183d150c97", "ec36cc7e685d3e237d4c9f190ec337e08c2f439b"),
    "train_1105": ("9cf15427e42d87ebe23fae284db971c2064e5ae8", "92b7859137b332b65cf16b99221d9acc84599190"),
    "train_1129": ("635ba314e5240f57d9247e05845d5c1ee6986901", "1083d13ade36b17ad5b66575778ff5f746c4848a"),
    "train_1160": ("cfc94f2dc5b19307a889bd4520d7ebd8aa350555", "7c7628b363da4638b91d881811e1cd9cc7ae25cb"),
    "train_1198": ("d2a33534124435f31ddab3c48285c3cc3ad854b7", "2ef51a161e52cf3831f0d003b06b2620366852d8"),
    "train_123": ("29ca5c479fc7f2abb1316f8e49278e76b9c54c66", "79634e1833dad55118601a5932d1827169668315"),
    "train_1257": ("7aae4806d787fd30d8c196076d6e5c4f9341b2bb", "dfc98e02c4cd418556505c218610c7ae4d600546"),
    "train_1286": ("879baa8ae29fb94c4d8654367a395d68a7a11767", "ef5e059d4fac506e6d46ef49bed7527cfd2de5f8"),
    "train_1293": ("0474d8f48d0bf63f5d8cea079c975247839ef2b1", "e2dd0eeb3d2e452c8e9a3631069709143d5e7b7b"),
}


class Blocked(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blobsha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def jbytes(obj: object) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()


def private_write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(data)


def checked(command: list[str], cwd: Path, env: dict | None = None, timeout: int = 900) -> str:
    r = subprocess.run(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, timeout=timeout)
    if r.returncode:
        raise Blocked(f"{command[0]} failed ({r.returncode}): {(r.stdout + r.stderr)[-1300:]}")
    return r.stdout.strip()


def node_commands(root: Path) -> tuple[str, str, dict]:
    """Prefer private, pinned portable Node; otherwise qualify system Node."""
    portable = root / ".node" / "bin"
    if (portable / "node").is_file():
        if not (portable / "npm").is_file():
            raise Blocked("Portable npm missing; refuse incomplete toolchain")
        env = {**os.environ, "PATH": str(portable) + os.pathsep + os.environ.get("PATH", "")}
        return str(portable / "node"), str(portable / "npm"), env
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        raise Blocked("Node.js/npm missing: use 'greenfield' to install pinned portable Node")
    return node, npm, os.environ.copy()


def node_versions(root: Path | None = None) -> dict:
    node, npm, env = node_commands(root or PROJECT)
    version = checked([node, "--version"], PROJECT, env)
    try:
        major = int(version.removeprefix("v").split(".")[0])
    except ValueError as exc:
        raise Blocked("Unrecognized Node.js version") from exc
    if major < 20:
        raise Blocked("Node.js >=20 required; use 'greenfield' for pinned portable Node")
    if root and (root / ".node" / "bin" / "node").is_file() and version != "v" + NODE_PIN:
        raise Blocked("Portable Node pin changed")
    return {"node": version, "npm": checked([npm, "--version"], PROJECT, env)}


def install_portable_node(stage: Path) -> None:
    """Fetch Node LTS by pinned SHA256 into this installer-owned staging dir."""
    machine = platform.machine()
    if platform.system() != "Linux" or machine not in NODE_ARCHIVE_SHA256:
        raise Blocked("Greenfield Node supports Linux aarch64/x86_64 only")
    arch = "arm64" if machine == "aarch64" else "x64"
    filename = f"node-v{NODE_PIN}-linux-{arch}.tar.xz"
    url = f"https://nodejs.org/dist/v{NODE_PIN}/{filename}"
    archive = stage / filename
    sha = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "ModelBench-Greenfield"})
    with urllib.request.urlopen(req, timeout=120) as response:
        if response.geturl() != url:
            raise Blocked("Node download redirect changed trusted origin")
        with archive.open("xb") as target:
            while block := response.read(1024 * 1024):
                sha.update(block)
                target.write(block)
    if sha.hexdigest() != NODE_ARCHIVE_SHA256[machine]:
        raise Blocked("Node archive SHA256 does not match pinned release")
    with tarfile.open(archive, "r:xz") as tar:
        tar.extractall(stage, filter="data")
    (stage / filename.removesuffix(".tar.xz")).rename(stage / ".node")
    archive.unlink()
    if node_versions(stage)["node"] != "v" + NODE_PIN:
        raise Blocked("Portable Node extraction or version failed")

def browser_smoke(root: Path) -> dict:
    bundled = root / "node_modules" / "playwright"
    if not (bundled / "package.json").is_file():
        raise Blocked("Bundled Playwright missing")
    js = (
        "const {chromium}=require(process.argv[1]);"
        "(async()=>{const b=await chromium.launch({headless:true});try{"
        "const p=await b.newPage();await p.goto('data:text/html,<title>Bench</title><h1>OK</h1>');"
        "if(await p.title()!=='Bench')throw Error('bad title');"
        "console.log(JSON.stringify({status:'PASS',browser:'chromium',version:b.version()}));"
        "}finally{await b.close()}})().catch(e=>{console.error(e.message);process.exit(2)})"
    )
    node, _, base_env = node_commands(root)
    env = {**base_env, "PLAYWRIGHT_BROWSERS_PATH": str(root / "browsers")}
    output = checked([node, "-e", js, str(bundled)], root, env, timeout=90)
    try:
        result = json.loads(output.splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise Blocked("Invalid Chromium smoke result") from exc
    if result.get("status") != "PASS":
        raise Blocked("Chromium smoke failed")
    return result


def verify(root: Path, expected: str | None = None, smoke: bool = True) -> dict:
    pkg = root / "package.json"
    lock = root / "package-lock.json"
    stamp = root / "stamp.json"
    executable = root / "node_modules" / "@playwright" / "mcp" / "cli.js"
    installed = root / "node_modules" / "@playwright" / "mcp" / "package.json"
    if any(not x.is_file() for x in (pkg, lock, stamp, executable, installed)):
        raise Blocked("Incomplete toolchain; refuse to repair silently: " + str(root))
    pin = json.loads(pkg.read_text())["dependencies"].get(MCP)
    if pin != MCP_VERSION or json.loads(installed.read_text())["version"] != MCP_VERSION:
        raise Blocked("MCP package version differs from pinned version")
    metadata = json.loads(stamp.read_text())
    digest = sha256(lock.read_bytes())
    if digest != metadata.get("lock_sha256") or (expected and expected != digest):
        raise Blocked("Toolchain lock SHA mismatch; don't mix models or trials")
    if metadata.get("arch") != platform.machine() or metadata.get("os") != platform.system():
        raise Blocked("Browser binaries are installed for another platform")
    live_node = node_versions(root)
    if live_node != {"node": metadata.get("node"), "npm": metadata.get("npm")}:
        raise Blocked("Node/npm runtime changed since the pinned installation")
    result = {"status": "VERIFIED", "mcp_version": MCP_VERSION,
              "lock_sha256": digest, "arch": metadata["arch"], "os": metadata["os"],
              "node": live_node["node"], "npm": live_node["npm"]}
    if smoke:
        result["browser_smoke"] = browser_smoke(root)
    return result


def install(root: Path, expected: str | None, deps: bool, greenfield: bool = False) -> dict:
    if root.exists():
        if greenfield and not (root / ".node" / "bin" / "node").is_file():
            raise Blocked("Existing installation is not pinned greenfield Node; refuse reinterpretation")
        return {"action": "REUSED", **verify(root, expected)}
    if platform.system() != "Linux":
        raise Blocked("Linux only; DGX Spark ARM64 supported when upstream binaries are available")
    if not greenfield:
        node_versions()
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".modelbench-owned-", dir=root.parent))
    os.chmod(staging, 0o700)
    try:
        if greenfield:
            install_portable_node(staging)
        node, npm, node_env = node_commands(staging)
        versions = node_versions(staging)
        private_write(staging / "package.json", jbytes({
            "name": "modelbench-playwright", "version": "1.0.0", "private": True,
            "dependencies": {MCP: MCP_VERSION},
        }))
        checked([npm, "install", "--package-lock-only", "--ignore-scripts",
                 "--no-audit", "--no-fund"], staging, node_env)
        digest = sha256((staging / "package-lock.json").read_bytes())
        if expected and digest != expected:
            raise Blocked("Fresh npm lockfile not equal to the coordinator-approved SHA256")
        checked([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"], staging, node_env)
        cli = staging / "node_modules" / "playwright" / "cli.js"
        if not cli.is_file():
            raise Blocked("Matching Playwright browser installer missing")
        env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(staging / "browsers")}
        if deps:
            if os.geteuid() == 0:
                prefix = []
            elif shutil.which("sudo"):
                prefix = ["sudo"]
            else:
                raise Blocked("Explicit system dependencies requested but sudo/root unavailable")
            checked(prefix + [node, str(cli), "install-deps", "chromium"], staging,
                    {**env, **node_env}, 1200)
        checked([node, str(cli), "install", "chromium"], staging,
                {**env, **node_env}, 1200)
        browser = browser_smoke(staging)  # Offline, data: URL only.
        private_write(staging / "stamp.json", jbytes({
            "schema": 1, "lock_sha256": digest, "mcp_version": MCP_VERSION,
            "arch": platform.machine(), "os": platform.system(),
            "chromium_version": browser["version"], **versions,
        }))
        if root.exists():
            raise Blocked("Destination appeared during installation; refuse overwrite")
        staging.rename(root)
        return {"action": "INSTALLED", **verify(root, expected)}
    finally:
        if staging.exists():
            shutil.rmtree(staging)  # Only this invocation's private staging directory.


def deep_research_check(source: Path) -> dict:
    """Check an existing canonical Deep-Research tree; do not install or expose it."""
    validator = source / "scripts" / "validate_coverage.py"
    if not source.is_dir() or not validator.is_file() or validator.is_symlink():
        raise Blocked("Canonical Deep-Research scripts/validate_coverage.py not found")
    digest = sha256(validator.read_bytes())
    return {"status": "SOURCE_CHECKED_ONLY", "root": str(source),
            "validator_sha256": digest, "mcp_tools_enabled": False,
            "note": "A separate pinned tool/service and identical MCP schema are required before trials"}


def hpi_pairs() -> list[tuple[str, str]]:
    return [(name, blob) for case, (body, ann) in HPI_TRAIN.items()
            for name, blob in ((case, body), (case + ".ann", ann))]


def rights_record(path: str | None) -> dict:
    if not path:
        raise Blocked("HPI import requires local --rights-record (no automatic corpus download)")
    p = Path(path).expanduser().resolve(strict=True)
    if PROJECT in p.parents and PROJECT / "build" not in p.parents:
        raise Blocked("Rights records must stay outside tracked repository files")
    data = json.loads(p.read_text(encoding="utf-8"))
    if (data.get("approved") is not True or data.get("source_revision") != HPI_REF
            or data.get("usage") != "internal-train-only"
            or not data.get("reviewer") or not data.get("legal_basis")):
        raise Blocked("Rights/privacy record lacks approved TRAIN-only scope and reviewer")
    return {"rights_record_sha256": sha256(p.read_bytes())}


def verify_annotation(text: str, content: bytes) -> dict:
    ann = json.loads(content.decode("utf-8-sig"))
    body = ann.get("text")
    zones = ann.get("denotations")
    if not isinstance(body, str) or not isinstance(zones, list):
        raise Blocked("Malformed HPI annotation structure")
    for x in zones:
        start, end = x.get("start"), x.get("end")
        if (type(start) is not int or type(end) is not int
                or not 0 <= start <= end <= len(body)
                or body[start:end] != x.get("text")):
            raise Blocked("HPI annotation offset/text mismatch")
    return {"zone_count": len(zones), "historical_headers": sum(x.get("type") == "Header" for x in zones),
            "annotated_text_equals_source_file": body == text,
            "coordinate_basis": "ann.text Unicode codepoints; never assume raw EML byte offsets"}


def verify_hpi(folder: Path) -> dict:
    manifest_file = folder / "manifest.json"
    if not manifest_file.is_file():
        raise Blocked("Missing HPI manifest")
    metadata = json.loads(manifest_file.read_text(encoding="utf-8"))
    if metadata.get("source_revision") != HPI_REF or metadata.get("scope") != "ASF/TRAIN":
        raise Blocked("Wrong HPI commit or partition")
    if set(metadata.get("files", {})) != {name for name, _ in hpi_pairs()}:
        raise Blocked("HPI file inventory incomplete or expanded unexpectedly")
    expected = dict(hpi_pairs())
    cases = []
    for case in HPI_TRAIN:
        raw = (folder / case).read_bytes()
        ann = (folder / (case + ".ann")).read_bytes()
        for name, data in ((case, raw), (case + ".ann", ann)):
            if blobsha(data) != expected[name] or sha256(data) != metadata["files"][name]["sha256"]:
                raise Blocked("HPI file checksum mismatch: " + name)
        cases.append(verify_annotation(raw.decode("utf-8-sig"), ann))
    return {"status": "VERIFIED", "scope": "ASF/TRAIN", "pairs": len(cases),
            "header_annotations": sum(x["historical_headers"] for x in cases),
            "source_vs_annotation_text_mismatch": sum(not x["annotated_text_equals_source_file"] for x in cases),
            "manifest_sha256": sha256(manifest_file.read_bytes())}


def hpi_import(folder: Path, approval: dict) -> dict:
    if folder.exists():
        summary = verify_hpi(folder)
        original_approval = json.loads((folder / "manifest.json").read_text()).get("rights_record_sha256")
        if original_approval != approval["rights_record_sha256"]:
            raise Blocked("Existing HPI TRAIN data belong to a different rights approval")
        return {"action": "REUSED", **summary}
    folder.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".hpi-owned-", dir=folder.parent))
    os.chmod(stage, 0o700)
    try:
        data_index = {}
        for name, expected in hpi_pairs():
            url = (f"https://raw.githubusercontent.com/{HPI_REPO}/{HPI_REF}/"
                   f"Datasets/ASF/train/{name}")
            req = urllib.request.Request(url, headers={"User-Agent": "ModelBench-TRAIN-Importer"})
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.geturl() != url:
                    raise Blocked("HPI redirect changed approved source URL")
                content = response.read(250001)
            if len(content) > 250000 or blobsha(content) != expected:
                raise Blocked("HPI source blob invalid: " + name)
            private_write(stage / name, content)
            data_index[name] = {"source_url": url, "sha256": sha256(content),
                                "git_blob_sha1": expected, "bytes": len(content)}
        private_write(stage / "manifest.json", jbytes({
            "schema_version": 1, "source_revision": HPI_REF, "scope": "ASF/TRAIN",
            "rights_record_sha256": approval["rights_record_sha256"],
            "files": data_index, "access": "private-coordinator-only",
        }))
        verify_hpi(stage)
        if folder.exists():
            raise Blocked("HPI destination appeared during download; refuse overwrite")
        stage.rename(folder)
        return {"action": "IMPORTED", **verify_hpi(folder)}
    finally:
        if stage.exists():
            shutil.rmtree(stage)



def hpi_bundle(folder: Path, output: Path, approval: dict, worker_approved: bool) -> dict:
    """Create identical visible TRAIN labels for workers, only after privacy review."""
    if not worker_approved:
        raise Blocked("Explicit worker disclosure approval required (--approve-worker-disclosure)")
    summary = verify_hpi(folder)
    original_approval = json.loads((folder / "manifest.json").read_text()).get("rights_record_sha256")
    if original_approval != approval["rights_record_sha256"]:
        raise Blocked("TRAIN bundle rights approval differs from imported dataset")
    if PROJECT in output.parents and PROJECT / "build" not in output.parents:
        raise Blocked("TRAIN bundle cannot be written in tracked repository")
    records = []
    for case in sorted(HPI_TRAIN):
        ann = json.loads((folder / (case + ".ann")).read_text(encoding="utf-8-sig"))
        # Offsets refer to the authoritative annotated text, not source EML bytes.
        labels = [{"type": z["type"], "start": z["start"], "end": z["end"]}
                  for z in ann["denotations"]]
        records.append({"case_id": case, "text": ann["text"], "labels": labels,
                        "coordinate_basis": "annotated_text_codepoints"})
    content = b"".join((json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n").encode()
                       for item in records)
    digest = sha256(content)
    if output.exists():
        if sha256(output.read_bytes()) != digest:
            raise Blocked("Existing TRAIN bundle differs; refuse overwrite")
        action = "REUSED_VERIFIED"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        private_write(output, content)
        action = "CREATED"
    return {"action": action, "bundle_sha256": digest, "cases": len(records),
            "source_manifest_sha256": summary["manifest_sha256"],
            "rights_record_sha256": approval["rights_record_sha256"],
            "coordinate_basis": "ann.text codepoints", "split": "TRAIN_ONLY"}


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT_DEFAULT)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("plan")
    p = actions.add_parser("install")
    p.add_argument("--expected-lock-sha256")
    p.add_argument("--with-system-deps", action="store_true",
                   help="Explicit opt-in: install Chromium OS dependencies with root/sudo")
    p = actions.add_parser("greenfield")
    p.add_argument("--expected-lock-sha256")
    p.add_argument("--with-system-deps", action="store_true",
                   help="Explicit opt-in: system Chromium dependencies with root/sudo")
    p = actions.add_parser("verify")
    p.add_argument("--expected-lock-sha256")
    for command in ("mcp-config", "mcp-serve"):
        p = actions.add_parser(command)
        p.add_argument("--expected-lock-sha256")
        p.add_argument("--network-isolated", action="store_true",
                       help="Coordinator attests external sandbox and egress controls")
    p = actions.add_parser("deep-research-check")
    p.add_argument("--source", type=Path, required=True,
                   help="Existing canonical Deep-Research repository; no automatic install")
    actions.add_parser("hpi-plan")
    bundle = actions.add_parser("hpi-bundle")
    bundle.add_argument("--data-dir", type=Path, default=HPI_DEFAULT)
    bundle.add_argument("--output", type=Path, default=PROJECT / "build" / "hpi-train-visible.jsonl")
    bundle.add_argument("--rights-record", required=True)
    bundle.add_argument("--approve-worker-disclosure", action="store_true")
    for command in ("hpi-import", "hpi-verify"):
        p = actions.add_parser(command)
        p.add_argument("--data-dir", type=Path, default=HPI_DEFAULT)
        if command == "hpi-import":
            p.add_argument("--rights-record")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    try:
        if args.action == "plan":
            result = {"mcp": f"{MCP}@{MCP_VERSION}", "root": str(root),
                      "portable_node_pin": NODE_PIN, "greenfield_supported": True,
                      "allowed_origins": ALLOWED_ORIGINS, "hpi_ref": HPI_REF,
                      "warning": "MCP origin filtering is NOT a network security boundary"}
        elif args.action in ("install", "greenfield"):
            result = install(root, args.expected_lock_sha256, args.with_system_deps,
                             greenfield=args.action == "greenfield")
        elif args.action == "verify":
            result = verify(root, args.expected_lock_sha256)
        elif args.action in ("mcp-config", "mcp-serve"):
            if not args.network_isolated:
                raise Blocked("Coordinator has not attested external network/sandbox isolation")
            fingerprint = verify(root, args.expected_lock_sha256, smoke=False)["lock_sha256"]
            command = [str(root / "node_modules" / "@playwright" / "mcp" / "cli.js"),
                       "--headless", "--browser", "chromium", "--isolated",
                       "--block-service-workers", "--allowed-origins", ";".join(ALLOWED_ORIGINS)]
            if args.action == "mcp-config":
                result = {"mcpServers": {"playwright": {
                    "command": sys.executable,
                    "args": [str(Path(__file__).resolve()), "--root", str(root),
                             "mcp-serve", "--expected-lock-sha256", fingerprint,
                             "--network-isolated"],
                }}}
            else:
                node, _, base_env = node_commands(root)
                env = {**base_env, "PLAYWRIGHT_BROWSERS_PATH": str(root / "browsers")}
                os.execvpe(node, [node, *command], env)
                raise AssertionError("execvpe returned")
        elif args.action == "deep-research-check":
            result = deep_research_check(args.source.expanduser().resolve(strict=True))
        elif args.action == "hpi-plan":
            result = {"scope": "ASF/TRAIN", "source_revision": HPI_REF,
                      "sample_ids": list(HPI_TRAIN), "file_pairs": len(HPI_TRAIN),
                      "data_permission": "explicit legal/privacy review required"}
        elif args.action == "hpi-import":
            result = hpi_import(args.data_dir.expanduser().resolve(),
                                rights_record(args.rights_record))
        elif args.action == "hpi-verify":
            result = verify_hpi(args.data_dir.expanduser().resolve())
        elif args.action == "hpi-bundle":
            approval = rights_record(args.rights_record)
            result = hpi_bundle(args.data_dir.expanduser().resolve(),
                                args.output.expanduser().resolve(), approval,
                                args.approve_worker_disclosure)
        else:
            raise Blocked("Unknown action")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (Blocked, OSError, ValueError, KeyError, subprocess.TimeoutExpired,
            urllib.error.URLError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
