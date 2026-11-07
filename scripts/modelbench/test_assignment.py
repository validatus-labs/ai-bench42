"""Outcome-free export, immutable task parity and no-overwrite reuse."""
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import assignment
import worker


class AssignmentTests(unittest.TestCase):
    def original(self):return {n:(ROOT/n).read_bytes() for n in (*assignment.COPIED,'docs/RUNBOOK.md')}
    def test_only_explicit_inputs_and_no_previous_results(self):
        original=self.original();files=assignment.payload(original)
        self.assertNotIn('docs/reports/kolibri.md',files)
        self.assertEqual(files['AGENTS.md'],original['AGENTS.md'])
        self.assertEqual(files['TASKS.md'],original['TASKS.md'])
        self.assertEqual(files['config/budget.json'],original['config/budget.json'])
        with self.assertRaises(worker.Blocked):assignment.payload(dict(original,**{'docs/reports/hidden.md':b'old result'}))
    def test_archive_is_deterministic_git_free_and_task_only(self):
        files=assignment.payload(self.original());raw=assignment.archive_bytes(files)
        self.assertEqual(raw,assignment.archive_bytes(dict(reversed(list(files.items())))))
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            self.assertEqual(set(tar.getnames()),set(files))
            self.assertTrue(all(m.isfile() and m.mtime==0 and m.mode==0o600 for m in tar))
            self.assertFalse(any('.git' in name or '/reports/' in name for name in tar.getnames()))
    def test_source_drift_is_rejected_before_export(self):
        with patch.object(assignment.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'different committed bytes',b'')):
            with self.assertRaisesRegex(worker.Blocked,'differs from approved'):assignment.inputs(ROOT,'0'*40)
    def test_full_scaffold_expected_failures_and_verified_reuse(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(assignment,'inputs',return_value=self.original()):
            dest=Path(tmp)/'assignment';first=assignment.export(ROOT,'0'*40,dest)
            self.assertEqual(first['status'],'PREPARED_NOT_READY')
            self.assertEqual(first['checks'][-1]['name'],'empty-parser-acceptance')
            self.assertNotEqual(first['checks'][-1]['exit_code'],0)
            stamp=(dest/'assignment.tar').stat().st_mtime_ns
            self.assertTrue(assignment.export(ROOT,'0'*40,dest)['reused'])
            self.assertEqual((dest/'assignment.tar').stat().st_mtime_ns,stamp)
            (dest/'assignment.tar').write_bytes(b'tampered')
            with self.assertRaises(worker.Blocked):assignment.export(ROOT,'0'*40,dest)
            self.assertEqual((dest/'assignment.tar').read_bytes(),b'tampered')
