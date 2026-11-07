"""Adoption safety tests; all host/browser/inference observations are mocked."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import sys
import unittest
from unittest.mock import patch

MODULE = Path(__file__).with_name('bootstrap_adoption.py')
spec = importlib.util.spec_from_file_location('tested_adoption', MODULE)
adoption = importlib.util.module_from_spec(spec); spec.loader.exec_module(adoption)


class AdoptionTests(unittest.TestCase):
    def fixture(self, root):
        old = root / 'existing'; runtime = old / 'tools/new-host'
        data = {'destination_runtime': str(runtime), 'existing_runtime': str(old),
                'user': 'fixture', 'hostname': 'fixture', 'model_fingerprint': 'a' * 64}
        snapshot = {'model': {'package': str(old / 'source'), 'state': {'fingerprint': 'a' * 64}}}
        base = old / 'tools/playwright-tool'; base.mkdir(parents=True)
        adoption.write_new(base / 'kilo.json', {'mcp': {'playwright': {'command': ['fixture'], 'enabled': True}}})
        def proof(_data, folder):
            folder.mkdir(parents=True)
            adoption.write_new(folder / 'proof.json', {'status': 'VERIFIED_MCP_AND_SANDBOXED_BROWSER', 'new_model_requests': 0})
            return {'path': str(folder / 'proof.json'), 'sha256': adoption.digest(folder / 'proof.json')}
        return data, snapshot, proof

    def test_failed_preflight_publishes_no_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, snapshot, proof = self.fixture(Path(tmp))
            with patch.object(adoption, 'identity'), patch.object(adoption, 'inspect', side_effect=RuntimeError('drift')), patch.object(adoption, 'browser_proof') as browser:
                with self.assertRaises(RuntimeError): adoption.adopt(data, Path(tmp) / 'proof')
                browser.assert_not_called()
            self.assertFalse(adoption.registry_path(data['destination_runtime']).parent.exists())

    def test_browser_failure_publishes_no_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, snapshot, proof = self.fixture(Path(tmp))
            with patch.object(adoption, 'identity'), patch.object(adoption, 'inspect', return_value=snapshot), patch.object(adoption, 'browser_proof', side_effect=RuntimeError('browser failed')):
                with self.assertRaises(RuntimeError): adoption.adopt(data, Path(tmp) / 'proof')
            self.assertFalse(adoption.registry_path(data['destination_runtime']).exists())

    def test_host_change_during_proof_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, snapshot, proof = self.fixture(Path(tmp))
            changed = copy.deepcopy(snapshot); changed['model']['state']['fingerprint'] = 'b' * 64
            with patch.object(adoption, 'identity'), patch.object(adoption, 'inspect', side_effect=[snapshot, changed]), patch.object(adoption, 'browser_proof', side_effect=proof):
                with self.assertRaises(RuntimeError): adoption.adopt(data, Path(tmp) / 'proof')
            self.assertFalse(adoption.registry_path(data['destination_runtime']).exists())

    def test_repeat_preserves_every_registry_byte_mode_and_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, snapshot, proof = self.fixture(Path(tmp))
            with patch.object(adoption, 'identity'), patch.object(adoption, 'inspect', return_value=snapshot), patch.object(adoption, 'browser_proof', side_effect=proof) as browser:
                first = adoption.adopt(data, Path(tmp) / 'proof')
                folder = adoption.registry_path(data['destination_runtime']).parent
                before = {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in folder.iterdir()}
                second = adoption.adopt(data, Path(tmp) / 'unused')
                after = {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in folder.iterdir()}
                self.assertEqual(first['status'], 'ADOPTED_EXISTING'); self.assertEqual(second['status'], 'UNCHANGED')
                self.assertEqual(before, after); self.assertEqual(browser.call_count, 1)

    def test_existing_divergence_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, snapshot, proof = self.fixture(Path(tmp))
            with patch.object(adoption, 'identity'), patch.object(adoption, 'inspect', return_value=snapshot), patch.object(adoption, 'browser_proof', side_effect=proof):
                adoption.adopt(data, Path(tmp) / 'proof')
                selected = adoption.registry_path(data['destination_runtime']).with_name('selected-model.json')
                selected.write_text('{"unexpected":"preserve"}')
                with self.assertRaises(RuntimeError): adoption.adopt(data, Path(tmp) / 'unused')
                self.assertEqual(selected.read_text(), '{"unexpected":"preserve"}')

    def test_pinned_evidence_mutation_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, snapshot, proof = self.fixture(Path(tmp))
            with patch.object(adoption, 'identity'), patch.object(adoption, 'inspect', return_value=snapshot), patch.object(adoption, 'browser_proof', side_effect=proof):
                adoption.adopt(data, Path(tmp) / 'proof')
                (Path(tmp) / 'proof/proof.json').write_text('{}')
                with self.assertRaises(RuntimeError): adoption.check(data['destination_runtime'])

    def test_no_overwrite_publication_preserves_existing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / 'stage'; destination = Path(tmp) / 'destination'
            stage.mkdir(); destination.mkdir(); (destination / 'unrelated').write_text('preserve')
            with self.assertRaises(OSError): adoption.publish(stage, destination)
            self.assertEqual((destination / 'unrelated').read_text(), 'preserve')

    def test_symlink_destination_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / 'link'; link.symlink_to(Path(tmp), target_is_directory=True)
            with self.assertRaises(RuntimeError): adoption.registry_path(link)

    def test_adopted_off_cannot_stop_external_services(self):
        with patch.object(adoption, 'check') as check:
            with self.assertRaises(RuntimeError): adoption.bootstrap({'action': 'off', 'components': ['kolibri']})
            check.assert_not_called()

    def test_calibration_off_cannot_redeploy_adopted_v5(self):
        with patch.object(adoption, 'check') as check:
            with self.assertRaises(RuntimeError): adoption.bootstrap({'action': 'on', 'components': ['kolibri'], 'calibration': 'off'})
            check.assert_not_called()

    def test_health_override_cannot_mutate_adopted_installation(self):
        with patch.object(adoption, 'check') as check:
            with self.assertRaises(RuntimeError): adoption.bootstrap({'action': 'on', 'components': ['health'], 'health_retention': '7'})
            check.assert_not_called()

    def test_duplicate_json_keys_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'bad.json'; p.write_text('{"x":1,"x":2}')
            with self.assertRaises(RuntimeError): adoption.read(p)

    def test_preserved_baseline_shebang_requires_exact_live_arguments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); release = root / 'v5'; baseline = root / 'baseline'
            launcher = release / 'venv/bin/vllm'; launcher.parent.mkdir(parents=True)
            interpreter = str(baseline / 'venv/bin/python')
            launcher.write_text('#!' + interpreter + '\n')
            expected = [str(launcher), 'serve', 'calibrated', '--max-model-len', '262144']
            fake = types.ModuleType('modules.lifecycle'); fake.server_argv = lambda *_: expected
            with patch.dict(sys.modules, {'modules.lifecycle': fake}):
                args = [p.encode() for p in [interpreter, *expected]]
                self.assertEqual(adoption.process_argv(release, {'source_release': str(baseline)}, {}, args), interpreter)
                with self.assertRaises(RuntimeError):
                    adoption.process_argv(release, {'source_release': str(baseline)}, {}, args[:-1] + [b'32768'])
                with self.assertRaises(RuntimeError):
                    adoption.process_argv(release, {'source_release': str(root / 'other')}, {}, args)
                launcher.write_text('#!/bin/sh\n' + "'''exec' " + interpreter + ' "$0" "$@"\n' + "' '''\n")
                self.assertEqual(adoption.process_argv(release, {'source_release': str(baseline)}, {}, args), interpreter)
                launcher.write_text('#!/bin/sh\nexec arbitrary\n')
                with self.assertRaises(RuntimeError):
                    adoption.process_argv(release, {'source_release': str(baseline)}, {}, args)

    def health_fixture(self, root):
        source=root/'source'; script=source/'scripts/deploy/dgx-spark-health-bootstrap.sh'
        script.parent.mkdir(parents=True);script.write_text('new health source')
        data={'destination_runtime':str(root/'runtime'),'source_root':str(source),
              'files':{'/etc/default/dgx-spark-health':{'sha256':'a'*64,'mode':420},
                       '/usr/local/lib/dgx-spark-health/bootstrap.sh':{'sha256':'b'*64,'mode':493},
                       '/etc/unrelated':{'sha256':'c'*64,'mode':420}}}
        config={'owner':'fixture','interval':'60s'}
        snapshot={'files':copy.deepcopy(data['files']),'health':{'configuration':config},'model':{'immutable':'keep'}}
        proof=root/'proof.json';proof.write_text('{}')
        record={'owner':adoption.OWNER,'schema_version':1,'profile':data,'snapshot':snapshot,
                'browser_proof':{'path':str(proof),'sha256':adoption.digest(proof)}}
        path=adoption.registry_path(data['destination_runtime']);path.parent.mkdir(parents=True);adoption.write_new(path,record)
        updated=copy.deepcopy(snapshot);updated['health']['configuration']=dict(config,retention_days=30)
        updated['files'].update({'/etc/default/dgx-spark-health':{'sha256':adoption.hashlib.sha256(adoption.encoded(updated['health']['configuration'])).hexdigest(),'mode':420},
                                '/usr/local/lib/dgx-spark-health/bootstrap.sh':{'sha256':adoption.digest(script),'mode':493}})
        real_read=adoption.read
        def read(p):
            return updated['health']['configuration'] if str(p)=='/etc/default/dgx-spark-health' else real_read(p)
        return data,path,updated,read

    def test_health_refresh_rejects_unrelated_host_drift_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            data,path,updated,read=self.health_fixture(Path(tmp));before=path.read_bytes()
            updated['model']['immutable']='changed'
            with patch.object(adoption,'identity'),patch.object(adoption,'read',side_effect=read),patch.object(adoption,'inspect',return_value=updated):
                with self.assertRaises(RuntimeError):adoption.refresh_health(data,'30',Path(tmp)/'backup')
            self.assertEqual(path.read_bytes(),before);self.assertFalse((Path(tmp)/'backup').exists())

    def test_health_refresh_backs_up_registry_and_preserves_browser_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            data,path,updated,read=self.health_fixture(Path(tmp));before=path.read_bytes()
            with patch.object(adoption,'identity'),patch.object(adoption,'read',side_effect=read),patch.object(adoption,'inspect',return_value=updated),patch.object(adoption,'registration_files'),patch.object(adoption,'check'):
                result=adoption.refresh_health(data,'30',Path(tmp)/'backup')
                self.assertEqual(result['status'],'HEALTH_ADOPTION_REFRESHED')
                self.assertEqual((Path(tmp)/'backup/adoption-before.json').read_bytes(),before)
                after=read(path);self.assertEqual(after['browser_proof'],adoption.json.loads(before)['browser_proof'])
                self.assertEqual(after['snapshot']['model'],{'immutable':'keep'})


if __name__ == '__main__': unittest.main()
