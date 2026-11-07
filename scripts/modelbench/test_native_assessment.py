"""Reproduce the real script-path import failure and fixed sealed-helper entry."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import json
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_assessment as assessment

class AssessmentTests(unittest.TestCase):
    def test_actual_visible_helper_needs_workspace_import_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);workspace=root/'workspace';tests=workspace/'tests';tests.mkdir(parents=True);package=workspace/'melusense';package.mkdir();(package/'__init__.py').write_text('def detect_text():return "fixture"\n')
            source=(ROOT/'tools/worker_inner.py').read_text().replace("    sys.path.insert(0,'/workspace')\n",'').replace('/workspace',str(workspace));helper=root/'worker_inner.py';helper.write_text(source)
            for name in ['test_scaffold.py','test_greenfield.py','test_acceptance.py','test_reserved_ml_mode.py']:
                (tests/name).write_text('import unittest\nfrom melusense import detect_text\nclass Fixture(unittest.TestCase):\n def test_import(self):self.assertEqual(detect_text(),"fixture")\n')
            elsewhere=root/'elsewhere';elsewhere.mkdir();environment={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1'}
            negative='import runpy,sys;sys.exit(runpy.run_path('+repr(str(helper))+')["visible"]())'
            broken=subprocess.run([sys.executable,'-B','-c',negative],cwd=elsewhere,env=environment,capture_output=True)
            self.assertEqual(broken.returncode,1);self.assertIn(b"No module named 'melusense'",broken.stderr)
            fixed=assessment.BOOTSTRAP.replace('/workspace',str(workspace)).replace('/opt/modelbench/worker_inner.py',str(helper))
            result=subprocess.run([sys.executable,'-B','-c',fixed,'visible'],cwd=elsewhere,env=environment,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr);value=json.loads(result.stdout);self.assertEqual(value['status'],'PASS');self.assertEqual(len(value['suites']),4)
            future=root/'future_worker_inner.py';future.write_text((ROOT/'tools/worker_inner.py').read_text().replace('/workspace',str(workspace)))
            direct='import runpy,sys;sys.exit(runpy.run_path('+repr(str(future))+')["visible"]())'
            result=subprocess.run([sys.executable,'-B','-c',direct],cwd=elsewhere,env=environment,capture_output=True)
            self.assertEqual(result.returncode,0,result.stderr)
    def test_changed_original_controller_refused_before_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'controller.py';p.write_text('raise AssertionError("must never import")')
            with self.assertRaisesRegex(ValueError,'pin changed'):assessment.assess(p,p,'0'*64,p,p)

if __name__=='__main__':unittest.main()
