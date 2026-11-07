"""Failure/restart regressions use synthetic stages, never a model or installation."""
import copy
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modelbench import common as c, pipeline, report, resume


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = {'runtime_root': str(self.root / 'host'), 'model': {'id': 'synthetic'}, 'fixed': 1}
        self.calls = []
        self.problem = None
        self.phases = [dict(id=name, name=name, kind='installation', status='PENDING')
                       for name in ('inspect', 'verify', 'challenge')]

    def dispatch(self, config, target, evidence, state, phase, *args):
        self.calls.append(phase['id'])
        if phase['id'] == 'verify': state['live_identity'] = {'pid': 'fixed'}
        if self.problem: self.problem(phase['id'], evidence)
        c.save(evidence / 'observed.json', {'actual': phase['id']})
        return {'status': 'PASS', 'scope': 'synthetic regression, no inference'}

    def run_pipeline(self, config=None):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(pipeline, 'validate', side_effect=lambda value: value))
            stack.enter_context(patch.object(pipeline.components, 'account', return_value={'runtime': str(self.root / 'host')}))
            stack.enter_context(patch.object(pipeline, 'source_hashes', return_value={'source': 'fixed'}))
            stack.enter_context(patch.object(pipeline, 'phase_definitions', side_effect=lambda value: copy.deepcopy(self.phases)))
            stack.enter_context(patch.object(pipeline, 'current_backend', return_value={'pid': 'fixed'}))
            stack.enter_context(patch.object(pipeline, 'execute_phase', side_effect=self.dispatch))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            return pipeline.run(config or self.config, self.root / 'runs', 'resume-proof')

    @property
    def folder(self): return self.root / 'runs/resume-proof'

    def tree(self):
        return {str(path.relative_to(self.folder)): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.folder.rglob('*') if path.is_file()}

    def test_disabled_optional_suite_does_not_make_completed_run_partial(self):
        state = {'phases': [{'status': 'PASS'}, {'status': 'NOT_REQUESTED'}]}
        self.assertEqual(report.conclusion(state)[0], 'COMPLETED')

    def test_requested_but_unavailable_suite_is_still_partial(self):
        state = {'phases': [{'status': 'PASS'}, {'status': 'NOT_EVALUATED'}]}
        self.assertEqual(report.conclusion(state)[0], 'PARTIAL')

    def test_complete_repeat_is_byte_and_mtime_noop(self):
        self.assertEqual(self.run_pipeline()['status'], 'COMPLETED')
        before = self.tree(); self.run_pipeline()
        self.assertEqual(before, self.tree()); self.assertEqual(self.calls, ['inspect', 'verify', 'challenge'])

    def test_rejected_candidates_complete_all_seeds_and_never_replay(self):
        self.phases=self.phases[:2]+[
            dict(id=kind+'-'+str(seed),name=kind,kind=kind,status='PENDING')
            for seed in [1,2,3] for kind in ['coding','evaluation']]
        original=self.dispatch
        def measured(*args):
            result=original(*args);phase=args[4]
            if phase['id'].startswith('coding-'):
                c.mark_effect('synthetic once-only candidate')
                result.update(status='CANDIDATE_REJECTED',candidate_verdict='FAILED')
            elif phase['id'].startswith('evaluation-'):
                result.update(status='NOT_EVALUATED',scope='No qualified held-out evaluator')
            return result
        with patch.object(self,'dispatch',side_effect=measured):
            result=self.run_pipeline();before=self.tree();calls=list(self.calls)
            self.assertEqual(result['status'],'INCOMPLETE')
            self.assertEqual(result['progress']['action'],'COMPLETE')
            self.assertEqual(self.calls,[p['id'] for p in self.phases])
            self.run_pipeline()
            self.assertEqual(self.calls,calls);self.assertEqual(self.tree(),before)
            self.assertEqual(result['aggregates'],[])

    def test_metric_order_stays_stable_after_json_roundtrip(self):
        dispatch = self.dispatch
        def measured(*args):
            result = dispatch(*args)
            result['metrics'] = {'z_last': {'value': 2, 'unit': 's'}, 'a_first': {'value': 1, 'unit': 's'}}
            return result
        with patch.object(self, 'dispatch', side_effect=measured):
            self.run_pipeline(); before = self.tree(); self.run_pipeline()
        self.assertEqual(before, self.tree())

    def test_blocked_prerequisite_resumes_without_repeating_success(self):
        def missing(name, folder):
            if name == 'verify': raise c.Blocked('Missing prerequisite')
        self.problem = missing
        self.assertEqual(self.run_pipeline()['progress']['next_phase'], 'verify')
        prior = self.folder / 'phases/verify/attempt-0001/receipt.json'; before = prior.read_bytes()
        self.assertEqual(self.calls, ['inspect', 'verify'])
        self.problem = None
        self.assertEqual(self.run_pipeline()['status'], 'COMPLETED')
        self.assertEqual(self.calls, ['inspect', 'verify', 'verify', 'challenge'])
        self.assertEqual(prior.read_bytes(), before)
        state = c.read(self.folder / 'state.json'); self.assertEqual(len(state['phases'][1]['attempts']), 2)
        resume.verify(self.folder, state)

    def test_graceful_interruption_before_effects_resumes(self):
        def interrupt(name, folder):
            if name == 'verify': raise KeyboardInterrupt()
        self.problem = interrupt
        with self.assertRaises(KeyboardInterrupt): self.run_pipeline()
        self.problem = None
        self.assertEqual(self.run_pipeline()['status'], 'COMPLETED')
        self.assertEqual(self.calls.count('inspect'), 1)

    def test_uncertain_model_execution_is_never_retried(self):
        def ambiguous(name, folder):
            if name == 'challenge':
                c.mark_effect('synthetic model boundary'); raise KeyboardInterrupt()
        self.problem = ambiguous
        with self.assertRaises(KeyboardInterrupt): self.run_pipeline()
        self.problem = None
        self.assertEqual(self.run_pipeline()['progress']['action'], 'REVIEW_REQUIRED')
        self.assertEqual(self.calls.count('challenge'), 1)

    def test_configuration_change_is_rejected_before_execution(self):
        self.run_pipeline(); before = self.tree()
        with self.assertRaisesRegex(c.Blocked, 'different inputs'): self.run_pipeline(dict(self.config, fixed=2))
        self.assertEqual(before, self.tree())

    def test_old_failed_attempt_tampering_blocks_resume(self):
        def missing(name, folder): raise c.Blocked('Missing')
        self.problem = missing; self.run_pipeline(); self.problem = None; self.run_pipeline()
        path = self.folder / 'phases/inspect/attempt-0001/extra.txt'; path.write_text('tamper')
        with self.assertRaisesRegex(c.Blocked, 'evidence changed'): self.run_pipeline()

    def test_overlapping_invocation_is_rejected(self):
        self.run_pipeline()
        with c.locked(self.folder / 'pipeline.lock'):
            with self.assertRaises(BlockingIOError): self.run_pipeline()

    def test_hard_crash_without_receipt_is_journaled_then_resumed(self):
        self.problem = lambda name, folder: (_ for _ in ()).throw(c.Blocked('missing'))
        self.run_pipeline(); state = c.read(self.folder / 'state.json'); phase = state['phases'][0]
        resume.begin(self.folder, phase); c.save(self.folder / 'state.json', state)
        self.problem = None; self.run_pipeline()
        attempts = c.read(self.folder / 'state.json')['phases'][0]['attempts']
        self.assertEqual([row['status'] for row in attempts], ['BLOCKED', 'INTERRUPTED', 'PASS'])

    def test_receipt_written_before_checkpoint_is_recovered(self):
        self.problem = lambda name, folder: (_ for _ in ()).throw(c.Blocked('missing'))
        self.run_pipeline(); state = c.read(self.folder / 'state.json'); phase = state['phases'][0]
        resume.begin(self.folder, phase); c.save(self.folder / 'state.json', state)
        phase['status'] = 'PASS'; resume.seal(self.folder, phase, state['fingerprint'])
        self.problem = None; self.run_pipeline()
        self.assertEqual(self.calls.count('inspect'), 1)

    def test_live_child_prevents_hard_crash_recovery(self):
        folder = c.private_directory(self.root / 'live')
        pid = os.getpid()
        c.save(folder / 'command.json', {'status': 'RUNNING', 'pid': pid,
               'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'process_start_ticks': Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()[19]})
        with self.assertRaisesRegex(c.Blocked, 'still alive'): resume.no_live_commands(folder)

    def test_unknown_launch_window_requires_review(self):
        folder = c.private_directory(self.root / 'unknown'); c.save(folder / 'command.json', {'status': 'RUNNING'})
        with self.assertRaisesRegex(c.Blocked, 'Uncertain command launch'): resume.no_live_commands(folder)

    def test_effect_marker_precedes_command_and_is_not_overwritten(self):
        folder = c.private_directory(self.root / 'effect')
        with c.effect_scope(folder):
            c.mark_effect('first'); before = (folder / 'effects-started.json').read_bytes(); c.mark_effect('second')
        self.assertEqual(before, (folder / 'effects-started.json').read_bytes())

    def test_command_journals_process_identity(self):
        result = c.execute([sys.executable, '-c', 'print("local synthetic")'], self.root / 'command', 10)
        self.assertEqual(result['exit_code'], 0); self.assertGreater(result['pid'], 1)
        self.assertTrue(result['process_start_ticks']); self.assertTrue(result['boot_id'])

    def test_directory_escape_is_rejected(self):
        with self.assertRaisesRegex(c.Blocked, 'inside the experiment'):
            resume.evidence_path(self.root, {'evidence_directory': '../outside'})

    def test_native_job_still_active_is_not_submitted_again(self):
        self.phases = [dict(id='deploy', name='deploy', kind='installation', status='PENDING')]
        def stopped(name, folder):
            c.mark_effect('Native bootstrap submission')
            c.save(folder / 'bootstrap-job.json', {'unit': 'modelbench-bootstrap-fixture'})
            raise KeyboardInterrupt()
        self.problem = stopped
        with self.assertRaises(KeyboardInterrupt): self.run_pipeline()
        self.problem = None
        with patch.object(resume.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'active\n', '')):
            self.run_pipeline()
        self.assertEqual(self.calls, ['deploy'])

    def test_completed_native_job_is_reused_from_receipt(self):
        evidence = c.private_directory(self.root / 'deployment')
        job = self.root / 'job.json'; receipt = self.root / 'native-receipt.json'; log = self.root / 'native.log'
        c.save(job, {'fingerprint': 'fixed'}); c.save(receipt, {'fingerprint': 'fixed', 'status': 'COMPLETED'})
        log.write_text('synthetic native outcome')
        c.save(evidence / 'bootstrap-job.json', {'unit': 'modelbench-bootstrap-fixture',
               'request': str(job), 'receipt': str(receipt), 'log': str(log)})
        phase = {'effects_started': True, 'evidence_directory': 'deployment'}
        with patch.object(resume.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'inactive\n', '')):
            result = resume.deployment_result(self.root, phase)
        self.assertEqual(result['status'], 'PASS'); self.assertEqual(len(result['external_evidence']), 3)

    def test_adopted_stack_does_not_expect_nonexistent_native_receipt(self):
        import bootstrap
        import bootstrap_adoption as adoption
        registry = self.root / 'adoption.json'
        c.save(registry, {'snapshot': {'health': {'configuration': {'retention_days': 30}}}})
        config = {'deployment': {'components': ['brave', 'playwright', 'maintenance', 'health', 'kolibri'],
                                'calibration': 'on', 'retention': '30'}}
        with patch.object(adoption, 'registry_path', return_value=registry), \
             patch.object(adoption, 'bootstrap', return_value={'status': 'UNCHANGED_ADOPTED_EXISTING'}) as adopt, \
             patch.object(bootstrap, 'plan', return_value={'components': []}) as plan, \
             patch.object(bootstrap, 'submit') as submit:
            result = pipeline.deploy(config, {'runtime': str(self.root)}, c.private_directory(self.root / 'adopt'))
        self.assertEqual(result['status'], 'PASS'); adopt.assert_called_once(); submit.assert_not_called()
        self.assertIsNone(plan.call_args.args[0].retention)

    def test_adopted_monitoring_uses_its_own_checked_installer(self):
        import bootstrap
        import bootstrap_adoption as adoption
        import prometheus_bootstrap as monitoring
        registry = self.root / 'adoption.json'
        c.save(registry, {'snapshot': {'health': {'configuration': {'retention_days': 30}}}})
        c.save(self.root / 'monitoring-bootstrap.json', {'synthetic': True})
        names = ['brave', 'playwright', 'maintenance', 'health', 'kolibri', 'metrics']
        config = {'deployment': {'components': names, 'calibration': 'on', 'retention': '30'}}
        with patch.object(adoption, 'registry_path', return_value=registry), \
             patch.object(adoption, 'bootstrap', return_value={'status': 'UNCHANGED_ADOPTED_EXISTING'}) as adopt, \
             patch.object(bootstrap, 'plan', return_value={'components': names}), \
             patch.object(monitoring, 'settings', return_value={'runtime': str(self.root)}), \
             patch.object(monitoring, 'install') as install, patch.object(monitoring, 'verify') as verify:
            result = pipeline.deploy(config, {'runtime': str(self.root)}, c.private_directory(self.root / 'adopt'))
        self.assertNotIn('metrics', adopt.call_args.args[0]['components'])
        self.assertEqual(len(result['external_evidence']), 2)
        install.assert_called_once(); verify.assert_called_once()

    def test_nested_dataset_files_are_reverified_on_reuse(self):
        item = self.root / 'dataset'; item.write_bytes(b'fixed')
        manifest = self.root / 'manifest.json'
        c.save(manifest, {'schema_version': 1, 'files': [{'path': str(item), 'sha256': c.digest(item)}]})
        spec = {'data_manifest': {'path': str(manifest), 'sha256': c.digest(manifest)}}
        self.assertEqual(len(resume.input_pins(spec)), 2)
        item.write_bytes(b'changed')
        with self.assertRaisesRegex(c.Blocked, 'Pinned file missing or changed'): resume.input_pins(spec)

    def test_host_lock_prevents_different_run_ids_from_overlapping(self):
        self.run_pipeline()
        with c.locked(self.root / 'host/tools/experiment-locks/coordinator.lock'):
            with self.assertRaises(BlockingIOError): self.run_pipeline()


class ProvisionResumeTests(unittest.TestCase):
    def test_owned_offline_pip_failure_resumes_without_recreating_venv(self):
        from modelbench import provision
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); env = root / 'env'; python = env / 'bin/python'
            base = root / 'base'; base.write_bytes(b'interpreter')
            lock = root / 'install.lock'; lock.write_text('package==1 --hash=sha256:' + '0' * 64)
            wheels = c.private_directory(root / 'wheels'); (wheels / 'package.whl').write_bytes(b'synthetic')
            pin = lambda path: {'path': str(path), 'sha256': c.digest(path)}
            spec = {'python': {'path': str(python), 'sha256': c.digest(base)},
                    'provision': {'base_python': pin(base), 'install_lock': pin(lock),
                                  'wheelhouse': str(wheels), 'data_manifest': {}}}
            calls = []
            def execute(argv, folder, seconds):
                calls.append(argv)
                if 'venv' in argv:
                    (env / 'bin').mkdir(parents=True); python.write_bytes(base.read_bytes())
                    return {'exit_code': 0}
                return {'exit_code': 1 if len(calls) == 2 else 0}
            with patch.object(c, 'execute', side_effect=execute):
                with self.assertRaisesRegex(c.Blocked, 'installation failed'):
                    provision.ensure_runtime(spec, root / 'first', lambda *args, **kwargs: None)
                provision.ensure_runtime(spec, root / 'second', lambda *args, **kwargs: None)
                before = (root / 'env.provision.json').read_bytes()
                provision.ensure_runtime(spec, root / 'third', lambda *args, **kwargs: None)
            self.assertEqual(sum('venv' in argv for argv in calls), 1)
            self.assertEqual(len(calls), 3); self.assertEqual(before, (root / 'env.provision.json').read_bytes())
            journal = c.read(root / 'env.provision.json')
            self.assertEqual([row['status'] for row in journal['attempts']],
                             ['FAILED_RETAINED', 'INSTALLED_AWAITING_RUNTIME_LOCK_CHECK'])


if __name__ == '__main__': unittest.main()
