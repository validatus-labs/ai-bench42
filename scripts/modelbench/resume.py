"""Verified phase-attempt journal; never repeat an uncertain scored execution."""
from pathlib import Path
import re
import subprocess

from . import common as c

COMPLETE = {'PASS', 'NOT_REQUESTED', 'CANDIDATE_REJECTED', 'NOT_EVALUATED'}


def input_pins(value, label=''):
    rows = {}
    def visit(item, key):
        if isinstance(item, dict):
            if 'path' in item and 'sha256' in item:
                path = c.pin(item); rows[str(path)] = {'path': str(path), 'sha256': item['sha256']}
                if key in ('data_manifest', 'definition', 'qualification_report'):
                    visit(c.read(path), '')
            else:
                for name, child in item.items(): visit(child, name)
        elif isinstance(item, list):
            for child in item: visit(child, key)
    visit(value, label)
    return [rows[key] for key in sorted(rows)]


def snapshot(phase):
    return {key: value for key, value in phase.items()
            if key not in ('attempts', 'receipt_sha256')}


def evidence_path(folder, row):
    relative = Path(row['evidence_directory'])
    c.require(not relative.is_absolute() and '..' not in relative.parts,
              'Phase evidence must stay inside the experiment')
    path = c.safe(folder / relative)
    c.require(path.is_dir(), 'Missing phase evidence: ' + str(relative))
    return path


def check_receipt(folder, row, fingerprint):
    evidence = evidence_path(folder, row)
    receipt = c.read(evidence / 'receipt.json')
    c.require(c.digest(evidence / 'receipt.json') == row.get('receipt_sha256')
              and receipt['fingerprint'] == fingerprint
              and receipt['phase'] == snapshot(row)
              and receipt.get('evidence_sealed') is True, 'Phase receipt changed or unsealed: ' + row['id'])
    actual = c.inventory(evidence); actual.pop('receipt.json', None)
    c.require(actual == receipt['files'], 'Phase evidence changed: ' + row['id'])
    for item in row.get('result', {}).get('external_evidence', []): c.pin(item)


def seal(folder, phase, fingerprint):
    evidence = evidence_path(folder, phase)
    phase['finished_at'] = c.timestamp()
    phase['effects_started'] = (evidence / 'effects-started.json').exists()
    c.require(not (evidence / 'receipt.json').exists(), 'Never overwrite a sealed attempt')
    files = c.inventory(evidence)
    c.save(evidence / 'receipt.json', {'phase': snapshot(phase), 'fingerprint': fingerprint,
                                     'files': files, 'evidence_sealed': True})
    phase['receipt_sha256'] = c.digest(evidence / 'receipt.json')
    phase.setdefault('attempts', []).append({key: value for key, value in phase.items() if key != 'attempts'})


def no_live_commands(evidence):
    """A dead coordinator does not prove its child command stopped."""
    for path in evidence.rglob('command.json'):
        command = c.read(path)
        if command.get('status') != 'RUNNING': continue
        pid = command.get('pid')
        c.require(type(pid) is int and pid > 1 and command.get('process_start_ticks')
                  and command.get('boot_id'), 'Uncertain command launch; operator review required: ' + str(path))
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        if boot != command['boot_id']: continue
        proc = Path('/proc') / str(pid) / 'stat'
        if proc.exists():
            fields = proc.read_text().rsplit(')', 1)[1].split()
            c.require(fields[19] != command['process_start_ticks'],
                      'Previous command is still alive; wait before resuming: ' + str(pid))
        # An orphan descendant in the recorded process group also prevents reuse.
        for child in Path('/proc').iterdir():
            if not child.name.isdigit(): continue
            try: fields = (child / 'stat').read_text().rsplit(')', 1)[1].split()
            except (FileNotFoundError, ProcessLookupError, PermissionError): continue
            c.require(fields[2] != str(pid), 'Previous command descendants remain alive; operator review required')


def verify(folder, state, recover=False):
    for phase in state['phases']:
        attempts = phase.get('attempts', [])
        for number, row in enumerate(attempts, 1):
            c.require(row.get('attempt') == number and row['id'] == phase['id'], 'Attempt journal is inconsistent')
            check_receipt(folder, row, state['fingerprint'])
        if phase['status'] == 'PENDING':
            c.require(not attempts and not phase.get('evidence_directory'), 'Pending phase has unexpected evidence')
            continue
        if phase['status'] == 'RUNNING' and recover:
            evidence = evidence_path(folder, phase)
            receipt_path = evidence / 'receipt.json'
            if receipt_path.exists():
                receipt = c.read(receipt_path); row = receipt['phase']
                c.require(all(row.get(key) == phase.get(key) for key in
                              ('id', 'kind', 'name', 'attempt', 'started_at', 'evidence_directory')),
                          'Interrupted receipt does not match the active attempt')
                row = dict(row, receipt_sha256=c.digest(receipt_path))
                check_receipt(folder, row, state['fingerprint'])
                phase.update(row); phase.setdefault('attempts', []).append(dict(row))
            else:
                if phase['id'] != 'deploy': no_live_commands(evidence)
                phase.update(status='INTERRUPTED', reason='Coordinator stopped before sealing the attempt')
                seal(folder, phase, state['fingerprint'])
            c.save(folder / 'state.json', state)
        if state.get('schema_version') == 1:
            check_receipt(folder, phase, state['fingerprint'])
        else:
            c.require(phase.get('attempts') and phase['attempts'][-1] ==
                      {key: value for key, value in phase.items() if key != 'attempts'},
                      'Latest phase and attempt journal disagree')


def deployment_result(folder, phase):
    """Reattach to native supervisor evidence; never submit a duplicate active job."""
    if not phase.get('effects_started'): return None
    evidence = evidence_path(folder, phase)
    details = c.read(evidence / 'bootstrap-job.json')
    c.require(re.fullmatch(r'modelbench-bootstrap-[A-Za-z0-9_-]+', details['unit']), 'Invalid retained bootstrap unit')
    probe = subprocess.run(['/usr/bin/systemctl', 'show', details['unit'], '--property=ActiveState', '--value'],
                           capture_output=True, text=True, timeout=15)
    c.require(probe.returncode == 0 and probe.stdout.strip() in ('inactive', 'failed'),
              'Native bootstrap is active or its state is unavailable; wait, then repeat the same command')
    request = c.read(details['request']); receipt = c.read(details['receipt'])
    c.require(receipt.get('fingerprint') == request['fingerprint'] and
              receipt.get('status') in ('COMPLETED', 'FAILED'), 'Native bootstrap outcome is uncertain; inspect retained job')
    if receipt['status'] == 'FAILED': return None
    return {'status': 'PASS', 'scope': 'Recovered completed native bootstrap; no second deployment submitted',
            'external_evidence': [{'path': details[key], 'sha256': c.digest(details[key])}
                                  for key in ('request', 'receipt', 'log')]}


def may_retry(folder, phase):
    c.require(phase['status'] not in COMPLETE, 'Completed phase cannot be retried')
    if phase['id'] == 'deploy': return deployment_result(folder, phase)
    evidence=evidence_path(folder,phase)
    reference=evidence/'native-reference.json'
    if phase['id'].startswith('coding-') and reference.exists():
        row=c.read(reference)
        c.require(row.get('schema_version')==1 and row.get('seed')==int(phase['id'].rsplit('-',1)[1]),'Retained native continuation identity differs')
        for key in ['controller','configuration','profile','record']:c.pin(row[key])
        for key in ['capture_adapter','capture_profile']:
            if key in row:c.pin(row[key])
        no_live_commands(evidence)
        # The exact native controller reuses its existing start intent; this
        # permits observation/finish, never a second qualification or prompt.
        return None
    c.require(not phase.get('effects_started'),
              'Execution may already have consumed a trial budget; retain this run and review before a new trial')
    no_live_commands(evidence_path(folder, phase))
    return None


def begin(folder, phase):
    attempts = phase.get('attempts', [])
    number = len(attempts) + 1
    evidence = c.safe(folder / 'phases' / phase['id'] / ('attempt-' + str(number).zfill(4)))
    c.require(not evidence.exists(), 'Unexpected attempt directory; preserve and inspect it')
    c.private_directory(evidence)
    identity = {key: phase[key] for key in ('id', 'name', 'kind')}
    phase.clear(); phase.update(identity, attempts=attempts, attempt=number, status='RUNNING',
                                started_at=c.timestamp(), evidence_directory=str(evidence.relative_to(folder)))
    return evidence
