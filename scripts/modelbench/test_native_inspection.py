"""Inspection preparation: no systemd, SSH, browser or model access."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_inspection as inspect
import worker


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        fs=self.base/'rootfs';fs.mkdir();(fs/'public').write_text('synthetic runtime')
        ext=self.base/'installed';(ext/'bin').mkdir(parents=True);(ext/'dist').mkdir()
        (ext/'package.json').write_text(json.dumps({'publisher':'kilocode','name':'kilo-code','version':'7.8.17'}))
        (ext/'bin/kilo').write_text('synthetic installed binary');(ext/'dist/extension.js').write_text('synthetic extension')
        self.extension=ext;self.original=worker.tree(ext)
        self.root=self.base/'inspection';self.profile=self.base/'profile.json'
        value={'schema_version':1,'run_id':'synthetic-inspection','destination':str(self.root),'rootfs':str(fs),'rootfs_tree_sha256':worker.tree(fs),'python':inspect.artifact(Path(sys.executable).resolve()),'extension':str(ext),'extension_tree_sha256':self.original}
        worker.write(self.profile,value)

    def test_repeat_preserves_sealed_bytes_mtimes_and_original_extension(self):
        first=inspect.prepare(self.profile);before={n:((self.root/n).read_bytes(),(self.root/n).stat().st_mtime_ns) for n in first['sealed']}
        second=inspect.prepare(self.profile);self.assertTrue(second['reused'])
        self.assertEqual(before,{n:((self.root/n).read_bytes(),(self.root/n).stat().st_mtime_ns) for n in first['sealed']})
        self.assertEqual(worker.tree(self.extension),self.original)
        self.assertEqual(second['status'],'PREPARED_INSPECTION_NOT_C00')
        provider=worker.read(self.root/'modelbench.json');self.assertEqual(provider['enabled_providers'],['001']);self.assertEqual(provider['permission'],{'*':'deny'})
        self.assertEqual(worker.read(self.root/'toolchain.json')['channels'],{})

    def test_changed_extension_rejected_before_creation(self):
        (self.extension/'dist/extension.js').write_text('drift')
        with self.assertRaisesRegex(worker.Blocked,'Installed extension changed'):inspect.prepare(self.profile)
        self.assertFalse(self.root.exists())

    def test_derived_extension_drift_fails_without_repair(self):
        inspect.prepare(self.profile);p=self.root/'extension/dist/extension.js';p.write_text('tampered')
        with self.assertRaisesRegex(worker.Blocked,'Derived extension changed'):inspect.prepare(self.profile)
        self.assertEqual(p.read_text(),'tampered')

    def test_partial_prepare_is_retained(self):
        self.root.mkdir();(self.root/'unknown').write_text('retained')
        with self.assertRaises((OSError,worker.Blocked)):inspect.prepare(self.profile)
        self.assertEqual((self.root/'unknown').read_text(),'retained')

    def test_root_execution_rejected(self):
        with patch.object(inspect.os,'getuid',return_value=0):
            with self.assertRaisesRegex(worker.Blocked,'normal target'):inspect.prepare(self.profile)
        self.assertFalse(self.root.exists())


if __name__=='__main__':unittest.main()
