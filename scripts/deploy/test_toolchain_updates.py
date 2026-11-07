"""Updater transport and qualification regressions; no package/model operations."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/deploy'))
import toolchain_native as native
import toolchain_lifecycle as lifecycle
spec = importlib.util.spec_from_file_location('tested_toolchain_cli', ROOT / 'scripts/toolchain.py')
cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)


class UpdateTests(unittest.TestCase):


    def test_fresh_inactive_units_are_not_reset_as_failed(self):
        with patch.object(native.subprocess, 'run') as run:
            run.return_value.stdout = 'inactive\n'
            native.reset_failed_units()
            self.assertEqual(len(run.call_args_list), 3)
            self.assertTrue(all(call.args[0][1] == 'show' for call in run.call_args_list))

    def test_only_actually_failed_units_are_reset(self):
        with patch.object(native.subprocess, 'run') as run:
            run.return_value.stdout = 'failed\n'
            native.reset_failed_units()
            resets = [call.args[0] for call in run.call_args_list if call.args[0][1] == 'reset-failed']
            self.assertEqual(resets, [['systemctl', 'reset-failed', unit] for unit in native.UNITS])

    def test_native_launch_mapping_preserves_sandbox_and_avoids_outer_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = lifecycle.command_args(root / 'release', root / 'work', ['/usr/bin/node', '/npm/node_modules/@playwright/mcp/cli.js', '--sandbox', '--isolated', '--block-service-workers', '--output-dir', '/tmp/output'])
            self.assertEqual(args[0], '/usr/bin/node')
            self.assertEqual(args[1], str(root / 'release/npm/node_modules/@playwright/mcp/cli.js'))
            self.assertIn('--sandbox', args); self.assertNotIn('--no-sandbox', args)
            self.assertFalse(any('bwrap' in item for item in args))
            self.assertEqual(args[-1], str(root / 'work/output'))

    def test_native_drift_cannot_requalify_an_old_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(lifecycle, 'guard_controller'), patch.object(lifecycle, 'verify_release', return_value=(root, {'backend':'native-brave-sandbox/v1','native':{'old':True}})), patch.object(lifecycle, 'native_identity', return_value={'new':True}):
                with self.assertRaisesRegex(RuntimeError, 'Native runtime differs'):
                    lifecycle._qualify(root, {}, 'a' * 64)

    def test_npm_empty_user_and_global_configuration_are_distinct_and_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = lifecycle.environment(tmp)
            self.assertNotEqual(env['npm_config_userconfig'], env['npm_config_globalconfig'])
            for key in ('npm_config_userconfig', 'npm_config_globalconfig'):
                p = Path(env[key]); self.assertEqual(p.read_bytes(), b'')
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(lifecycle.environment(tmp), env)

    def test_qualification_seals_traces_without_transient_browser_home_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'qualifications').mkdir()
            manifest = {'backend':'native-brave-sandbox/v1', 'native':{},
                        'selection':{'platform':{}, 'controller':{}}, 'node_version':'v24.22.0'}
            def canary(release, folder, data):
                cache = folder / '.cache/Names With Spaces'; cache.mkdir(parents=True)
                (cache / 'volatile').write_text('not an execution receipt')
                (folder / 'browser.json').write_text('{}')
                return {'browser_sandbox':True}
            with patch.object(lifecycle, 'guard_controller'), patch.object(lifecycle, 'verify_release', return_value=(root, manifest)), patch.object(lifecycle, 'native_identity', return_value={}), patch.object(lifecycle, 'host', return_value={}), patch.object(lifecycle, 'wait_for_apt'), patch.object(lifecycle, 'controller_identity', return_value={}), patch.object(lifecycle, 'apt_epoch', return_value=1), patch('toolchain_canary.run', side_effect=canary):
                result = lifecycle._qualify(root, {'minimum_node_major':22}, 'a' * 64)
            self.assertEqual(result['status'], 'QUALIFIED_HOST_TOOLCHAIN_NOT_C00')
            self.assertEqual(set(result['evidence']), {'browser.json'})

    def test_external_benchmark_lease_works_with_read_only_file(self):
        import fcntl
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'benchmark.lock'; path.touch(); path.chmod(0o400)
            with lifecycle.external_benchmark({'external_benchmark_lock':str(path)}):
                with path.open('r') as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(path.read_bytes(), b'')

    def target(self, root):
        return {'uid': os.getuid(), 'gid': os.getgid(), 'runtime': str(root / 'runtime'), 'project': str(root)}

    def test_updater_only_cli_does_not_enter_release_or_model_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self.target(Path(tmp))
            with patch.object(cli.common, 'account', return_value=target), patch.object(native, 'submit', return_value=0) as submit, patch.object(lifecycle, 'store') as store:
                self.assertEqual(cli.main(['install-updater']), 0)
                submit.assert_called_once_with(target, cli.ROOT, False)
                store.assert_not_called()

    def test_private_install_job_pins_all_sources_and_preserves_separate_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = self.target(root)
            for name in (*native.SOURCES, 'config/bootstrap/98modelbench-toolchain-events'):
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(name)
            with patch.object(native.common, 'validate_target'), patch.object(native.subprocess, 'run') as run:
                run.return_value.returncode = 0
                self.assertEqual(native.submit(target, root), 0)
            args = run.call_args.args[0]
            self.assertEqual(args[:4], ['sudo', '-n', '/usr/bin/python3', '-B'])
            path = Path(args[-1]); job = json.loads(path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(job['target']['runtime'], target['runtime'])
            self.assertEqual(job['files'], {name: native.common.digest(root / name) for name in job['files']})
            self.assertFalse(job['activate'])

    def test_invalid_account_cannot_create_a_root_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(native.common, 'validate_target', side_effect=ValueError('wrong account')), patch.object(native.subprocess, 'run') as run:
                with self.assertRaises(ValueError): native.submit(self.target(root), root)
                run.assert_not_called()
            self.assertFalse((root / 'runtime').exists())

    def test_source_drift_is_rejected_before_native_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = self.target(root)
            names = (*native.SOURCES, 'config/bootstrap/98modelbench-toolchain-events')
            for name in names:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(name)
            job = {'target': target, 'source': str(root), 'activate': False,
                   'files': {name: native.common.digest(root / name) for name in names}}
            path = root / 'job.json'; path.write_text(json.dumps(job)); path.chmod(0o600)
            (root / names[0]).write_text('unexpected drift')
            with patch.object(native.os, 'geteuid', return_value=0), patch.object(native.common, 'validate_target'), patch.object(native, '__file__', str(root / 'scripts/deploy/toolchain_native.py')), patch.object(sys, 'argv', ['installer', '--job', str(path)]), patch.object(native, 'install') as install:
                with self.assertRaisesRegex(RuntimeError, 'source changed'): native.main()
                install.assert_not_called()

    def test_foreign_npm_registry_or_missing_integrity_is_rejected(self):
        for record in ({'resolved': 'https://evil.invalid/package.tgz', 'integrity': 'sha512-a'},
                       {'resolved': 'https://registry.npmjs.org/package.tgz'}):
            with self.assertRaises(RuntimeError):
                lifecycle.validate_npm_lock({'lockfileVersion':3, 'packages': {'node_modules/a':record}}, {'registry':'https://registry.npmjs.org/'})

    def test_failed_qualification_cannot_switch_active_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'active.json').write_text('existing pointer')
            manifest = {'selection_id': 'selection'}
            with patch.object(lifecycle, 'verify_release', return_value=(root, manifest)), patch.object(lifecycle, 'qualification', side_effect=RuntimeError('sandbox failed')):
                with self.assertRaisesRegex(RuntimeError, 'sandbox failed'):
                    lifecycle.promote(root, {}, 'a' * 64)
            self.assertEqual((root / 'active.json').read_text(), 'existing pointer')
            self.assertFalse((root / 'events').exists())

    def test_identical_promotion_preserves_pointer_bytes_and_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / 'active.json'; path.write_text('existing pointer'); before = path.stat().st_mtime_ns
            with patch.object(lifecycle, 'verify_release', return_value=(root, {'selection_id':'selection'})), patch.object(lifecycle, 'qualification'), patch.object(lifecycle, 'active', return_value={'release':'a' * 64}):
                self.assertEqual(lifecycle.promote(root, {}, 'a' * 64)['status'], 'UNCHANGED')
            self.assertEqual(path.read_text(), 'existing pointer'); self.assertEqual(path.stat().st_mtime_ns, before)


if __name__ == '__main__': unittest.main()
