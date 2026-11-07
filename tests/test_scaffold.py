"""Starter integrity checks; these are not parser correctness scores."""
import json
import pathlib
import unittest
from melusense import detect_eml, detect_text
ROOT = pathlib.Path(__file__).resolve().parents[1]

class ScaffoldTests(unittest.TestCase):
    def test_api_exported(self):
        self.assertTrue(callable(detect_text))
        self.assertTrue(callable(detect_eml))

    def test_common_budget(self):
        budget = json.loads((ROOT / "config/budget.json").read_text())
        self.assertEqual(budget["repetitions"], 3)
        self.assertEqual(len(set(budget["seeds"])), 3)
        self.assertEqual(budget["context_tokens"], 262144)

    def test_fixture_ids_unique(self):
        fixtures = json.loads((ROOT / "tests/fixtures.json").read_text())
        self.assertEqual(len({x["id"] for x in fixtures}), len(fixtures))
        self.assertTrue(all(x["id"].startswith("synthetic-") for x in fixtures))
