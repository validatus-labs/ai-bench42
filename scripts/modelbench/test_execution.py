"""Real owned-child supervision, elapsed-only mode and retained failure tests."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modelbench import common as c


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'command'

    def test_elapsed_only_waits_for_real_child_and_measures_time(self):
        result = c.execute([sys.executable, '-B', '-c', 'print("observed")'], self.folder, None)
        self.assertEqual(result['exit_code'], 0); self.assertIsNone(result['timeout_seconds'])
        self.assertGreaterEqual(result['elapsed_seconds'], 0)
        self.assertEqual((self.folder / 'output.log').read_text().strip(), 'observed')

    def test_nonzero_exit_retained_without_retry(self):
        result = c.execute([sys.executable, '-B', '-c', 'raise SystemExit(7)'], self.folder, None)
        self.assertEqual(result['exit_code'], 7)
        before = (self.folder / 'command.json').read_bytes()
        with self.assertRaisesRegex(c.Blocked, 'already started'):
            c.execute([sys.executable, '-c', 'print("must not run")'], self.folder, None)
        self.assertEqual(before, (self.folder / 'command.json').read_bytes())

    def test_finite_timeout_still_applies_to_other_commands(self):
        with self.assertRaisesRegex(c.Failed, 'wall-time'):
            c.execute([sys.executable, '-c', 'import time;time.sleep(10)'], self.folder, 1)
        record = c.read(self.folder / 'command.json')
        self.assertEqual(record['status'], 'FAILED'); self.assertIsNotNone(record['exit_code'])

    def test_elapsed_only_keeps_log_budget(self):
        with self.assertRaisesRegex(c.Failed, 'log budget'):
            c.execute([sys.executable, '-c', 'print("x"*10000)'], self.folder, None, max_log_bytes=64)
        self.assertEqual(c.read(self.folder / 'command.json')['status'], 'FAILED')

    def test_cancel_reaps_owned_child(self):
        processes = []; popen = subprocess.Popen
        def spawn(*args, **kwargs):
            child = popen(*args, **kwargs); processes.append(child); return child
        with patch.object(c.subprocess, 'Popen', side_effect=spawn), patch.object(c.selectors.DefaultSelector, 'select', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            c.execute([sys.executable, '-c', 'import time;time.sleep(10)'], self.folder, None)
        self.assertIsNotNone(processes[0].poll())
        self.assertEqual(c.read(self.folder / 'command.json')['status'], 'INTERRUPTED')

    def test_invalid_timeouts_rejected_before_launch(self):
        for value in (True, 0, -1, float('inf')):
            with self.subTest(value=value), self.assertRaises(c.Blocked):
                c.execute([sys.executable, '-c', 'pass'], self.folder, value)
        self.assertFalse(self.folder.exists())


if __name__ == '__main__': unittest.main()
