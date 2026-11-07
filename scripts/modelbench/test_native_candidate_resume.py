"""Capture-only coordinator repair retains original identity and cannot start."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_candidate_resume as adapter

class ResumeAdapterTests(unittest.TestCase):
    def test_only_capture_hook_changes_under_exact_independent_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'run';run.mkdir()
            def save(path,value):path.write_text(json.dumps(value));path.chmod(0o600)
            def pin(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            original=root/'original.py'
            original.write_text('from pathlib import Path\nimport json\nfrom types import SimpleNamespace\n'+'ROOT=Path('+repr(str(root))+')\n'+'''def bind(path,online=False):return (None,None,None,None,None,{'run_id':'fixture'},ROOT,ROOT/'run',{'fingerprint':'fingerprint','identity':{'seed':2}},{})
def atomic_json(w,path,value):
 if not path.exists():path.write_text(json.dumps(value));path.chmod(0o600)
def capture_messages(*args):raise AssertionError('old unsupported cursor')
def finish(*args):return capture_messages()
''')
            updated=root/'updated.py';updated.write_text("def capture_messages(*args):return {'captured':'same-session-only'}\n")
            configuration=root/'gui.json';session=root/'session.json';save(configuration,{});save(session,{'run_id':'fixture','seed':2});save(root/'session-prepared.json',{'identity':{'profile':{'run_id':'fixture','seed':2}}})
            review=root/'review.json';profile={'schema_version':1,'run_id':'fixture','fingerprint':'fingerprint','original':pin(original),'updated':pin(updated),'configuration':pin(configuration),'session_profile':pin(session),'adapter_sha256':hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest()}
            decision={'decision':'COORDINATOR_CAPTURE_PATCH_ACCEPTED','run_id':'fixture','fingerprint':'fingerprint','original_sha256':profile['original']['sha256'],'updated_sha256':profile['updated']['sha256'],'adapter_sha256':profile['adapter_sha256'],'scope':'OBSERVE_AND_FINISH_ONLY','independent_reviewer':'synthetic-test-only','findings':[]};save(review,decision);profile['review']=pin(review)
            source=root/'profile.json';save(source,profile);save(run/'candidate-start.json',{'controller_sha256':profile['original']['sha256'],'fingerprint':'fingerprint'})
            before=original.read_bytes();loaded,worker=adapter.load(source);self.assertEqual(worker.finish(),{'captured':'same-session-only'});self.assertEqual(original.read_bytes(),before)
            other=root/'wrong-session.json';save(other,{'run_id':'other','seed':1})
            wrong=dict(profile,session_profile=pin(other));save(root/'wrong-profile.json',wrong)
            with self.assertRaisesRegex(ValueError,'cleanup profile'):adapter.load(root/'wrong-profile.json')
            registration=run/'coordinator-capture-adapter.json';original_registration=registration.read_bytes()
            previous=pin(registration);migration=dict(profile,previous_registration=previous)
            migrated_review=dict(decision,previous_registration_sha256=previous['sha256'],session_profile_sha256=profile['session_profile']['sha256'])
            save(root/'migration-review.json',migrated_review);migration['review']=pin(root/'migration-review.json');save(root/'migration.json',migration)
            adapter.load(root/'migration.json');adapter.load(root/'migration.json')
            self.assertEqual(registration.read_bytes(),original_registration)
            self.assertEqual(len(list((run/'coordinator-capture-adapters').glob('*.json'))),1)
            bad=dict(migration);bad['review']=profile['review'];save(root/'unreviewed.json',bad)
            with self.assertRaisesRegex(ValueError,'independent'):adapter.load(root/'unreviewed.json')
            decision['findings']=['open'];save(review,decision);profile['review']=pin(review);save(source,profile)
            with self.assertRaisesRegex(ValueError,'independent'):adapter.load(source)
    def test_start_is_not_a_supported_action(self):
        result=subprocess.run([sys.executable,'-B',str(ROOT/'tools/native_candidate_resume.py'),'start','--profile','/nonexistent'],capture_output=True)
        self.assertEqual(result.returncode,2);self.assertIn(b'invalid choice',result.stderr)

if __name__=='__main__':unittest.main()
