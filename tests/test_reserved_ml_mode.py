"""Frozen proposed acceptance tests for the reserved, inactive ml_mode switch.

Purely synthetic input. No trained models, credentials or external data. These
tests are intentionally expected to fail on the initially unimplemented starter.
The same tests must be frozen identically for every eligible coding model.
"""
from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from melusense import detect_eml, detect_text


TEXT = "Current reply.\r\nOn Tuesday, Example wrote:\r\n> Previous body\r\n"
EML = (
    b"From: sender@example.invalid\r\n"
    b"To: recipient@example.invalid\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Current message.\r\n"
)


class ReservedModeContractTests(unittest.TestCase):
    def test_text_explicit_off_equals_default(self):
        with mock.patch("socket.socket", side_effect=AssertionError("network is forbidden")):
            standard = detect_text(TEXT, locale="en")
            explicit = detect_text(TEXT, locale="en", ml_mode="off")
        self.assertEqual(standard, explicit)
        self.assertEqual(standard["authorized_removals"], [])
        self.assertEqual(standard["text"], TEXT)

    def test_eml_explicit_off_equals_default(self):
        with mock.patch("socket.socket", side_effect=AssertionError("network is forbidden")):
            standard = detect_eml(EML, locale="en")
            explicit = detect_eml(EML, locale="en", ml_mode="off")
        self.assertEqual(standard, explicit)
        self.assertEqual(standard["authorized_removals"], [])

    def test_recover_is_recognized_but_not_implemented(self):
        for parser, content in ((detect_text, TEXT), (detect_eml, EML)):
            with self.subTest(parser=parser.__name__):
                with mock.patch("socket.socket", side_effect=AssertionError("network is forbidden")):
                    with self.assertRaisesRegex(NotImplementedError, "ml_mode=recover"):
                        parser(content, locale="en", ml_mode="recover")

    def test_unknown_modes_are_rejected(self):
        for bad in ("on", "enabled", "yes", "", "train"):
            for parser, content in ((detect_text, TEXT), (detect_eml, EML)):
                with self.subTest(mode=bad, parser=parser.__name__):
                    with self.assertRaises(ValueError):
                        parser(content, locale="en", ml_mode=bad)

    def test_local_cli_off_and_recover(self):
        with tempfile.TemporaryDirectory() as root:
            folder = pathlib.Path(root)
            source = folder / "synthetic.eml"
            source.write_bytes(EML)
            out = folder / "result.json"
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(
                filter(None, [str(pathlib.Path(__file__).resolve().parents[1]), env.get("PYTHONPATH", "")])
            )
            args = [sys.executable, "-m", "melusense", str(source), "--ml-mode"]
            first = subprocess.run(
                [*args, "off", "--output", str(out)],
                env=env, cwd=root, capture_output=True, text=True, timeout=20, check=False
            )
            self.assertEqual(first.returncode, 0, first.stderr[:600])
            self.assertTrue(out.is_file())
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["authorized_removals"], [])

            # Output files are private and never silently overwritten.
            previous = out.read_bytes()
            again = subprocess.run(
                [*args, "off", "--output", str(out)],
                env=env, cwd=root, capture_output=True, text=True, timeout=20, check=False
            )
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(out.read_bytes(), previous)

            pending = folder / "recover-result.json"
            rejected = subprocess.run(
                [*args, "recover", "--output", str(pending)],
                env=env, cwd=root, capture_output=True, text=True, timeout=20, check=False
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("recover", rejected.stderr.lower())
            self.assertFalse(pending.exists())


if __name__ == "__main__":
    unittest.main()
