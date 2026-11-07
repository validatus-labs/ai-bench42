"""Character span scorer and bounded Docker execution, ported from AI-Model agentbench.
No labels, reference or credential mounts enter the candidate container.
This implementation requires independent held-out qualification before use.
"""
import base64,hashlib,json,os,re,resource,subprocess,tempfile,time,uuid
from pathlib import Path
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def tree(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in a candidate export")
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if any(p in (".git", "__pycache__", ".venv") for p in path.relative_to(root).parts):
                raise ValueError("Git metadata/cache/environment in candidate export")
            if path.stat().st_size > 2 * 1024 * 1024 or len(result) >= 500:
                raise ValueError("Candidate file/count budget exceeded")
            result[rel] = sha(path)
    return result

def docker_command(config, candidate, name, writable=False):
    sandbox = config["sandbox"]
    command = ["sudo", "-n", "docker", "run", "--rm", "-i", "--name", name,
               "--log-driver", "none",
               "--platform", sandbox["platform"], "--network", "none", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges:true", "--read-only", "--user", str(os.getuid())+":"+str(os.getgid()),
               "--memory", sandbox["memory"], "--cpus", sandbox["cpus"], "--pids-limit", str(sandbox["pids_limit"]),
               "--tmpfs", "/tmp:rw,nosuid,nodev,size=128m,mode=1777", "--workdir", "/candidate",
               "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
               "--mount", "type=bind,src=" + str(candidate) + ",dst=/candidate" + ("" if writable else ",readonly")]
    if writable:
        for rel in config["protected_paths"]:
            rel = rel.rstrip("/")
            command += ["--mount", "type=bind,src=" + str(candidate / rel) + ",dst=/candidate/" + rel + ",readonly"]
    return command + [sandbox["image"], "python", "-B", "-c"]

def container_python(config, candidate, program, payload="", writable=False, timeout=120):
    name = "ai-model-agent-eval-" + uuid.uuid4().hex
    started = time.monotonic()
    try:
        # Anonymous bounded capture: neither Docker nor journald retains mail output.
        with tempfile.TemporaryFile(dir=str(candidate.parent), mode="w+b") as capture:
            result = subprocess.run(docker_command(config, candidate, name, writable) + [program],
                                    input=payload, text=True, stdout=capture, stderr=subprocess.DEVNULL, timeout=timeout,
                                    preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (4194304, 4194304)))
            capture.seek(0)
            output = capture.read(4194305)
        if len(output) >= 4194304:
            raise RuntimeError("Candidate output limit exceeded")
        return result.returncode, output.decode("utf-8", errors="strict"), time.monotonic() - started
    finally:
        subprocess.run(["sudo", "-n", "docker", "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)

def positions(spans, length):
    result = set()
    for span in spans:
        if type(span["start"]) is not int or type(span["end"]) is not int or not 0 <= span["start"] < span["end"] <= length:
            raise ValueError("Invalid original-text offsets")
        result.update(range(span["start"], span["end"]))
    return result

def score_case(gold, result):
    text = result["text"]
    if hashlib.sha256(text.encode()).hexdigest() != gold["text_sha256"] or result["source_sha256"] != gold["source_sha256"] or result["source_kind"] != gold["source_kind"] or result["schema_version"] != 1:
        raise ValueError("Candidate changed canonical input/offset basis")
    if any(not isinstance(result.get(k), list) for k in ("candidates", "authorized_removals", "attachments", "warnings")) or any(not s.get("evidence") for s in result["candidates"]):
        raise ValueError("Candidate API metadata contract violated")
    length = len(text)
    scores = {}
    for kind in ("reply", "forward", "signature", "footer"):
        expected = positions([s for s in gold["candidates"] if s["kind"] == kind], length)
        proposed = positions([s for s in result["candidates"] if s["kind"] == kind], length)
        scores[kind] = {"tp": len(expected & proposed), "fp": len(proposed - expected), "fn": len(expected - proposed)}
    if any(s["kind"] not in scores for s in result["candidates"]):
        raise ValueError("Unknown candidate kind")
    allowed = positions(gold["authorized_removals"], length)
    removed = positions(result["authorized_removals"], length)
    current = positions(gold["current_body_spans"], length)
    scores["removal"] = {"tp": len(allowed & removed), "fp": len(removed - allowed), "fn": len(allowed - removed)}
    scores["current_body_loss_characters"] = len(removed & current)
    return scores

def gold_records(path):
    seen = set()
    with path.open() as stream:
        for line in stream:
            if len(line.encode()) > 2 * 1024 * 1024:
                raise ValueError("Gold record exceeds evaluator input budget")
            gold = json.loads(line)
            if not isinstance(gold.get("id"), str) or not gold["id"] or gold["id"] in seen:
                raise ValueError("Gold IDs must be present and unique")
            seen.add(gold["id"])
            if gold["source_kind"] not in ("text", "eml") or type(gold["text_length"]) is not int or not 0 <= gold["text_length"] <= 1048576:
                raise ValueError("Invalid Gold source kind/length")
            raw = gold["text"].encode() if gold["source_kind"] == "text" else base64.b64decode(gold["eml_base64"], validate=True)
            if len(raw) > 1048576 or hashlib.sha256(raw).hexdigest() != gold["source_sha256"] or not re.fullmatch(r"[a-f0-9]{64}", gold["text_sha256"]):
                raise ValueError("Invalid Gold input hash/budget")
            if gold["source_kind"] == "text" and (len(gold["text"]) != gold["text_length"] or gold["source_sha256"] != gold["text_sha256"]):
                raise ValueError("Invalid original-text Gold basis")
            if any(s["kind"] not in ("reply", "forward", "signature", "footer") for s in gold["candidates"]):
                raise ValueError("Invalid Gold candidate kind")
            positions(gold["candidates"], gold["text_length"])
            if positions(gold["authorized_removals"], gold["text_length"]) & positions(gold["current_body_spans"], gold["text_length"]):
                raise ValueError("Gold authorizes current-body deletion")
            yield gold

CANDIDATE = '''import base64,json,sys
from melusense import detect_eml,detect_text
p=json.load(sys.stdin)
try:
 r=detect_eml(base64.b64decode(p['eml_base64']),locale=p['locale']) if p['source_kind']=='eml' else detect_text(p['text'],locale=p['locale'])
 print(json.dumps(r,ensure_ascii=False))
except BaseException: raise SystemExit(20)
'''
