#!/usr/bin/env python3
"""Kolibri-only measurements; no installation, model restart or hosted fallback.

scripts/kolibri-benchmark.py
|-- plan      validate the profile and list four dimensions, without inference
|-- run       exact identity -> speed -> quality -> tools -> isolated coding
|   |-- state.json       checkpoint before every model request
|   |-- cases/           request, response, objective assessment and hashes
|   `-- report.md/json   results, measured scope and missing evidence
`-- verify    check every retained evidence hash without making model requests

Python 3.10+; standard library only. Use --smoke for a small transport check.
The built-in P1-P3 tasks are diagnostics, not AIPerf/IFEval/BFCL scores.
P4 delegates to the existing isolated Melusense pipeline; it is never simulated.
"""
import argparse
import json
from pathlib import Path
import sys

from modelbench import common as c
from modelbench import kolibri


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['plan', 'run', 'verify'])
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[1] / 'config/kolibri-benchmark.json')
    parser.add_argument('--run-id')
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'build/kolibri-benchmark')
    parser.add_argument('--smoke', action='store_true', help='One seed, concurrency 1, two quality cases and one real tool round-trip; P4 not requested')
    args = parser.parse_args(argv)
    try:
        profile = c.read(args.config)
        kolibri.validate(profile)
        if args.action == 'plan':
            result = kolibri.plan(profile, args.smoke)
        else:
            c.require(args.run_id is not None, '--run-id is required for run/verify')
            if args.action == 'verify':
                result = kolibri.verify(args.output, args.run_id, profile, args.smoke)
            else:
                result = kolibri.run(profile, args.output, args.run_id, args.smoke)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if result['status'] in ('PLAN_ONLY', 'VERIFIED', 'COMPLETED') else 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({'status': 'INTERRUPTED', 'reason': 'Any in-flight request remains uncertain; no automatic replay.'}), file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
