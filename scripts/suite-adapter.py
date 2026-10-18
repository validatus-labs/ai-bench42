#!/usr/bin/env python3
"""Run pinned official-suite commands and project their native JSON scores.

suite-adapter.py
|-- definition   reviewed runtime, script pins, argument arrays and result schema
|-- commands     generation/scoring steps; no shell, downloads or hidden retries
`-- receipt      request-bound metrics plus hashed native evidence for the report
"""
import argparse
import json
from pathlib import Path
import signal
import sys

from modelbench import common as c, adapters


def pointer(value, expression):
    c.require(isinstance(expression, str) and expression.startswith('/'), 'Use a JSON pointer into the native score file')
    for part in expression[1:].split('/'):
        key = part.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--result', required=True, type=Path)
    parser.add_argument('--definition', required=True, type=Path)
    args = parser.parse_args()
    try:
        request = c.read(args.request); definition = c.read(args.definition)
        c.require(definition['schema_version'] == 1 and definition['benchmark'] == request['benchmark'], 'Wrong suite definition')
        c.require(c.digest(args.definition) == request['definition_sha256'], 'Suite definition changed')
        checksum = request.pop('request_sha256')
        c.require(c.fingerprint(request) == checksum, 'Adapter request fingerprint differs')
        request['request_sha256'] = checksum
        folder = c.safe(args.result).parent
        c.require(not args.result.exists(), 'A score receipt already exists')
        python = adapters.runtime(definition['runtime'], folder / 'runtime')
        artifacts = {str(c.pin(item)) for item in definition['artifacts']}
        values = {'python': str(python), 'model': request['model']['id'], 'base_url': request['model']['base_url'],
                  'seed': str(request['seed']), 'output': str(folder), 'request': str(args.request),
                  'candidate': request.get('candidate', {}).get('path', '')}
        env = c.environment(c.private_directory(folder / 'home'))
        env.update(OPENAI_BASE_URL=values['base_url'], OPENAI_API_BASE=values['base_url'])
        c.require(definition['commands'], 'No suite generation/scoring commands configured')
        for index, command in enumerate(definition['commands']):
            argv = []
            for part in command['argv']:
                for key, value in values.items(): part = part.replace('{' + key + '}', value)
                argv.append(part)
            c.require(argv[0] == str(python) or argv[0] in artifacts, 'Command executable is not pinned')
            # Python scripts named directly must also be pinned. Modules are bound by runtime lock/version.
            if argv[0] == str(python):
                for argument in argv[1:]:
                    if argument.endswith('.py'):
                        c.require(argument in artifacts, 'Suite Python script is not pinned')
            adapters.successful(c.execute(argv, folder / ('suite-' + str(index)), command['timeout_seconds'], env=env))
        path = Path(definition['result']['file'])
        c.require(not path.is_absolute() and '..' not in path.parts, 'Native result must be within the adapter output directory')
        native = c.read(folder / path)
        count = pointer(native, definition['result']['samples_pointer'])
        c.require(type(count) is int and count > 0, 'Native scorer evaluated no cases')
        scope = definition['scope']
        if scope in ('full', 'qualified-held-out'):
            c.require(count == definition['expected_samples'], 'Native scorer did not evaluate the entire pinned selection')
        metrics = {name: adapters.metric(pointer(native, spec['pointer']), spec['unit'])
                   for name, spec in definition['result']['metrics'].items()}
        result = {key: request[key] for key in ('schema_version', 'request_sha256', 'definition_sha256',
                  'adapter_version', 'data_manifest_sha256', 'benchmark', 'model', 'seed')}
        result.update(status='PASS', evaluated_samples=count, scope=scope, metrics=metrics,
                      evidence=[{'path': str(path), 'sha256': c.digest(folder / path)}])
        if request['benchmark'] == 'melusense':
            # A held-out evaluator must explicitly echo its independently checked candidate/TRAIN bindings.
            for key in ('candidate_tree_sha256', 'train_examples_checked', 'train_bundle_sha256'):
                result[key] = pointer(native, definition['result'][key + '_pointer'])
        for artifact in definition['artifacts']: c.pin(artifact)
        c.require(c.digest(args.definition) == request['definition_sha256'], 'Suite definition changed during execution')
        c.save(args.result, result)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, IndexError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    sys.exit(main())
