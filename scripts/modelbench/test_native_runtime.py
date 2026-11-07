"""Runtime reuse must recheck actual directory permissions and complete tree."""
import json,sys,tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_runtime as runtime
import worker


class RuntimeTests(unittest.TestCase):
    def test_font_assets_are_explicit_public_hash_pins(self):
        self.assertEqual(runtime.font_inputs({}),{})
        with self.assertRaisesRegex(worker.Blocked,'three existing'):runtime.font_inputs({'fonts':{'unexpected.ttf':{}}})
        files={n:{'path':'/usr/share/fonts/truetype/dejavu/'+n,'sha256':'0'*64} for n in ['DejaVuSans.ttf','DejaVuSansMono.ttf','DejaVuSerif.ttf']}
        with patch.object(worker,'checked_artifact',side_effect=lambda item:Path(item['path'])):
            self.assertEqual(set(runtime.font_inputs({'fonts':files})),set(files))
            files['DejaVuSans.ttf']['path']='/home/alice/private.ttf'
            with self.assertRaisesRegex(worker.Blocked,'public system TTF'):runtime.font_inputs({'fonts':files})
        self.assertIn('<cachedir>/tmp/fontconfig</cachedir>',runtime.FONTCONFIG)
        self.assertNotIn('/home/',runtime.FONTCONFIG)

    def test_directory_mode_drift_is_rejected_without_rebuilding(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);binary=base/'public-binary';binary.write_text('synthetic')
            pin=lambda p:{'path':str(p),'sha256':worker.digest(p)}
            definition={'schema_version':1,'python':pin(Path(sys.executable).resolve()),'node':pin(binary),'kilo':pin(binary),'ripgrep':pin(binary)}
            profile=base/'profile.json';worker.write(profile,definition)
            dest=base/'runtime';fs=dest/'rootfs';sub=fs/'public';sub.mkdir(parents=True);(sub/'file').write_text('public')
            receipt={'schema_version':1,'status':'BUILT_NOT_READY','identity':{'profile':definition,'builder_sha256':worker.digest(Path(runtime.__file__))},'files':runtime.inventory(fs),'rootfs_tree_sha256':worker.tree(fs),'reused':False}
            worker.write(dest/'receipt.json',receipt)
            self.assertTrue(runtime.build(profile,dest)['reused']);before=(dest/'receipt.json').read_bytes();sub.chmod(0o777)
            with self.assertRaisesRegex(worker.Blocked,'Native runtime changed'):runtime.build(profile,dest)
            self.assertEqual(before,(dest/'receipt.json').read_bytes());self.assertEqual(sub.stat().st_mode&0o777,0o777)


if __name__=='__main__':unittest.main()
