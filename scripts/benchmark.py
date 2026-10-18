#!/usr/bin/env python3
"""One AI-Bench42 experiment: deployment, standard suites, coding and one report.

scripts/benchmark.py
|-- plan          show phases and missing target assets, no execution
|-- run           execute/reuse one fingerprint-bound experiment
|-- report        regenerate HTML from verified retained phase evidence
`-- pin-data      seal a prepared local task/tokenizer/dataset bundle
"""
import argparse
import json
import os
from pathlib import Path
import signal
import sys

from modelbench import common as c


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    actions = parser.add_subparsers(dest='action', required=True)
    for name in ('plan', 'run'):
        part = actions.add_parser(name)
        part.add_argument('--config', type=Path, required=True)
        if name == 'run':
            part.add_argument('--run-id', required=True)
            part.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'build/experiments')
    part = actions.add_parser('report'); part.add_argument('--run', type=Path, required=True)
    part = actions.add_parser('pin-data')
    part.add_argument('--root', type=Path, action='append', required=True)
    part.add_argument('--revision', required=True)
    part.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        c.require(os.getuid() != 0, 'Run as the normal coordinator, without sudo')
        if args.action == 'pin-data':
            c.require(args.revision not in ('', 'main', 'latest'), 'Use an exact source revision or reviewed bundle ID')
            c.require(not args.output.exists(), 'Do not overwrite a previous data manifest')
            files = []
            for root in args.root:
                root = c.safe(root)
                for path in sorted(root.rglob('*')):
                    if path.name.endswith('.lock') or '__pycache__' in path.parts: continue
                    c.require(not path.is_symlink(), 'Use a materialized data/tokenizer bundle without links')
                    c.require(path.name not in ('token', 'stored_tokens', '.netrc', '.env', '.git-credentials'),
                              'Credential files do not belong in a data bundle')
                    if path.is_file(): files.append({'path': str(path), 'sha256': c.digest(path), 'revision': args.revision})
            c.require(files and len(files) <= 100000, 'Empty/oversized data bundle')
            c.private_directory(args.output.absolute().parent)
            c.save(args.output, {'schema_version': 1, 'files': files})
            print(json.dumps({'path': str(args.output.absolute()), 'sha256': c.digest(args.output), 'files': len(files)}))
            return 0
        from modelbench import pipeline, report
        if args.action == 'report':
            folder = c.safe(args.run)
            with c.locked(folder / 'pipeline.lock'):
                state = c.read(folder / 'state.json')
                for phase in state['phases']:
                    if phase.get('evidence_directory'):
                        evidence = c.safe(folder / phase['evidence_directory'])
                        receipt = c.read(evidence / 'receipt.json')
                        recorded_phase = dict(phase); recorded_phase.pop('receipt_sha256', None)
                        c.require(receipt['phase'] == recorded_phase and receipt['fingerprint'] == state['fingerprint']
                                  and c.digest(evidence / 'receipt.json') == phase.get('receipt_sha256'), 'Phase receipt changed')
                        actual = c.inventory(evidence); actual.pop('receipt.json', None)
                        c.require(actual == receipt['files'], 'Phase evidence changed: ' + phase['id'])
                        for item in phase.get('result', {}).get('external_evidence', []): c.pin(item)
                result = report.render(folder, state)
        else:
            config = c.read(args.config)
            result = pipeline.plan(config) if args.action == 'plan' else pipeline.run(config, args.output, args.run_id)
        print(json.dumps(result if args.action == 'plan' else {'run_id': result['run_id'], 'status': result['status']}, indent=2))
        return 0 if args.action == 'plan' or result['status'] in ('COMPLETED', 'COMPLETED_WITH_SMOKE') else 2
    except KeyboardInterrupt:
        print(json.dumps({'status': 'INTERRUPTED', 'reason': 'Retained evidence is not automatically retried'}), file=sys.stderr)
        return 130
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    sys.exit(main())
