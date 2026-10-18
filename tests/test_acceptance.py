"""Visible candidate acceptance tests. Initially fail: API is unimplemented."""
import hashlib
import json
import pathlib
import unittest
from melusense import detect_eml, detect_text
ROOT = pathlib.Path(__file__).resolve().parents[1]

class AcceptanceTests(unittest.TestCase):
    def check_contract(self, result, source, kind):
        json.dumps(result)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["source_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(result["source_kind"], kind)
        self.assertEqual(result["authorized_removals"], [])
        self.assertIsInstance(result["warnings"], list)
        for candidate in result["candidates"]:
            self.assertIn(candidate["kind"], ["reply", "forward", "signature", "footer"])
            self.assertIsInstance(candidate["start"], int)
            self.assertIsInstance(candidate["end"], int)
            self.assertTrue(0 <= candidate["start"] < candidate["end"] <= len(result["text"]))
            self.assertTrue(candidate["evidence"])

    def test_plain_current_body(self):
        for fixture in json.loads((ROOT / "tests/fixtures.json").read_text()):
            with self.subTest(case=fixture["id"]):
                text = fixture["text"]
                result = detect_text(text, locale=fixture["locale"])
                self.check_contract(result, text.encode("utf-8"), "text")
                self.assertEqual(result["text"], text)
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["attachments"], [])

    def test_reply_candidate_exact_original_span(self):
        text = "Réponse actuelle.\r\nOn Monday, Example wrote:\r\n> Old text\r\n"
        result = detect_text(text, locale="en")
        self.check_contract(result, text.encode("utf-8"), "text")
        self.assertEqual(result["text"], text)
        self.assertTrue(any(c["kind"] == "reply" and "> Old text" in text[c["start"]:c["end"]] for c in result["candidates"]))

    def test_inert_plain_eml(self):
        raw = b"From: sender@example.invalid\r\nTo: receiver@example.invalid\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nKeep this body.\r\n"
        before = bytes(raw)
        result = detect_eml(raw, locale="en")
        self.check_contract(result, raw, "eml")
        self.assertEqual(raw, before)
        self.assertIn("Keep this body.", result["text"])
        self.assertEqual(result["attachments"], [])
