#!/usr/bin/env python3
"""Read-only starter check. Run as checkout owner; no network or installation.
Inputs: this checkout. Output: structural PASS or failure; never parser PASS.
Flow: required files -> JSON budgets -> Markdown targets -> forbidden payloads.
"""
import json
import pathlib
import re
import sys
ROOT = pathlib.Path(__file__).resolve().parents[1]
errors = []
for path in ["README.md", "MANIFEST.md", "AGENTS.md", "TASKS.md", "docs/contract.md", "docs/evaluation.md", "docs/RESEARCH_TOOLS.md", "docs/HPI_TRAIN.md", "config/budget.json", "melusense/api.py", "tools/greenfield.py", "tests/test_greenfield.py", "tests/fixtures.json"]:
    if not (ROOT / path).is_file():
        errors.append("missing " + path)
for p in ROOT.rglob("*"):
    if any(part in {".git", "build", "__pycache__"} for part in p.relative_to(ROOT).parts):
        continue
    if p.is_file() and p.suffix in {".eml", ".mbox", ".key", ".pem", ".gguf", ".safetensors", ".ann"}:
        errors.append("forbidden payload " + str(p.relative_to(ROOT)))
    if p.is_file() and p.suffix == ".md":
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", p.read_text()):
            if "://" not in link and not (p.parent / link.split("#")[0]).exists():
                errors.append("broken link " + link)
try:
    budget = json.loads((ROOT / "config/budget.json").read_text())
    assert budget["repetitions"] == len(budget["seeds"]) == 3
    assert budget["context_tokens"] == 262144
except Exception as exc:
    errors.append("invalid budget: " + type(exc).__name__)
print("\n".join(errors) if errors else "PASS: scaffold integrity only; parser remains unimplemented")
sys.exit(bool(errors))
