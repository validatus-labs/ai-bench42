"""Read-only model adoption safety fixtures; no real model or systemd access."""
import copy
import importlib.util
import json
from pathlib import Path
import platform
import pwd
import os
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('adoption', Path(__file__).with_name('adopt-existing.py'))
mod = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(mod)


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.runtime = self.base / 'runtime'; self.source = self.base / 'source'
        (self.source / 'config').mkdir(parents=True); (self.source / 'models').mkdir()
        account = pwd.getpwuid(os.getuid())
        (self.source / 'config/defaults.json').write_text(json.dumps({'runtime_root': str(self.runtime), 'user': account.pw_name, 'hostname': platform.node()}))
        (self.source / 'models/kolibri-1.json').write_text(json.dumps({'id': 'kolibri-1', 'revision': '258cae8ffffc8c12db670bdbc6ac01bcf8826c87', 'quantization': 'fp8', 'server': {'max_model_len': 262144}}))
        (self.source / 'vllmctl.py').write_text('# fixture only; never invoked\n')
        self.observation = {'profile_matches': True, 'deployment': {'fingerprint': 'f' * 64, 'release': 'fixture-release', 'unit_sha256': 'a' * 64}, 'service': {'MainPID': '42', 'ActiveState': 'active'}}
        self.observe = patch.object(mod, 'observe', return_value=self.observation)
        self.observe.start(); self.addCleanup(self.observe.stop)

    def test_plan_does_not_create_runtime(self):
        self.assertEqual(mod.adopt(self.runtime, self.source)['status'], 'ADOPTION_PLAN_ONLY')
        self.assertFalse(self.runtime.exists())

    def test_apply_and_repeat_preserve_registration_bytes_and_mtime(self):
        first = mod.adopt(self.runtime, self.source, True)
        selected = self.runtime / 'tools/bootstrap/selected-model.json'
        before = (selected.read_bytes(), selected.stat().st_mtime_ns)
        again = mod.adopt(self.runtime, self.source, True)
        self.assertEqual(first['status'], 'EXISTING_MODEL_REGISTERED'); self.assertEqual(again['status'], 'UNCHANGED')
        self.assertEqual(before, (selected.read_bytes(), selected.stat().st_mtime_ns))
        self.assertEqual(again['service_changes'], 0)

    def test_source_drift_never_overwrites_selection(self):
        mod.adopt(self.runtime, self.source, True)
        selected = self.runtime / 'tools/bootstrap/selected-model.json'; before = selected.read_bytes()
        (self.source / 'vllmctl.py').write_text('# modified fixture\n')
        with self.assertRaisesRegex(RuntimeError, 'conflicting model'): mod.adopt(self.runtime, self.source, True)
        self.assertEqual(selected.read_bytes(), before)

    def test_changed_pid_does_not_publish_selection(self):
        changed = copy.deepcopy(self.observation); changed['service']['MainPID'] = '43'
        with patch.object(mod, 'observe', side_effect=[self.observation, changed]), self.assertRaisesRegex(RuntimeError, 'changed during'):
            mod.adopt(self.runtime, self.source, True)
        self.assertFalse((self.runtime / 'tools/bootstrap/selected-model.json').exists())

    def test_wrong_account_rejected_without_controller_invocation(self):
        p = self.source / 'config/defaults.json'; data = json.loads(p.read_text()); data['user'] = 'unrelated'; p.write_text(json.dumps(data))
        with patch.object(mod, 'observe') as inspect, self.assertRaisesRegex(RuntimeError, 'account'):
            mod.adopt(self.runtime, self.source, True)
        inspect.assert_not_called()

    def test_adopted_bootstrap_reuse_does_not_start_or_rebuild_model(self):
        import verify_installation
        mod.adopt(self.runtime, self.source, True)
        profile = {'server': {'max_model_len': 262144}, 'quantization': 'fp8'}
        selection = {'calibration': 'off'}
        with patch.object(verify_installation, 'model_status', return_value=(self.source, selection, profile, self.observation)), patch.object(mod.components, 'model_package', side_effect=AssertionError('no rebuild')), patch.object(mod.components, '_controller', side_effect=AssertionError('no restart')):
            result = mod.components.model({'runtime': str(self.runtime)}, 'off')
        self.assertEqual(result['status'], 'UNCHANGED'); self.assertEqual(result['service_changes'], 0)


if __name__ == '__main__': unittest.main()
