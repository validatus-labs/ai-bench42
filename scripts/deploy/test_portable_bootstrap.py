"""Portable wrapper contract tests: no sudo, installation, model download or GPU.

Includes 100 unchanged source preparations, account resolution, privilege refusal,
selected component isolation and calibration-off source generation.
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import sys
import socket
import threading
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('portable_bootstrap', ROOT / 'scripts/bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
components = bootstrap.components


class WrapperTests(unittest.TestCase):
    def arguments(self, *values):
        return bootstrap.parser().parse_args(values)

    def target(self, root):
        user = pwd.getpwuid(os.geteuid())
        return {'user': user.pw_name, 'uid': user.pw_uid, 'gid': user.pw_gid,
                'home': user.pw_dir, 'project': str(ROOT), 'hostname': bootstrap.platform.node(),
                'runtime': str(Path(root) / 'runtime')}

    def test_plan_uses_os_account_not_user_environment_and_never_submits(self):
        if os.geteuid() == 0:
            self.skipTest('Contract requires a normal invoking account')
        with patch.dict(os.environ, USER='forged-user'), patch.object(bootstrap, 'submit') as submit:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(bootstrap.main(['--health', '--plan']), 0)
            target = json.loads(output.getvalue())['target']
            self.assertEqual(target['user'], pwd.getpwuid(os.geteuid()).pw_name)
            self.assertEqual(target['uid'], os.geteuid())
            submit.assert_not_called()
            snapshot = json.loads(output.getvalue())
            bootstrap.check_sources(snapshot)
            with patch.object(bootstrap, 'sources', return_value=dict(snapshot['sources'], extra='changed')):
                with self.assertRaises(ValueError):
                    bootstrap.check_sources(snapshot)

    def test_flags_are_explicit(self):
        args = self.arguments('--maintenance', '--kolibri', '--calibration', 'on', '--off')
        self.assertTrue(args.maintenance)
        self.assertTrue(args.off)
        self.assertEqual(args.calibration, 'on')
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.arguments('--on', '--off', '--health')
        with self.assertRaises(ValueError):
            bootstrap.plan(self.arguments('--health', '--calibration', 'on'))
        with self.assertRaises(ValueError):
            bootstrap.plan(self.arguments('--plan'))

    def test_account_record_cannot_invent_identity_or_use_root(self):
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            changed = dict(target, uid=target['uid'] + 10)
            with self.assertRaises(ValueError):
                components.validate_target(changed)
            changed = dict(target, hostname='unrelated-host')
            with self.assertRaises(ValueError):
                components.validate_target(changed)

    def test_100_repetitions_preserve_source_bytes_and_mtimes(self):
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            package = components.model_package(target)
            before = {str(p.relative_to(package)): (p.read_bytes(), p.stat().st_mtime_ns)
                      for p in package.rglob('*') if p.is_file()}
            for _ in range(100):
                self.assertEqual(components.model_package(target), package)
            after = {str(p.relative_to(package)): (p.read_bytes(), p.stat().st_mtime_ns)
                     for p in package.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            defaults = json.loads((package / 'config/defaults.json').read_text())
            model = json.loads((package / 'models/kolibri-1.json').read_text())
            self.assertEqual(defaults['user'], target['user'])
            self.assertEqual(defaults['runtime_root'], target['runtime'])
            self.assertEqual(model['quantization'], 'fp8')
            self.assertEqual(model['server']['kv_cache_dtype'], 'fp8')
            self.assertNotIn('kv_calibration', model)

    def test_source_drift_is_preserved_and_not_repaired(self):
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            package = components.model_package(target)
            path = package / 'vllmctl.py'
            path.write_text('changed source')
            with self.assertRaises(ValueError):
                components.model_package(target)
            self.assertEqual(path.read_text(), 'changed source')

    def test_native_configuration_repeats_without_overwriting(self):
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            source = bootstrap.configure_native_source(target)
            service = source / 'config/systemd/ai-model-apt-update@.service'
            self.assertIn('MODEL_BENCH_HOSTNAME=' + target['hostname'], service.read_text())
            before = service.stat().st_mtime_ns
            self.assertEqual(bootstrap.configure_native_source(target), source)
            self.assertEqual(before, service.stat().st_mtime_ns)
            service.write_text('foreign configuration')
            with self.assertRaises(ValueError):
                bootstrap.configure_native_source(target)
            self.assertEqual(service.read_text(), 'foreign configuration')

    def test_non_maintenance_selection_does_not_enable_timers(self):
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            host = Mock()
            host.PACKAGES = []
            job = {'target': target, 'components': ['vllm'], 'action': 'on'}
            with patch.object(components, 'load_script', return_value=host):
                bootstrap.root_components(job)
            self.assertFalse(host.INSTALL_MAINTENANCE)
            self.assertEqual(host.DEPLOY_USER, target['user'])
            self.assertEqual(host.targets(), [])
            host.install.assert_called_once()

    def test_privilege_channel_rejects_arbitrary_root_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            job = {'target': self.target(temp)}
            for argv in [['sh', '-c', 'id'], ['systemctl', 'restart', 'sshd.service'],
                         ['rm', '--', '/etc/passwd']]:
                with patch.object(bootstrap.subprocess, 'check_output') as run:
                    with self.assertRaises(ValueError):
                        bootstrap.service_command(job, argv, 10)
                    run.assert_not_called()

    def test_submit_uses_one_sudo_supervisor_not_sudo_validation_loop(self):
        if os.geteuid() == 0:
            self.skipTest('Normal-account submission')
        with tempfile.TemporaryDirectory() as temp:
            job = bootstrap.plan(self.arguments('--health', '--runtime-root', str(Path(temp) / 'runtime')))
            with patch.object(bootstrap, 'host_check'), patch.object(bootstrap.subprocess, 'run', return_value=Mock(returncode=0)) as run, patch.object(sys.stdin, 'isatty', return_value=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bootstrap.submit(job), 0)
            command = run.call_args.args[0]
            self.assertEqual(command[:2], ['sudo', 'systemd-run'])
            self.assertNotIn('-v', command)
            self.assertNotIn('--user', command)
            run.assert_called_once()

    def test_playwright_off_preserves_the_managed_installer_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            config = Path(target['runtime']) / 'tools/bootstrap/kilo.json'
            components.atomic(config, {'mcp': {'playwright': {'enabled': True}}})
            job = {'target': target, 'components': ['playwright'], 'action': 'off', 'calibration': 'off'}
            bootstrap.user_components(job)
            self.assertFalse(json.loads(config.read_text())['mcp']['playwright']['enabled'])
            self.assertFalse((Path(target['runtime']) / 'tools/playwright-tool').exists())

    def test_privilege_transport_works_without_invoking_sudo(self):
        sys.path.insert(0, str(ROOT / 'scripts/deploy/dgx-spark-vllm'))
        from modules import common
        parent, child = socket.socketpair()
        received = []
        def server():
            with parent, parent.makefile('rwb') as stream:
                received.append(json.loads(stream.readline()))
                stream.write(b'{"returncode":0,"output":"owned-service-ready"}\n')
                stream.flush()
        thread = threading.Thread(target=server)
        thread.start()
        try:
            with patch.dict(os.environ, MODEL_BENCH_PRIVILEGE_FD=str(child.fileno())), patch.object(common.subprocess, 'run') as sudo:
                self.assertEqual(common.run(['sudo', '-n', 'systemctl', 'start', 'ai-model-vllm-kolibri-1.service']), 'owned-service-ready')
                sudo.assert_not_called()
            self.assertEqual(received[0]['argv'], ['systemctl', 'start', 'ai-model-vllm-kolibri-1.service'])
        finally:
            child.close()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())

    def test_100_healthy_model_repetitions_do_not_redeploy_or_recalibrate(self):
        from types import SimpleNamespace
        sys.path.insert(0, str(ROOT / 'scripts/deploy/dgx-spark-vllm'))
        from modules import lifecycle
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            package = components.model_package(target)
            selected = Path(target['runtime']) / 'tools/bootstrap/selected-model.json'
            components.atomic(selected, {'package': str(package), 'calibration': 'off', 'fingerprint': 'stable'})
            context = SimpleNamespace(model={})
            with patch.object(components, 'activate', return_value=context), patch.object(lifecycle, 'managed', return_value={'fingerprint': 'stable'}), patch.object(components, '_controller') as controller, patch.object(components, 'calibrated_artifact') as calibrate:
                for _ in range(100):
                    result = components.model(target, 'off')
                    self.assertEqual(result['status'], 'UNCHANGED')
                calibrate.assert_not_called()
                self.assertEqual(controller.call_count, 100)
                self.assertTrue(all(call.args[1] == 'start' for call in controller.call_args_list))

    def test_calibrated_profile_uses_target_runtime_and_pinned_loader_proof(self):
        sys.path.insert(0, str(ROOT / 'scripts/deploy/dgx-spark-vllm'))
        from modules.profiles import load
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            runtime = Path(target['runtime'])
            folder = runtime / 'build/dgx-spark-vllm/calibration/portable-fixture'
            folder.mkdir(parents=True)
            (folder / 'manifest.json').write_text('{}')
            proof = folder / 'loader-exact-preflight.json'
            proof.write_text('{"status":"test-fixture"}')
            record = {'kv_calibration': {'manifest': str(folder / 'manifest.json'), 'sha256': 'a' * 64,
                      'source_release': str(runtime / 'build/dgx-spark-vllm/releases/kolibri-1-fixture'),
                      'requirements_sha256': 'b' * 64}, 'loader_proof_sha256': components.digest(proof)}
            components.atomic(runtime / 'tools/bootstrap/calibration.json', record)
            package = components.model_package(target, True)
            profile = load(package, 'kolibri-1')
            self.assertEqual(profile['defaults']['user'], target['user'])
            self.assertEqual(profile['model']['server']['kv_cache_dtype'], 'fp8')
            self.assertEqual(profile['model']['kv_calibration'], record['kv_calibration'])
            proof.write_text('drift')
            with self.assertRaises(ValueError):
                components.model_package(target, True)

    def test_committed_pending_change_is_finalized_without_redeployment(self):
        from types import SimpleNamespace
        sys.path.insert(0, str(ROOT / 'scripts/deploy/dgx-spark-vllm'))
        from modules import lifecycle
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            package = components.model_package(target)
            state = Path(target['runtime']) / 'tools/bootstrap'
            request = {'package': str(package), 'calibration': 'off', 'fingerprint': 'committed'}
            components.atomic(state / 'pending-model.json', request)
            base = Path(target['runtime']) / 'build/dgx-spark-vllm'
            release = base / 'releases/kolibri-1-fixture'
            components.atomic(base / 'kolibri-1-transaction.json', {'phase': 'committed'})
            components.atomic(release / 'acceptance.json', {'smoke': {'semantic_fixture_verified': True}})
            active = SimpleNamespace(base=base, model={})
            with patch.object(components, 'activate', return_value=active), patch.object(lifecycle, 'managed', return_value={'fingerprint': 'committed', 'release': str(release)}), patch.object(components, '_controller') as controller, patch.object(components, 'calibrated_artifact') as calibrate:
                self.assertEqual(components.model(target, 'off')['status'], 'RECOVERED_COMMITTED_MODEL')
                controller.assert_called_once_with(package, 'start')
                calibrate.assert_not_called()
            self.assertFalse((state / 'pending-model.json').exists())
            self.assertEqual(json.loads((state / 'selected-model.json').read_text()), request)

    def test_100_calibrated_repetitions_reuse_pinned_artifact_without_observation(self):
        from types import SimpleNamespace
        sys.path.insert(0, str(ROOT / 'scripts/deploy/dgx-spark-vllm'))
        from modules import lifecycle, calibration
        from modules.common import Context
        from modules.profiles import load
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            runtime = Path(target['runtime'])
            folder = runtime / 'build/dgx-spark-vllm/calibration/reuse-fixture'
            folder.mkdir(parents=True)
            proof = folder / 'loader-exact-preflight.json'
            proof.write_text('{}')
            kv = {'manifest': str(folder / 'manifest.json'), 'sha256': 'a' * 64,
                  'source_release': str(runtime / 'build/dgx-spark-vllm/releases/kolibri-1-fixture'),
                  'requirements_sha256': 'b' * 64}
            components.atomic(runtime / 'tools/bootstrap/calibration.json', {'kv_calibration': kv, 'loader_proof_sha256': components.digest(proof)})
            package = components.model_package(target, True)
            components.atomic(runtime / 'tools/bootstrap/selected-model.json', {'package': str(package), 'calibration': 'on', 'fingerprint': 'stable'})
            with patch.dict(os.environ, MODEL_BENCH_PRIVILEGE_FD='42'):
                self.assertNotIn('MODEL_BENCH_PRIVILEGE_FD', Context(package, load(package, 'kolibri-1')).environment())
            active = Context(package, load(package, 'kolibri-1'))
            with patch.object(components, 'activate', return_value=active), patch.object(lifecycle, 'managed', return_value={'fingerprint': 'stable'}), patch.object(calibration, 'validate_manifest') as validate, patch.object(components, '_controller') as controller, patch.object(components, 'calibrated_artifact') as observe:
                for _ in range(100):
                    self.assertEqual(components.model(target, 'on')['status'], 'UNCHANGED')
                observe.assert_not_called()
                self.assertEqual(validate.call_count, 100)
                self.assertTrue(all(call.args[1] == 'start' for call in controller.call_args_list))

    def test_privileged_unit_install_accepts_only_rendered_nonroot_service(self):
        sys.path.insert(0, str(ROOT / 'scripts/deploy/dgx-spark-vllm'))
        from modules.common import Context
        from modules.profiles import load
        from modules.lifecycle import unit_text
        import shutil
        with tempfile.TemporaryDirectory() as temp:
            target = self.target(temp)
            package = components.model_package(target)
            release = Path(target['runtime']) / 'build/dgx-spark-vllm/releases/kolibri-1-fixture'
            shutil.copytree(package, release / 'source')
            context = Context(release / 'source', load(release / 'source', 'kolibri-1'))
            source = release / 'server.service'
            expected = unit_text(context, release)
            source.write_text(expected)
            command = ['install', '-o', 'root', '-g', 'root', '-m', '0644', str(source), '/etc/systemd/system/ai-model-vllm-kolibri-1.service']
            with patch.object(bootstrap.subprocess, 'check_output', return_value='owned-unit-installed') as install:
                self.assertEqual(bootstrap.service_command({'target': target}, command, 10), 'owned-unit-installed')
                install.assert_called_once()
            source.write_text(expected.replace('\nUser=' + target['user'] + '\n', '\nUser=root\n'))
            with patch.object(bootstrap.subprocess, 'check_output') as install:
                with self.assertRaises(ValueError):
                    bootstrap.service_command({'target': target}, command, 10)
                install.assert_not_called()


if __name__ == '__main__':
    unittest.main()
