#!/usr/bin/env python3
"""Read-only C00 qualification; writes private coordinator evidence only.

Checks archive/run pins, toolchain and model identities, fresh namespace and
filesystem denials, broker peers, a real model-issued browser canary, and the
configured independent channel verifier. Does not install or repair anything.
Missing checks are BLOCKED. The worker never writes its own READY receipt.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import worker

CHECKS = {
    'kilo_identity_and_config', 'browser_node_mcp_identity', 'mcp_schema_parity',
    'headless', 'browser_sandbox', 'fresh_profile', 'service_workers_blocked',
    'downloads_uploads_denied', 'task_scoped_read_only_research',
    'public_https_allowed', 'private_ipv4_denied', 'private_ipv6_denied',
    'dns_rebinding_denied', 'redirect_to_private_denied', 'authenticated_pages_denied',
    'inference_transport_scoped', 'local_backend_identity', 'budgets_enforced',
    'model_issued_mcp_marker', 'browser_page_closed', 'browser_host_files_denied',
}
TTL_SECONDS = 900


def evidence_rows(rows, folder):
    worker.require(isinstance(rows, dict) and set(rows) == CHECKS, 'Independent channel verifier omitted required checks')
    result = {}
    for name, item in rows.items():
        worker.require(item.get('passed') is True, 'Channel qualification failed: ' + name)
        relative = item.get('evidence_file')
        worker.require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
                       and '..' not in Path(relative).parts, 'Invalid qualification evidence path')
        path = worker.private(folder / relative)
        worker.require(path.is_file() and path.stat().st_size <= 8 * 1024 * 1024
                       and worker.digest(path) == worker.pin(item.get('sha256')), 'Missing/changed channel evidence: ' + name)
        result[name] = {'passed': True, 'path': str(path), 'sha256': item['sha256']}
    return result


def verify_ready(receipt, record, run, config):
    worker.require(receipt.get('status') == 'READY' and receipt.get('fingerprint') == record['fingerprint'], 'No matching coordinator READY receipt')
    age = time.time() - receipt['created_unix']
    worker.require(0 <= age <= TTL_SECONDS, 'C00 expired; qualify again before starting the candidate')
    worker.require(receipt.get('preflight_sha256') == worker.digest(Path(__file__)), 'Preflight code changed')
    worker.require(receipt.get('boot_id') == Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'Host rebooted since qualification')
    worker.require(set(receipt.get('checks', {})) == CHECKS, 'Incomplete readiness receipt')
    for item in receipt['checks'].values():
        path = worker.private(item['path'])
        worker.require(item['passed'] is True and worker.digest(path) == item['sha256'], 'Qualification evidence changed')
    for key in ('canary', 'isolation', 'audit'):
        item = receipt[key]
        worker.require(worker.digest(worker.private(item['path'])) == item['sha256'], 'C00 evidence changed: ' + key)
    current_peers = {name: worker.peer(channel) for name, channel in config['channels'].items()}
    worker.require(current_peers == receipt['peers'], 'Channel process restarted/changed; qualify again')


def qualify(run, record, config, folder):
    challenge = os.urandom(24).hex()
    peers = {name: worker.peer(channel) for name, channel in config['channels'].items()}
    probe = worker.isolation_probe(run, record, config, folder, challenge)
    transcript = folder / 'canary.jsonl'
    # Canary is launched by us in exactly the same namespace/mount/transport
    # construction as the candidate, with a model-specific, fresh marker.
    before = {str(path.relative_to(run / 'workspace')): worker.digest(path)
              for path in (run / 'workspace/melusense').rglob('*') if path.is_file()}
    code = worker.execute(worker.command(run, record, config, 'canary', challenge), config,
                          min(record['budget']['wall_seconds'], 1200), transcript)
    worker.require(code == 0, 'Real Kilo/model canary failed; inspect the private transcript')
    worker.verify_frozen(run, record)
    after = {str(path.relative_to(run / 'workspace')): worker.digest(path)
             for path in (run / 'workspace/melusense').rglob('*') if path.is_file()}
    worker.require(before == after, 'Canary modified candidate source; preserve this run and prepare a new Run-ID')
    request = {
        'schema_version': 1, 'run_id': record['identity']['run_id'],
        'fingerprint': record['fingerprint'], 'challenge': challenge,
        'model': config['model'], 'budget': record['budget'], 'peers': peers,
        'policy': config['policy'], 'artifacts': config['artifacts'],
        'agent': config['agent'], 'channels': config['channels'],
        'canary_transcript': str(transcript), 'canary_sha256': worker.digest(transcript),
        'evidence_directory': str(folder), 'required_checks': sorted(CHECKS),
    }
    # This is an explicitly pinned coordinator adapter, never a candidate script
    # or a user-supplied booleans file. It must inspect broker controls and real
    # tool traces for this challenge; no generic Kilo event schema is invented.
    auditor = worker.checked_artifact(config['qualification'])
    worker.require(os.access(auditor, os.X_OK), 'Channel verifier must be directly executable')
    audit_log = folder / 'audit.json'
    code = worker.execute([str(auditor)], config, min(record['budget']['wall_seconds'], 300), audit_log,
                          worker.encoded(request), stderr_destination=folder / 'audit.stderr.log')
    worker.require(code == 0, 'Independent channel verification failed')
    audit = worker.read(audit_log)
    worker.require(audit.get('schema_version') == 1 and audit.get('status') == 'PASS'
                   and audit.get('fingerprint') == record['fingerprint'] and audit.get('challenge') == challenge,
                   'Channel proof is missing or belongs to another run/challenge')
    worker.require(audit.get('canary_sha256') == request['canary_sha256'] and audit.get('model') == config['model'], 'Canary/model evidence mismatch')
    checks = evidence_rows(audit['checks'], folder)
    worker.require(peers == {name: worker.peer(channel) for name, channel in config['channels'].items()}, 'Channel process changed during qualification')
    worker.verify_frozen(run, record)
    return {
        'status': 'READY', 'fingerprint': record['fingerprint'], 'created_unix': time.time(),
        'preflight_sha256': worker.digest(Path(__file__)),
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        'checks': checks, 'peers': peers,
        'canary': {'path': str(transcript), 'sha256': worker.digest(transcript)},
        'isolation': {'path': str(folder / 'isolation.json'), 'sha256': probe['sha256']},
        'audit': {'path': str(audit_log), 'sha256': worker.digest(audit_log)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--toolchain', required=True, type=Path)
    args = parser.parse_args()
    run = None
    folder = None
    try:
        worker.require(os.getuid() != 0, 'Run as the normal coordinator, not root')
        # Retain BLOCKED evidence even when the toolchain has not been provisioned.
        run = worker.private(args.run)
        with worker.locked(run):
            worker.require(not (run / 'candidate-start.json').exists(), 'Candidate already started; C00 cannot be rerun to relabel that attempt')
            folder = run / ('c00-' + str(time.time_ns())); folder.mkdir(mode=0o700)
            previous = run / 'readiness.json'
            if previous.exists():
                # Never retain an old green decision when requalification fails.
                previous.rename(folder / 'previous-readiness.json')
            _, record, config = worker.load_run(run, args.toolchain)
            with worker.toolchain_leases(config):
                result = qualify(run, record, config, folder)
            worker.write(folder / 'receipt.json', result)
            worker.write(run / 'readiness.json', result)
            print(json.dumps({'status': 'READY', 'run': str(run), 'receipt': str(folder / 'receipt.json')}))
            return 0
    except (OSError, ValueError, KeyError, TypeError, worker.Blocked, subprocess.SubprocessError) as exc:
        result = {'status': 'BLOCKED', 'reason': str(exc), 'created_unix': time.time()}
        if folder is not None:
            worker.write(folder / 'blocked.json', result)
        print(json.dumps(result), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
