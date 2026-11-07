#!/usr/bin/env python3
"""Read-only privacy gate for publication source; no installation or edits.

Checks: source payloads -> credentials -> actual network identities -> email data.
Model/tool versions, hashes, metrics, Spark identity and account/home paths are
valid reproducibility metadata. Generated runtime data is never a source release.
This gate complements secret scanners and human review; it does not clear Git/PR
history, attachments, generated logs or all possible confidential prose.
"""
import argparse
import ipaddress
from pathlib import Path
import re
import sys

OMIT = {'.git', 'build', '__pycache__', '.pytest_cache', '.venv', 'node_modules'}
FORBIDDEN = {'.eml', '.mbox', '.ann', '.pem', '.key', '.safetensors', '.gguf', '.sqlite', '.db', '.pyc'}
NETWORK_TESTS = {'tools/worker_inner.py', 'tools/browser_inner.py', 'tools/native_controls.py',
                 'scripts/modelbench/test_native_browser.py', 'scripts/verify-publication.py'}
PUBLIC_EMAIL_DOMAINS = {'example.com', 'example.net', 'example.org', 'example.invalid', 'users.noreply.github.com'}


def check(root, denied=()):
    errors = []
    for file in sorted(root.rglob('*')):
        rel = file.relative_to(root)
        if any(part in OMIT for part in rel.parts):
            continue
        if file.is_symlink():
            errors.append((str(rel), 0, 'source symlink requires review'))
            continue
        if not file.is_file():
            continue
        if file.suffix.lower() in FORBIDDEN or file.name in {'.env', 'id_rsa', 'id_ed25519'}:
            errors.append((str(rel), 0, 'private payload type'))
        try:
            text = file.read_bytes().decode('utf-8')
        except UnicodeError:
            errors.append((str(rel), 0, 'unindexed binary'))
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if any(value.casefold() in line.casefold() for value in denied):
                errors.append((str(rel), number, 'denied confidential identifier'))
            if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', line):
                errors.append((str(rel), number, 'private key material'))
            if re.search(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b|\bgh[pousr]_[A-Za-z0-9]{36,}\b', line):
                errors.append((str(rel), number, 'credential pattern'))
            for value in re.findall(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', line):
                try:
                    ip = ipaddress.ip_address(value)
                except ValueError:
                    continue
                documentation = any(ip in ipaddress.ip_network(net) for net in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24'))
                synthetic = str(rel) in NETWORK_TESTS and value in {'10.0.0.1', '169.254.169.254'}
                if not (ip.is_loopback or ip.is_unspecified or documentation or synthetic):
                    errors.append((str(rel), number, 'non-example IPv4 address'))
            for value in re.findall(r'(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.]*(?![\w:])', line):
                try:
                    ip = ipaddress.IPv6Address(value)
                except ValueError:
                    continue
                if not (ip.is_loopback or ip.is_unspecified or ip in ipaddress.ip_network('2001:db8::/32')):
                    errors.append((str(rel), number, 'non-example IPv6 address'))
            for value in re.findall(r'(?<![0-9a-fA-F:])(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}(?![0-9a-fA-F:])', line):
                if value != '00:00:00:00:00:00':
                    errors.append((str(rel), number, 'MAC address requires review'))
            for value in re.findall(r'[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', line):
                domain = value.rsplit('@', 1)[1].lower()
                service = domain.endswith('.service') and '/systemd/' in str(rel)
                synthetic = value == 'dummy@docs.python.org' and str(rel) in {'tools/native_controls.py', 'scripts/modelbench/test_native_controls.py', 'scripts/verify-publication.py'}
                git_transport = value.split('@', 1)[0] == 'git' and domain == 'github.com' and bool(re.search(r'git@[A-Za-z0-9.-]+:[A-Za-z0-9_.-]+/', line))
                if not (domain in PUBLIC_EMAIL_DOMAINS or service or synthetic or git_transport):
                    errors.append((str(rel), number, 'email address requires review'))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--deny-file', type=Path, help='optional private identifiers, one per line; values are never printed')
    args = parser.parse_args()
    denied = [line.strip() for line in args.deny_file.read_text().splitlines() if line.strip()] if args.deny_file else []
    errors = check(args.root.resolve(), denied)
    for path, number, reason in errors:
        print(f'[FAIL] {path}:{number}: {reason}')
    print('FAIL' if errors else 'PASS: source privacy gate; history and confidential-prose review remain separate')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
