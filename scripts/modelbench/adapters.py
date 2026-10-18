"""Pinned AIPerf/lm-eval integrations and independent scorer adapters.

adapters.py
|-- runtime()           verify executable and complete installed dependency lock
|-- aiperf()            concurrency 1/2/4 x three, actual export metrics
|-- lm_eval()           pinned task/tokenizer/data inputs; no network downloads
`-- external()          BFCL/SWE-bench/Gold receipt contract, no shell or fake scores
"""
import json
import math
from pathlib import Path
import re
import statistics

from . import common as c
from . import provision


def number(value):
    c.require(type(value) in (int, float) and math.isfinite(value), 'Expected finite numeric measurement')
    return value


def successful(command):
    if command.get('exit_code') != 0:
        raise c.Failed('Command exited ' + str(command.get('exit_code')) + '; inspect its private output.log')


def runtime(spec, folder):
    """The venv interpreter is a regular --copies executable, not a moving alias."""
    c.require(isinstance(spec.get('version'), str) and spec['version'] not in ('', 'latest'), 'Pin the exact benchmark distribution version')
    provision.ensure_runtime(spec, folder, pinned_dataset)
    python = c.pin(spec['python'])
    lock = c.pin(spec['requirements_lock'])
    expected = {}
    canonical = lambda name: re.sub(r'[-_.]+', '-', name).lower()
    for line in lock.read_text().splitlines():
        if not line.strip() or line.startswith('#'): continue
        match = re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s@/]+)', line)
        c.require(match and canonical(match[1]) not in expected, 'Runtime lock must contain unique name==version entries only')
        expected[canonical(match[1])] = match[2]
    # Do not log pip direct-reference URLs, which could contain credentials.
    query = ('import importlib.metadata as m,json; '
             'print(json.dumps([[d.metadata["Name"],d.version,'
             'bool(json.loads(d.read_text("direct_url.json") or "{}").get("dir_info",{}).get("editable"))] '
             'for d in m.distributions()]))')
    metadata = c.execute([str(python), '-I', '-c', query], folder / 'environment', 120)
    successful(metadata)
    observed = json.loads((folder / 'environment/output.log').read_text())
    c.require(all(not row[2] for row in observed), 'Editable benchmark dependencies are not accepted')
    actual = {canonical(row[0]): row[1] for row in observed}
    c.require(len(actual) == len(observed) and actual == expected, 'Installed benchmark dependency lock differs')
    version = c.execute([str(python), '-I', '-c', 'import importlib.metadata as m; print(m.version(' + repr(spec['distribution']) + '))'],
                        folder / 'version', 30)
    successful(version)
    c.require((folder / 'version/output.log').read_text().strip() == spec['version'], 'Benchmark package version differs')
    return python


def pinned_dataset(spec, roots=()):
    """A manifest seals actual files, including task configs/tokenizers, not just names."""
    manifest = c.read(c.pin(spec))
    c.require(manifest.get('schema_version') == 1 and isinstance(manifest.get('files'), list)
              and manifest['files'], 'Dataset manifest needs versioned sources and file pins')
    sealed = set()
    for row in manifest['files']:
        c.require(Path(str(row.get('path'))).name not in ('token', 'stored_tokens', '.netrc', '.env', '.git-credentials'),
                  'Credential files do not belong in a dataset/tokenizer manifest')
        c.require(isinstance(row.get('revision'), str) and row['revision'] and row['revision'] not in ('main', 'latest'),
                  'Dataset/tokenizer/task source revision must be pinned')
        sealed.add(c.pin(row))
    for root in roots:
        root = c.safe(root)
        c.require(root.is_dir(), 'Pinned data directory is missing: ' + str(root))
        files = set()
        for path in root.rglob('*'):
            c.require(not path.is_symlink(), 'Use materialized dataset/cache/tokenizer files, not symlinks')
            if path.is_file() and not path.name.endswith('.lock') and '__pycache__' not in path.parts:
                files.add(c.safe(path))
        c.require(files and files <= sealed, 'Data manifest does not cover all files in ' + str(root))
    return manifest


def metric(value, unit, direction=None):
    result = {'value': number(value), 'unit': unit}
    if direction: result['better'] = direction
    return result


def aiperf(spec, model, folder):
    python = runtime(spec['runtime'], folder)
    c.require(not model.get('auth_file'), 'Native AIPerf adapter currently requires the unauthenticated loopback endpoint')
    c.require(isinstance(spec['tokenizer'], str), 'Configure the local tokenizer path')
    tokenizer = c.safe(spec['tokenizer'])
    c.require(tokenizer.is_dir(), 'Configure an existing local tokenizer directory')
    pinned_dataset(spec['data_manifest'], roots=[tokenizer])
    c.require(spec['concurrency'] == [1, 2, 4] and spec['repetitions'] == 3,
              'P1 requires concurrency 1/2/4 and three repetitions')
    for key in ('input_tokens', 'output_tokens', 'request_count', 'timeout_seconds'):
        c.require(type(spec[key]) is int and spec[key] > 0, 'Invalid AIPerf budget')
    c.require(spec['request_count'] >= 4 and spec['input_tokens'] + spec['output_tokens'] < model['context_tokens'], 'Invalid P1 context/request budget')
    trials = []
    env = c.environment(c.private_directory(folder / 'home'))
    base = model['base_url'].removesuffix('/v1')
    for concurrency in spec['concurrency']:
        for repeat in range(1, 4):
            target = c.private_directory(folder / ('c' + str(concurrency) + '-r' + str(repeat)))
            artifacts = target / 'artifacts'
            argv = [str(python), '-I', '-m', 'aiperf', 'profile', '--model', model['id'],
                    '--url', base, '--endpoint-type', 'chat', '--endpoint', '/v1/chat/completions', '--streaming',
                    '--tokenizer', str(tokenizer), '--concurrency', str(concurrency),
                    '--request-count', str(spec['request_count']), '--warmup-request-count', '0',
                    '--synthetic-input-tokens-mean', str(spec['input_tokens']), '--synthetic-input-tokens-stddev', '0',
                    '--output-tokens-mean', str(spec['output_tokens']), '--output-tokens-stddev', '0',
                    '--random-seed', str(repeat), '--artifact-dir', str(artifacts), '--use-server-token-count']
            command = c.execute(argv, target / 'command', spec['timeout_seconds'], env=env)
            successful(command)
            exports = list(artifacts.rglob('profile_export_aiperf.json'))
            c.require(len(exports) == 1, 'Expected one unambiguous AIPerf JSON export')
            data = c.read(exports[0])
            c.require(data.get('aiperf_version') == spec['runtime']['version'], 'Export/runtime version mismatch')
            c.require(not data.get('was_cancelled') and data.get('is_complete') is not False, 'Incomplete AIPerf run')
            count = data.get('request_count', {})
            c.require(count.get('avg') == spec['request_count'], 'AIPerf completed request count differs')
            errors = (data.get('error_request_count') or {}).get('avg')
            if errors is not None: c.require(number(errors) == 0, 'AIPerf recorded request errors')
            measurements = {}
            for key in ('time_to_first_token', 'inter_token_latency', 'request_latency', 'output_token_throughput',
                        'output_token_throughput_per_user', 'input_sequence_length', 'output_sequence_length'):
                row = data.get(key)
                c.require(isinstance(row, dict) and row.get('avg') is not None and row.get('unit'), 'Missing AIPerf metric: ' + key)
                measurements[key] = metric(row['avg'], row['unit'])
            trials.append({'concurrency': concurrency, 'repeat': repeat, 'metrics': measurements,
                           'reported_request_errors': errors,
                           'configured_context_tokens': model['context_tokens'],
                           'requested_input_tokens': spec['input_tokens'], 'requested_output_tokens': spec['output_tokens'],
                           'cache_condition': 'uncontrolled; no cold/warm claim',
                           'raw_export': str(exports[0].relative_to(folder)), 'raw_sha256': c.digest(exports[0])})
    pinned_dataset(spec['data_manifest'], roots=[tokenizer])
    aggregates = {}
    for concurrency in (1, 2, 4):
        for key in trials[0]['metrics']:
            values = [row['metrics'][key]['value'] for row in trials if row['concurrency'] == concurrency]
            aggregates[f'c{concurrency}/{key}'] = dict(metric(statistics.median(values), trials[0]['metrics'][key]['unit']),
                                                     n=3, min=min(values), max=max(values))
    verified_errors = all(row['reported_request_errors'] == 0 for row in trials)
    return {'status': 'PASS' if verified_errors else 'NOT_EVALUATED', 'metrics': aggregates, 'trials': trials,
            'scope': ('serving performance' if verified_errors else 'measurements retained; request-error count not fully reported')
                     + '; client concurrency is not proof of simultaneous GPU decoding'}


def lm_eval(spec, model, folder):
    python = runtime(spec['runtime'], folder)
    pinned_dataset(spec['data_manifest'])
    c.require(spec['tasks'] == ['ifeval', 'mmlu_pro', 'bbh'], 'P2 requires the explicit IFEval/MMLU-Pro/BBH task set')
    c.require(not model.get('auth_file'), 'Native lm-eval adapter currently requires the unauthenticated loopback endpoint')
    c.require(spec['backend'] in ('local-completions', 'local-chat-completions'), 'Unsupported local lm-eval backend')
    c.require(spec.get('cli_style', 'run') in ('run', 'legacy'), 'Declare the pinned lm-eval CLI style')
    c.require(all(isinstance(spec[key], str) for key in ('tokenizer', 'hf_home', 'include_path')), 'Configure pinned tokenizer, HF cache and task-bundle paths')
    c.require(spec['limit'] is None or type(spec['limit']) is int and spec['limit'] > 0, 'lm-eval limit must be null (full) or a positive smoke count')
    c.require(type(spec['output_tokens']) is int and 0 < spec['output_tokens'] < model['context_tokens'], 'Invalid lm-eval output budget')
    tokenizer = c.safe(spec['tokenizer'])
    cache = c.safe(spec['hf_home'])
    task_path = c.safe(spec['include_path'])
    c.require(tokenizer.is_dir() and cache.is_dir() and task_path.is_dir(), 'Prepare pinned tokenizer, offline HF cache and task bundle first')
    pinned_dataset(spec['data_manifest'], roots=[tokenizer, cache, task_path])
    for value in (model['id'], model['base_url'], str(tokenizer)):
        c.require(',' not in value and '\n' not in value, 'Comma/newline in lm-eval model args')
    endpoint = '/completions' if spec['backend'] == 'local-completions' else '/chat/completions'
    arguments = {'model': model['id'], 'base_url': model['base_url'] + endpoint,
                 'tokenizer': str(tokenizer), 'tokenized_requests': 'False',
                 'num_concurrent': 1, 'max_retries': 0, 'max_length': model['context_tokens'],
                 'max_gen_toks': spec['output_tokens']}
    output = folder / 'results'
    argv = [str(python), '-I', '-m', 'lm_eval']
    if spec.get('cli_style', 'run') == 'run': argv.append('run')
    argv += ['--model', spec['backend'],
            '--model_args', ','.join(key + '=' + str(value) for key, value in arguments.items()),
            '--include_path', str(task_path), '--tasks', ','.join(spec['tasks']),
            '--output_path', str(output), '--seed', '1', '--log_samples']
    if spec.get('apply_chat_template'): argv.append('--apply_chat_template')
    if spec['limit'] is not None: argv += ['--limit', str(spec['limit'])]
    env = c.environment(c.private_directory(folder / 'home')); env['HF_HOME'] = str(cache)
    successful(c.execute(argv, folder / 'command', spec['timeout_seconds'], env=env))
    paths = list(output.rglob('results*.json'))
    c.require(len(paths) == 1, 'Expected one lm-eval results JSON')
    data = c.read(paths[0]); results = data.get('results'); samples = data.get('n-samples', {})
    c.require(isinstance(results, dict) and results and samples, 'Missing task results/sample coverage')
    observed = data.get('config', {}).get('model_args')
    if isinstance(observed, str):
        observed = dict(part.split('=', 1) for part in observed.split(',') if '=' in part)
    c.require(isinstance(observed, dict) and observed.get('model') == model['id']
              and observed.get('base_url') == model['base_url'] + endpoint, 'lm-eval result model/endpoint differs')
    metrics = {}
    for task, scores in results.items():
        if task in samples:
            c.require(type(samples[task].get('effective')) is int and samples[task]['effective'] > 0, 'No evaluated samples for ' + task)
            if spec['limit'] is None:
                c.require(samples[task]['effective'] == samples[task]['original'], 'Full task coverage differs for ' + task)
        else:
            c.require(data.get('group_subtasks', {}).get(task), 'No sample coverage/group membership for ' + task)
        for name, value in scores.items():
            if type(value) in (int, float): metrics[task + '/' + name] = metric(value, 'score')
    c.require(metrics, 'lm-eval returned no numeric scores')
    # Validate requested task/group names against actual result/config groups.
    represented = set(results) | set(data.get('groups', {})) | set(data.get('group_subtasks', {}))
    c.require(all(task in represented for task in spec['tasks']), 'A requested task/group was not evaluated')
    pinned_dataset(spec['data_manifest'], roots=[tokenizer, cache, task_path])
    return {'status': 'PASS', 'metrics': metrics, 'samples': samples,
            'scope': 'full' if spec['limit'] is None else 'smoke subset; not a full benchmark',
            'limit': spec['limit'], 'backend': spec['backend'],
            'raw_result': str(paths[0].relative_to(folder)), 'raw_sha256': c.digest(paths[0])}


def external(spec, request, folder):
    """Official-version adapter owns backend-specific generation/scoring details."""
    executable = c.pin(spec['executable'])
    pinned_dataset(spec['data_manifest'])
    c.require(isinstance(spec['version'], str) and spec['version'] not in ('', 'latest', 'main'), 'Pin adapter version')
    request_path = folder / 'request.json'; result_path = folder / 'result.json'
    bound = dict(request, schema_version=1, result_path=str(result_path),
                 adapter_version=spec['version'], data_manifest_sha256=spec['data_manifest']['sha256'])
    definition = c.pin(spec['definition']) if spec.get('definition') else None
    if definition: bound['definition_sha256'] = c.digest(definition)
    bound['request_sha256'] = c.fingerprint(bound)
    c.save(request_path, bound)
    argv = [str(executable), '--request', str(request_path), '--result', str(result_path)]
    if definition: argv += ['--definition', str(definition)]
    command = c.execute(argv,
                        folder / 'command', spec['timeout_seconds'])
    successful(command)
    result = c.read(result_path)
    for key in ('schema_version', 'request_sha256', 'adapter_version', 'data_manifest_sha256', 'benchmark', 'model', 'seed'):
        c.require(result.get(key) == bound.get(key), 'Scorer receipt mismatch: ' + key)
    c.require(result.get('status') == 'PASS' and type(result.get('evaluated_samples')) is int and result['evaluated_samples'] > 0,
              'Scorer did not complete any evaluation samples')
    c.require(result.get('scope') in ('smoke', 'full', 'qualified-held-out'), 'Declare evaluation scope')
    c.require(isinstance(result.get('metrics'), dict) and 0 < len(result['metrics']) <= 2000, 'Scorer returned no/bounded metrics')
    for row in result['metrics'].values():
        number(row['value']); c.require(isinstance(row.get('unit'), str), 'Metric unit missing')
    evidence = result.get('evidence', [])
    c.require(evidence, 'Scorer must attach raw-result evidence')
    for item in evidence:
        relative = Path(item['path'])
        c.require(not relative.is_absolute() and '..' not in relative.parts, 'Scorer evidence escapes its directory')
        c.require(c.digest(c.safe(folder / relative)) == item['sha256'], 'Scorer evidence missing/changed')
    c.pin(spec['executable']); pinned_dataset(spec['data_manifest'])
    if definition:
        c.require(result.get('definition_sha256') == bound['definition_sha256'], 'Wrong suite definition in scorer receipt')
        c.pin(spec['definition'])
    return result
