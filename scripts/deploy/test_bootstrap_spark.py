"""Bootstrap safety tests: mock APT/systemd/npm; no network or live installation."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


b=load('bootstrap','scripts/deploy/bootstrap-spark.py')
n=load('npm_bootstrap','scripts/deploy/bootstrap-playwright-deps.py')
h=load('host_bootstrap','scripts/deploy/bootstrap-host.py')
m=load('metrics_setup','scripts/benchmark/setup-metrics.py')


class StackTests(unittest.TestCase):
    def test_plan_is_fixed_commands_and_preserves_calibration(self):
        plan=b.plan();commands=dict(plan['stages'])
        self.assertEqual(plan['profile']['context_tokens'],262144)
        self.assertEqual(plan['profile']['calibration'],'qualified-v5-reuse')
        self.assertIn('kolibri-calibrated',commands)
        self.assertTrue(all(isinstance(argv,list) for argv in commands.values()))
        self.assertFalse(any('calibrate.py' in str(argv) for argv in commands.values()))
        self.assertIn('--metrics-only',commands['metrics']);self.assertIn('--include-health',commands['metrics'])
        # A submitted job is serialized before the copied driver validates it.
        # Nested tuples would make every legitimate native job fail equality.
        self.assertEqual(json.loads(b.encoded(plan)),plan)

    def test_infrastructure_selection_does_not_deploy_model(self):
        plan=b.plan(True)
        self.assertNotIn('kolibri-calibrated',dict(plan['stages']))
        self.assertTrue(plan['without_model'])

    def test_blocked_preflight_never_submits_or_installs(self):
        with patch.object(b,'identity'),patch.object(b,'inspect',return_value={'blockers':['missing V5']}),patch.object(b.subprocess,'run') as run:
            self.assertEqual(b.submit(b.plan(),'install')['status'],'BLOCKED');run.assert_not_called()

    def test_model_context_mismatch_is_not_accepted(self):
        good=types.SimpleNamespace(returncode=0)
        payload=json.dumps({'data':[{'id':'kolibri-1','max_model_len':131072}]}).encode()
        with patch.object(b.subprocess,'run',return_value=good),patch.object(b,'fetch',return_value=(200,payload)):
            with self.assertRaisesRegex(RuntimeError,'Model/context'):b.verify(False)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'prometheus.json';self.old=b'{"jobs":2}\n';self.new=b'{"jobs":3}\n'

    def test_config_repeat_preserves_bytes_and_mtime(self):
        self.path.write_bytes(self.new);before=self.path.stat().st_mtime_ns
        with patch.object(m,'run') as run:
            changed,old=m.publish_config(self.path,self.new,self.old,Path('/mock/promtool'))
            self.assertFalse(changed);run.assert_not_called()
        self.assertEqual(self.path.stat().st_mtime_ns,before)

    def test_exact_legacy_migration_preserves_checked_backup(self):
        self.path.write_bytes(self.old);self.path.chmod(0o640)
        with patch.object(m,'run') as run:
            changed,old=m.publish_config(self.path,self.new,self.old,Path('/mock/promtool'))
        self.assertTrue(changed);self.assertEqual(old,self.old);run.assert_called_once()
        self.assertEqual(self.path.read_bytes(),self.new)
        self.assertEqual(self.path.stat().st_mode&0o777,0o640)
        self.assertEqual((self.path.parent/'config-backups'/(hashlib.sha256(self.old).hexdigest()+'.json')).read_bytes(),self.old)

    def test_divergence_never_overwritten(self):
        self.path.write_bytes(b'unexpected')
        with patch.object(m,'run') as run,self.assertRaisesRegex(RuntimeError,'divergent'):
            m.publish_config(self.path,self.new,self.old,Path('/mock/promtool'))
        run.assert_not_called();self.assertEqual(self.path.read_bytes(),b'unexpected')

    def test_bad_candidate_leaves_old_configuration(self):
        self.path.write_bytes(self.old)
        with patch.object(m,'run',side_effect=RuntimeError('invalid config')),self.assertRaises(RuntimeError):
            m.publish_config(self.path,self.new,self.old,Path('/mock/promtool'))
        self.assertEqual(self.path.read_bytes(),self.old)

    def test_concurrent_change_is_preserved(self):
        self.path.write_bytes(self.old)
        with patch.object(m,'run',side_effect=lambda *args:self.path.write_bytes(b'external edit')),self.assertRaisesRegex(RuntimeError,'changed during'):
            m.publish_config(self.path,self.new,self.old,Path('/mock/promtool'))
        self.assertEqual(self.path.read_bytes(),b'external edit')


class NativeAndNpmTests(unittest.TestCase):
    def test_apt_upgrade_plan_stops_before_install_and_native_files(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/'native-target';src=Path(temp)/'source';src.write_text('owned')
            facts={'missing_packages':['curl'],'incompatible':[],'status':'MISSING'}
            planned=types.SimpleNamespace(stdout='Inst libc6 [old] (new Ubuntu)\n')
            with patch.object(h,'STATE',Path(temp)/'state'),patch.object(h.os,'geteuid',return_value=0),patch.object(h,'inspect',return_value=facts),patch.object(h,'targets',return_value=[(src,dest,0o644)]),patch.object(h.subprocess,'run',return_value=planned) as run:
                with self.assertRaisesRegex(RuntimeError,'upgrade/removal'):h.install()
                self.assertEqual(run.call_count,2)
                self.assertFalse(dest.exists())

    def test_exact_existing_npm_tree_is_noop(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp)/'playwright';base.mkdir()
            package=json.loads((ROOT/'config/playwright-package-lock.json').read_text())
            shutil.copyfile(ROOT/'config/playwright-package.json',base/'package.json')
            shutil.copyfile(ROOT/'config/playwright-package-lock.json',base/'package-lock.json')
            versions={name.removeprefix('node_modules/'):v['version'] for name,v in package['packages'].items() if name}
            for name,version in versions.items():
                p=base/'node_modules'/name/'package.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'version':version}))
            helper=types.SimpleNamespace(safe_path=lambda p:p,file_sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest(),seal_modules=lambda p:{'sha256':n.MODULE_SHA})
            before={str(p):p.stat().st_mtime_ns for p in base.rglob('*')}
            with patch.object(n.subprocess,'check_output') as call:
                result=n.install(helper,{'module_root':str(base/'node_modules'),'packages':versions})
            self.assertEqual(result['status'],'UNCHANGED');call.assert_not_called()
            self.assertEqual(before,{str(p):p.stat().st_mtime_ns for p in base.rglob('*')})

    def test_npm_lock_is_exact_existing_spark_lock(self):
        helper=types.SimpleNamespace(file_sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest())
        package,lock=n.validate_lock(helper)
        self.assertEqual(hashlib.sha256(lock.read_bytes()).hexdigest(),n.LOCK_SHA)
        self.assertEqual(json.loads(package.read_text())['dependencies']['@playwright/mcp'],'0.0.83')


if __name__=='__main__':unittest.main()
