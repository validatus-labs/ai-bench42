"""Durable local coordinator: inspect -> deploy -> verify -> P1/P2/P3 -> P4.

pipeline.py
|-- plan()          inputs and exact phases, no installation or inference
|-- run()           private, locked, fingerprint-bound receipts and reports
|-- coding()        three isolated seeds, C00, candidate, freeze, visible tests
`-- evaluate()      independent pinned scorer with frozen-candidate binding
"""
import contextlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import subprocess
import time
import urllib.request

from . import common as c, adapters, report, telemetry, resume

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/deploy'))
sys.path.insert(0, str(ROOT / 'tools'))
import bootstrap_components as components
import verify_installation
import worker


def source_hashes():
    paths = [ROOT / 'scripts', ROOT / 'config']
    result = {str(path.relative_to(ROOT)): c.digest(path) for base in paths for path in sorted(base.rglob('*'))
              if path.is_file() and path.suffix in ('.py', '.sh', '.cjs', '.json', '.service', '.timer', '.sources', '.preferences', '.cfg')
              and '__pycache__' not in path.parts}
    for name in ('tools/worker.py', 'tools/worker_inner.py', 'tools/preflight.py', 'tools/native_candidate.py', 'tools/native_readiness.py', 'config/toolchain-updates.json'):
        result[name] = c.digest(ROOT / name)
    return result


def validate(config):
    c.require(config.get('schema_version') == 1, 'Unsupported pipeline schema')
    c.require(set(config) == {'schema_version', 'runtime_root', 'deployment', 'model', 'benchmarks', 'coding'}, 'Unknown/missing pipeline fields')
    deployment = config['deployment']
    c.require(type(deployment['enabled']) is bool and deployment['calibration'] in ('on', 'off'), 'Invalid deployment mode')
    c.require(deployment['components'] in (['brave', 'playwright', 'maintenance', 'health', 'kolibri'], ['brave', 'playwright', 'maintenance', 'health', 'kolibri', 'metrics']), 'Use the complete supported Spark component set')
    c.require(deployment['retention'] in ('7', '30', '90', '180', '365', 'forever'), 'Invalid health retention')
    model = config['model']
    import toolchain_lifecycle
    toolchain_lifecycle.model_endpoint(dict(model=model['id'], base_url=model['base_url'], timeout_seconds=1200))
    c.require(model['id'] == 'kolibri-1' and model['base_url'] == 'http://127.0.0.1:8000/v1', 'Current full deployment profile is local Spark/Kolibri')
    c.require(isinstance(model['revision'], str) and model['revision'] not in ('', 'main', 'latest'), 'Pin model revision')
    c.require(type(model['context_tokens']) is int and model['context_tokens'] >= 262144, 'Common task requires 262144 context; no implicit reduction')
    c.require(set(config['benchmarks']) == {'aiperf', 'lm_eval', 'bfcl', 'swe_bench'}, 'P1/P2/P3 benchmark set is incomplete')
    for spec in config['benchmarks'].values():
        c.require(type(spec['enabled']) is bool, 'Invalid benchmark enabled flag')
    seeds=config['coding']['seeds']
    c.require(isinstance(seeds,list) and len(seeds)==3 and all(type(x) is int and 0<x<2**31 for x in seeds) and len(set(seeds))==3, 'Coding comparison requires three distinct positive seeds from the frozen assignment')
    c.require(type(config['coding'].get('enabled',True)) is bool,'Invalid coding enabled flag')
    c.require(type(config['coding'].get('elapsed_only',True)) is bool,'Invalid coding elapsed-only policy')
    c.require(type(config['coding']['approve_worker_disclosure']) is bool, 'Invalid disclosure approval')
    return config


def blockers(config):
    """Useful setup feedback even when target-specific assets are not provisioned."""
    missing = []
    def visit(value, label):
        if isinstance(value, dict):
            if value.get('enabled') is False: return
            if 'path' in value and 'sha256' in value:
                try: c.pin(value)
                except (c.Blocked, OSError) as exc: missing.append(label + ': ' + str(exc))
                return
            for key, child in value.items():
                if key == 'python' and isinstance(value.get('provision'), dict) and child.get('path') and not Path(child['path']).exists():
                    if not re.fullmatch('[a-f0-9]{64}', str(child.get('sha256'))):
                        missing.append(label + '.python: pin the expected copied interpreter SHA-256')
                    continue
                if key in ('evaluator', 'adapter') and child is None:
                    missing.append(label + '.' + key + ': configure a pinned scoring adapter')
                else: visit(child, label + '.' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value): visit(child, label + '.' + str(index))
    visit(config['benchmarks'], 'benchmarks'); visit(config['coding'], 'coding')
    for name in ('aiperf', 'lm_eval'):
        spec = config['benchmarks'][name]
        if not spec['enabled']: continue
        if not spec['runtime'].get('version'): missing.append(name + ': exact benchmark distribution version is missing')
        for key in (('tokenizer',) if name == 'aiperf' else ('tokenizer', 'hf_home', 'include_path')):
            if not isinstance(spec[key], str) or not Path(spec[key]).is_dir(): missing.append(name + ': local ' + key + ' directory is missing')
    if config['coding'].get('enabled',True) and not config['coding']['approve_worker_disclosure']: missing.append('coding: worker disclosure has not been approved')
    if config['coding'].get('enabled',True) and not re.fullmatch('[a-f0-9]{40}', str(config['coding']['source_sha'])): missing.append('coding: full source commit SHA is missing')
    return missing


def phase_definitions(config):
    rows = [('inspect', 'Host inventory', 'installation'),
            ('controller-tests', 'Coordinator regression tests', 'installation'), ('deploy', 'Deployment', 'installation'),
            ('verify', 'Installation and functional verification', 'installation')]
    rows += [(name, label, kind) for name, label, kind in [('aiperf', 'P1 · Serving performance', 'performance'),
             ('lm_eval', 'P2 · Standard model benchmarks', 'standard-quality'),
             ('bfcl', 'P3 · BFCL tool calls', 'bfcl'), ('swe_bench', 'P3 · SWE-bench', 'swe-bench')]]
    for seed in config['coding']['seeds']:
        rows += [(f'coding-{seed}', f'P4 · Coding task · seed {seed}', 'coding'),
                 (f'evaluation-{seed}', f'P4 · Independent assessment · seed {seed}', 'held-out-quality')]
    return [dict(id=key, name=name, kind=kind, status='PENDING') for key, name, kind in rows]


def plan(config):
    config = validate(config)
    return {'status': 'PLAN_ONLY', 'target': components.account(ROOT, config['runtime_root']),
            'phases': phase_definitions(config), 'configuration_sha256': c.fingerprint(config),
            'missing_inputs': blockers(config),
            'note': 'A plan executes no deployment, inference, coding or benchmark. Target inspection happens during run.'}


def current_backend(target, model):
    package, selected, profile, status = verify_installation.model_status(target)
    c.require(profile['id'] == model['id'] and profile['revision'] == model['revision'], 'Deployed model/revision differs from experiment')
    c.require(profile['server']['max_model_len'] == model['context_tokens'] and profile['quantization'] == model['quantization']
              and profile['server']['kv_cache_dtype'] == model['kv_cache_dtype'], 'Model context/quantization/KV configuration differs')
    observations = status['service']
    c.require(observations.get('ActiveState') == 'active' and observations.get('MainPID') not in ('0', None), 'Owned model service is not active')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(model['base_url'] + '/models', timeout=5) as response:
        raw = response.read(1024 * 1024 + 1)
    c.require(len(raw) <= 1024 * 1024, 'Oversized model metadata')
    metadata = json.loads(raw)
    actual = next((row for row in metadata.get('data', []) if row.get('id') == model['id']), None)
    c.require(actual and actual.get('max_model_len') == model['context_tokens'], 'Live model/context differs')
    from .kolibri import service_identity
    return {'service': service_identity(), 'selected': selected, 'model_profile_sha256': c.digest(package / 'models/kolibri-1.json'),
            'pid': observations.get('MainPID'), 'unit_sha256': c.digest(Path('/etc/systemd/system/ai-model-vllm-kolibri-1.service'))}


def deploy(config, target, folder):
    """Keep the native single sudo boundary on the operator's actual terminal."""
    import bootstrap
    import bootstrap_adoption as adoption
    registry = adoption.registry_path(target['runtime'])
    adopted = registry.exists()
    if adopted:
        existing = c.read(registry)
        c.require(str(existing['snapshot']['health']['configuration'].get('retention_days', 30)) == config['deployment']['retention'],
                  'Adopted health retention differs; explicit maintenance change required')
    argv = ['--' + item for item in config['deployment']['components']]
    argv += ['--runtime-root', target['runtime'], '--calibration', config['deployment']['calibration'],
             '--on']
    if not adopted: argv += ['--retention', config['deployment']['retention']]
    job = bootstrap.plan(bootstrap.parser().parse_args(argv))
    if 'metrics' in job['components'] and config['deployment'].get('metrics_policy'):
        # Pin the embedded policy as a private input and use the public CLI path.
        metrics_path = folder / 'metrics-policy.json'
        c.save(metrics_path, config['deployment']['metrics_policy'])
        argv += ['--metrics-config', str(metrics_path)]
        job = bootstrap.plan(bootstrap.parser().parse_args(argv))
    record = {'equivalent_cli': ['/usr/bin/python3', '-B', str(ROOT / 'scripts/bootstrap.py'), *argv],
              'entrypoint': 'bootstrap.plan / bootstrap.submit',
              'started_at': c.timestamp(), 'status': 'RUNNING',
              'supervision': 'native bootstrap supervisor; terminal preserved for its one sudo prompt'}
    c.save(folder / 'command.json', record)
    details = {}
    def observer(value):
        details.update(value)
        record['argv'] = value['argv']
        c.save(folder / 'command.json', record)
        c.save(folder / 'bootstrap-job.json', value)
    started = time.monotonic()
    try:
        if adopted:
            adopted_job = dict(job, components=[name for name in job['components'] if name != 'metrics'])
            result = adoption.bootstrap(adopted_job)
            monitoring_evidence = []
            if 'metrics' in job['components']:
                import prometheus_bootstrap as monitoring
                policy = monitoring.settings(target, config['deployment'].get('metrics_policy'))
                monitoring.install(target, policy)
                monitoring.verify(target, policy)
                registration = Path(policy['runtime']) / 'monitoring-bootstrap.json'
                monitoring_evidence.append({'path': str(registration), 'sha256': c.digest(registration)})
            c.save(folder / 'adoption-check.json', result)
            record.update(status='EXITED', exit_code=0)
            return {'status': 'PASS', 'scope': 'Existing adopted installation verified; no native deployment submitted',
                    'external_evidence': [{'path': str(registry), 'sha256': c.digest(registry)}] + monitoring_evidence}
        c.mark_effect('Native bootstrap submission')
        code = bootstrap.submit(job, observer=observer)
        record.update(status='EXITED', exit_code=code)
        c.require(code == 0, 'Native bootstrap did not complete; inspect its durable job receipt')
        receipt = c.read(details['receipt'])
        c.require(receipt.get('status') == 'COMPLETED' and receipt.get('fingerprint') == job['fingerprint'],
                  'No matching completed native bootstrap receipt')
        c.save(folder / 'bootstrap-completed.json', receipt)
        evidence = [{'path': details[key], 'sha256': c.digest(details[key])} for key in ('request', 'receipt', 'log')]
        return {'status': 'PASS', 'scope': 'Native bootstrap and component acceptance completed',
                'external_evidence': evidence}
    except BaseException as exc:
        record.update(status='INTERRUPTED' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'FAILED', error=str(exc))
        raise
    finally:
        record.update(finished_at=c.timestamp(), elapsed_seconds=time.monotonic() - started)
        c.save(folder / 'command.json', record)


def coding(config, target, folder, parent_id, seed):
    cfg = config['coding']
    c.require(cfg.get('enabled',True),'Coding is explicitly disabled; no worker may start')
    import tarfile
    provenance=c.read(c.pin(cfg['source_record']))
    c.require(provenance['approved_commit']==cfg['source_sha'] and provenance['archive_sha256']==cfg['package']['sha256'],'Approved source provenance differs')
    with tarfile.open(c.pin(cfg['package'])) as archive:
        budget=json.load(archive.extractfile('config/budget.json'))
    c.require(cfg['seeds']==budget['seeds'] and seed in budget['seeds'],'Coding seeds differ from the exact frozen assignment')
    c.require(config['model']['context_tokens']>=budget['context_tokens'],'Model context violates frozen budget')
    # Independent held-out qualification gates evaluate(), not candidate development.
    for key in ('package', 'train_bundle', 'rights_record'): c.pin(cfg[key])
    if cfg.get('native') is not None:
        from . import native_pipeline
        return native_pipeline.coding(config,folder,seed)
    c.pin(cfg['toolchain'])
    c.require(cfg['approve_worker_disclosure'], 'Explicit TRAIN worker disclosure approval is missing')
    toolchain = worker.validate_config(c.pin(cfg['toolchain']))
    c.require(toolchain['model']['id'] == config['model']['id'] and toolchain['model']['revision'] == config['model']['revision']
              and toolchain['model']['context_tokens'] == config['model']['context_tokens'], 'Worker and benchmark model identities differ')
    run_id = parent_id[:55] + '-s' + str(seed)
    runs = folder / 'workers'; run = runs / run_id
    argv = ['/usr/bin/python3', '-B', str(ROOT / 'tools/worker.py'), 'prepare', '--run-id', run_id,
            '--source-sha', cfg['source_sha'], '--package', str(c.pin(cfg['package'])), '--package-sha256', cfg['package']['sha256'],
            '--train-bundle', str(c.pin(cfg['train_bundle'])), '--train-sha256', cfg['train_bundle']['sha256'],
            '--rights-record', str(c.pin(cfg['rights_record'])), '--approve-worker-disclosure', '--seed', str(seed),
            '--model', config['model']['id'], '--toolchain', str(c.pin(cfg['toolchain'])), '--runs', str(runs)]
    if cfg.get('elapsed_only', True): argv += ['--elapsed-only']
    adapters.successful(c.execute(argv, folder / 'prepare', 300))
    c.mark_effect('Worker C00/model-to-tool qualification and candidate budget')
    adapters.successful(c.execute(['/usr/bin/python3', '-B', str(ROOT / 'tools/preflight.py'), '--run', str(run),
                                  '--toolchain', str(c.pin(cfg['toolchain']))], folder / 'c00', 900))
    candidate = c.execute(['/usr/bin/python3', '-B', str(ROOT / 'tools/worker.py'), 'run', '--run', str(run),
                           '--toolchain', str(c.pin(cfg['toolchain']))], folder / 'agent', None if cfg.get('elapsed_only', True) else 3900)
    # A nonzero agent exit still leaves a candidate worth freezing and assessing.
    frozen = c.execute(['/usr/bin/python3', '-B', str(ROOT / 'tools/worker.py'), 'freeze', '--run', str(run),
                        '--toolchain', str(c.pin(cfg['toolchain']))], folder / 'freeze', 300)
    adapters.successful(frozen)
    assessment = c.execute(['/usr/bin/python3', '-B', str(ROOT / 'tools/worker.py'), 'verify-candidate', '--run', str(run),
                            '--toolchain', str(c.pin(cfg['toolchain']))], folder / 'visible', 360)
    result = c.read(run / 'visible-result.json')
    freeze = c.read(run / 'frozen-candidate.json')
    # Agent prose is not evidence of training checks or token accounting.
    agent_report = run / 'workspace/build/worker-report.json'
    return {'status': 'PASS' if candidate.get('exit_code') == 0 and assessment.get('exit_code') == 0 else 'FAILED',
            'seed': seed, 'scope': 'frozen code and independently invoked visible tests; real-mail accuracy is evaluated separately',
            'worker_run': str(run), 'candidate_tree_sha256': freeze['candidate_tree_sha256'],
            'archive_sha256': freeze['archive_sha256'], 'archive': str(run / 'frozen-candidate.tar'),
            'suites': result['suites'], 'metrics': {'coding_seconds': adapters.metric(candidate['elapsed_seconds'], 's')},
            'agent_exit_code': candidate.get('exit_code'), 'visible_exit_code': assessment.get('exit_code'),
            'agent_report_present': agent_report.is_file(), 'agent_report_sha256': c.digest(agent_report) if agent_report.is_file() else None,
            'usage': {'source': 'NOT_REPORTED_BY_TRUSTED_METER', 'fresh_input_tokens': None, 'cache_read_tokens': None, 'output_tokens': None}}


def evaluate(config, folder, seed, candidate, run_id):
    scorer = config['coding']['evaluator']
    if scorer is None:
        return {'status': 'NOT_EVALUATED', 'scope': 'No qualified independent evaluator/held-out Gold configured'}
    request = {'benchmark': 'melusense', 'model': config['model'], 'seed': seed, 'run_id': run_id,
               'candidate': {'path': candidate['archive'], 'sha256': candidate['archive_sha256'],
                             'tree_sha256': candidate['candidate_tree_sha256']},
               'worker_run': candidate['worker_run'], 'source_sha': config['coding']['source_sha'],
               'package_sha256': config['coding']['package']['sha256'],
               'train_bundle': config['coding']['train_bundle'], 'required_train_examples': 12}
    # Independent evaluator owns a separate runtime; never execute candidate on host.
    result = adapters.external(scorer, request, folder)
    c.require(result['scope'] == 'qualified-held-out', 'Real-mail scoring needs qualified held-out scope')
    c.require(result.get('candidate_tree_sha256') == candidate['candidate_tree_sha256'], 'Evaluator scored another candidate')
    c.require(result.get('train_examples_checked') == 12 and result.get('train_bundle_sha256') == config['coding']['train_bundle']['sha256'],
              'Independent assessment must verify all 12 matching TRAIN development cases separately')
    return result


def run(config, destination, run_id):
    c.require(os.getuid() != 0, 'Run the coordinator as your normal account')
    c.require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}', run_id), 'Invalid pipeline Run-ID')
    validate(config)
    target = components.account(ROOT, config['runtime_root'])
    folder = c.private_directory(c.safe(destination) / run_id)
    identity = {'configuration_sha256': c.fingerprint(config), 'controller_sources': source_hashes(),
                'host': platform.node(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'uid': os.getuid(), 'target': target, 'model': config['model'],
                'python': platform.python_version(), 'kernel': platform.release(), 'os': platform.freedesktop_os_release()}
    fingerprint = c.fingerprint(identity)
    state_path = folder / 'state.json'
    host_lock = c.private_directory(Path(target['runtime']) / 'tools/experiment-locks') / 'coordinator.lock'
    with c.locked(folder / 'pipeline.lock'), c.locked(host_lock), contextlib.ExitStack() as leases:
        if state_path.exists():
            state = c.read(state_path)
            c.require(state['fingerprint'] == fingerprint, 'Run-ID has different inputs/code/host/boot; choose a new Run-ID')
            resume.verify(folder, state, recover=True)
            if state.get('live_identity'):
                c.require(current_backend(target, config['model']) == state['live_identity'], 'Backend changed since this experiment; choose a new Run-ID')
        else:
            state = {'schema_version': 2, 'run_id': run_id, 'fingerprint': fingerprint, 'identity': identity,
                     'created_at': c.timestamp(), 'phases': phase_definitions(config)}
            c.save(folder / 'configuration.json', config); c.save(state_path, state)
        report.render(folder, state)
        for phase in state['phases']:
            if phase['status'] in resume.COMPLETE: continue
            recovered = None
            if phase['status'] != 'PENDING':
                try: recovered = resume.may_retry(folder, phase)
                except (c.Blocked, OSError, KeyError, subprocess.SubprocessError) as exc:
                    print(json.dumps({'phase': phase['id'], 'status': 'REVIEW_REQUIRED', 'reason': str(exc)}), flush=True)
                    return report.render(folder, state)
            name = phase['id']
            evidence = resume.begin(folder, phase)
            c.save(state_path, state); report.render(folder, state)
            try:
                with c.effect_scope(evidence):
                    result = execute_phase(config, target, evidence, state, phase, identity, leases, run_id, recovered)
                phase.update(status=result['status'], result=result)
            except (KeyboardInterrupt, SystemExit):
                phase.update(status='INTERRUPTED', reason='Interrupted; resume checks evidence and execution boundary before retry')
                raise
            except Exception as exc:
                phase.update(status='BLOCKED' if isinstance(exc, (c.Blocked, worker.Blocked)) else 'FAILED', reason=str(exc))
            finally:
                resume.seal(folder, phase, fingerprint)
                c.save(state_path, state)
                report.render(folder, state)
            print(json.dumps({'phase': name, 'status': phase['status'], 'attempt': phase['attempt'], 'report': str(folder / 'report.html')}), flush=True)
            if phase['status'] not in resume.COMPLETE: break
        return report.render(folder, state)


def execute_phase(config, target, evidence, state, phase, identity, leases, run_id, recovered=None):
    name = phase['id']
    c.require(source_hashes() == identity['controller_sources'], 'Controller changed during the experiment')
    installation = {p['id']: p for p in state['phases'] if p['kind'] == 'installation'}
    if name == 'inspect':
        result = verify_installation.inspect_host(target, config['deployment']['components'], config['deployment'].get('metrics_policy'))
        # Missing components are expected before installation; unsupported hardware is a blocker.
        c.require(not any(row['status'] == 'UNSUPPORTED' for row in result['checks']), 'Unsupported target platform')
        result['installation_status'] = result['status']
        result.update(status='PASS', scope='Inventory completed; missing components may be installed in the next phase')
    elif name == 'controller-tests':
        for suite, source in [('modelbench', ROOT / 'scripts/modelbench'), ('deploy', ROOT / 'scripts/deploy'),
                              ('vllm', ROOT / 'scripts/deploy/dgx-spark-vllm/tests')]:
            adapters.successful(c.execute([sys.executable, '-B', '-m', 'unittest', 'discover',
                '-s', str(source), '-p', 'test_*.py', '-v'], evidence / suite, 900))
        result = {'status': 'PASS', 'scope': 'Coordinator regression suites; candidate tests remain isolated within each coding trial'}
    elif name == 'deploy':
        c.require(installation['controller-tests']['status'] == 'PASS', 'Coordinator regressions failed')
        c.require(installation['inspect']['status'] == 'PASS', 'Host inventory failed')
        if config['deployment']['enabled']:
            result = recovered or deploy(config, target, evidence)
        else:
            result = {'status': 'PASS', 'scope': 'Existing installation selected; live verification follows'}
    elif name == 'verify':
        c.require(installation['deploy']['status'] == 'PASS', 'Deployment did not complete')
        result = verify_installation.verify(target, config['deployment']['components'], evidence / 'acceptance', config['deployment'].get('metrics_policy'))
        c.require(result['status'] == 'PASS', 'Installed components failed acceptance; inspect acceptance/verification.json')
        state['live_identity'] = current_backend(target, config['model'])
    else:
        c.require(installation['verify']['status'] == 'PASS', 'Installation verification is not PASS')
        c.require(current_backend(target, config['model']) == state['live_identity'], 'Backend changed during the experiment')
        if not getattr(leases, '_modelbench_acquired', False):
            import toolchain_lifecycle
            store = c.private_directory(Path(target['runtime']) / 'tools/toolchains')
            leases.enter_context(toolchain_lifecycle.activity(store, exclusive=True, kind='benchmark'))
            leases.enter_context(toolchain_lifecycle.activity(store))
            leases._modelbench_acquired = True
        from . import native_pipeline
        with native_pipeline.workload_lease(config,target,name), telemetry.Monitor(evidence, config['model']) as observed:
            if name in config['benchmarks']:
                spec = config['benchmarks'][name]
                if not spec['enabled']:
                    result = {'status': 'NOT_REQUESTED', 'scope': 'Explicitly disabled in this experiment'}
                elif name == 'aiperf': result = adapters.aiperf(spec, config['model'], evidence)
                elif name == 'lm_eval': result = adapters.lm_eval(spec, config['model'], evidence)
                elif name == 'bfcl' and spec.get('retained'): result = adapters.retained_bfcl(spec, config['model'], evidence)
                else:
                    c.require(spec['adapter'] is not None, 'Configure the pinned official-suite generation/scoring adapter')
                    result = adapters.external(spec['adapter'], {'benchmark': name, 'model': config['model'],
                                               'seed': 1, 'run_id': run_id}, evidence)
            elif name.startswith('coding-'):
                if not config['coding'].get('enabled',True):
                    result={'status':'NOT_REQUESTED','scope':'Coding explicitly disabled; no worker started'}
                else:result = coding(config, target, evidence, run_id, int(name.rsplit('-', 1)[1]))
            else:
                seed = int(name.rsplit('-', 1)[1])
                previous = next(p for p in state['phases'] if p['id'] == 'coding-' + str(seed))
                if not config['coding'].get('enabled',True):
                    result={'status':'NOT_REQUESTED','scope':'Coding/evaluation explicitly disabled'}
                else:
                    c.require(previous.get('result', {}).get('candidate_tree_sha256'), 'No frozen candidate to evaluate')
                    result = evaluate(config, evidence, seed, previous['result'], run_id)
        result['telemetry'] = observed.summary
        result.setdefault('metrics', {}).update({'host/' + key: row for key, row in observed.summary['metrics'].items()})
        c.require(current_backend(target, config['model']) == state['live_identity'], 'Backend changed during measurement')
    if result['status'] == 'PASS' and name in config['benchmarks']:
        retained = result.setdefault('external_evidence', [])
        retained.extend(resume.input_pins(config['benchmarks'][name]))
    return result
