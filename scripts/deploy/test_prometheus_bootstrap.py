"""Monitoring safety checks; downloads, systemd and HTTP are mocked unless stated."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import prometheus_bootstrap as monitor


class MonitoringTests(unittest.TestCase):
    def target(self, root):
        return dict(home=str(root), runtime=str(root/'workspace/runtime'), user='test', uid=os.getuid(), hostname='spark-a922')

    def test_policy_rejects_unknown_fields_and_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=self.target(Path(tmp))
            with self.assertRaises(RuntimeError):monitor.settings(target,{'arbitrary_proxy':'yes'})
            with self.assertRaises(ValueError):monitor.settings(target,{'runtime':tmp+'/../escape'})
            with self.assertRaises(RuntimeError):monitor.settings(target,{'runtime':'/etc/monitoring'})

    def test_layout_preserves_legacy_config_and_native_units(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=self.target(Path(tmp));policy=monitor.settings(target)
            base,release,config,legacy,files=monitor.layout(target,policy)
            self.assertEqual([x['job_name'] for x in json.loads(legacy)['scrape_configs']],['vllm','benchmark-host'])
            self.assertEqual(config['scrape_configs'][-1]['job_name'],'dgx-spark-health')
            self.assertIn(b'--web.listen-address=127.0.0.1:9090',files[Path(tmp)/'.config/systemd/user'/monitor.UNITS[0]])
            self.assertNotIn(b'enable-lifecycle',b''.join(files.values()))

    def test_repeat_publication_preserves_bytes_modes_and_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.json'
            self.assertTrue(monitor.publish(path,b'{}'))
            before=path.stat()
            for _ in range(10):self.assertFalse(monitor.publish(path,b'{}'))
            self.assertEqual((before.st_mtime_ns,before.st_mode),(path.stat().st_mtime_ns,path.stat().st_mode))

    def test_symlink_is_never_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'target';target.write_bytes(b'private')
            link=Path(tmp)/'link';link.symlink_to(target)
            with self.assertRaises(ValueError):monitor.publish(link,b'overwrite')
            self.assertEqual(target.read_bytes(),b'private')

    def test_foreign_scrape_config_fails_before_release_or_service_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target=self.target(root);policy=monitor.settings(target)
            base=Path(policy['runtime']);base.mkdir(parents=True);(base/'prometheus.json').write_text('{"foreign":true}')
            with patch.object(monitor.common,'validate_target'),patch.object(monitor.platform,'machine',return_value='aarch64'),patch.object(monitor,'release_files') as release,patch.object(monitor,'run') as run:
                with self.assertRaisesRegex(RuntimeError,'divergent monitoring scrape'):monitor.install(target,policy)
                release.assert_not_called();run.assert_not_called()
            self.assertEqual((base/'prometheus.json').read_text(),'{"foreign":true}')

    def test_bad_release_hash_preserves_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);release=base/('prometheus-'+monitor.VERSION+'.linux-arm64')
            archive=base/(release.name+'.tar.gz');archive.write_bytes(b'bad')
            with self.assertRaisesRegex(RuntimeError,'SHA256 mismatch'):monitor.release_files(base,release)
            self.assertEqual(archive.read_bytes(),b'bad');self.assertFalse(release.exists())

    def test_down_target_cannot_be_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);(base/'monitoring-bootstrap.json').write_text('{}')
            config={'scrape_configs':[]};reply={'status':'success','data':{'activeTargets':[{'labels':{'job':'vllm'},'health':'down'}]}}
            with patch.object(monitor,'preflight',return_value=(base,base,config,b'',{})),patch.object(monitor,'run'),patch.object(monitor,'checked_file',return_value=json.dumps(config).encode()),patch.object(monitor,'http',side_effect=[b'ready',json.dumps(reply).encode()]):
                with self.assertRaisesRegex(RuntimeError,'not all healthy'):monitor.verify({}, {'include_health':True},timeout=0)

    def test_exact_legacy_mode_migration_is_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);base.chmod(0o775);path=base/'metrics.py';path.write_bytes(b'known');path.chmod(0o664)
            self.assertEqual(monitor.known_file(path,(b'known',)),b'known')
            monitor.migrate_legacy_modes(base,[path])
            self.assertEqual(path.stat().st_mode&0o777,0o600);self.assertEqual(base.stat().st_mode&0o777,0o700)
            receipt=json.loads(next(base.glob('legacy-metadata-*.json')).read_text())
            self.assertEqual(receipt['before'][str(path)]['mode'],'0o664')
            self.assertEqual(path.read_bytes(),b'known')

    def test_legacy_mode_does_not_accept_foreign_contents_or_world_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'metrics.py';path.write_bytes(b'foreign');path.chmod(0o664)
            with self.assertRaises(RuntimeError):monitor.known_file(path,(b'known',))
            path.chmod(0o666)
            with self.assertRaises(RuntimeError):monitor.known_file(path,(b'foreign',))
            self.assertEqual(path.read_bytes(),b'foreign')

    def test_inspection_does_not_install(self):
        with patch.object(monitor,'verify',side_effect=RuntimeError('missing')),patch.object(monitor,'install') as install:
            self.assertEqual(monitor.inspect({}, {})['status'],'BLOCKED');install.assert_not_called()
