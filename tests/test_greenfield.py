"""Pure offline contract tests for ModelBench greenfield tooling."""
import importlib.util
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("greenfield_tool", ROOT / "tools" / "greenfield.py")
greenfield = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(greenfield)


class GreenfieldTests(unittest.TestCase):
    def test_hpi_train_only_and_fixed_revision(self):
        self.assertEqual(len(greenfield.HPI_TRAIN), 12)
        self.assertEqual(len(greenfield.hpi_pairs()), 24)
        self.assertEqual(len(greenfield.HPI_REF), 40)
        self.assertNotIn("TEST", " ".join(greenfield.HPI_TRAIN))
        self.assertNotIn("EVAL", " ".join(greenfield.HPI_TRAIN))

    def test_git_blob_hash_and_annotation_coordinates(self):
        self.assertEqual(greenfield.blobsha(b"test content\n"),
                         "d670460b4b4aece5915caf5c68d12f560a9fe3e4")
        sample = b'{"text":"From: a\\nbody","denotations":[{"start":0,"end":8,"text":"From: a\\n","type":"Header"}]}'
        stats = greenfield.verify_annotation("From: a\nbody", sample)
        self.assertEqual(stats["historical_headers"], 1)

    def test_malformed_annotation_fails_closed(self):
        sample = b'{"text":"abc","denotations":[{"start":0,"end":9,"text":"abc","type":"Header"}]}'
        with self.assertRaises(greenfield.Blocked):
            greenfield.verify_annotation("abc", sample)

    def test_hpi_bundle_requires_disclosure_approval(self):
        with self.assertRaises(greenfield.Blocked):
            greenfield.hpi_bundle(pathlib.Path("/missing"), pathlib.Path("/tmp/unused"),
                                  {"rights_record_sha256": "unit-test"}, False)

    def test_browser_sources_exclude_reference_repositories(self):
        self.assertEqual(greenfield.MCP_VERSION, "0.0.83")
        self.assertFalse(any("github.com" in url for url in greenfield.ALLOWED_ORIGINS))
        self.assertTrue(all(url.startswith("https://") for url in greenfield.ALLOWED_ORIGINS))

    def test_portable_node_has_hard_pins(self):
        self.assertEqual(greenfield.NODE_PIN, "22.22.2")
        self.assertEqual(set(greenfield.NODE_ARCHIVE_SHA256), {"aarch64", "x86_64"})
        self.assertTrue(all(len(value) == 64 for value in greenfield.NODE_ARCHIVE_SHA256.values()))

    def test_portable_node_paths_do_not_depend_on_system_node(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            tools = root / ".node" / "bin"
            tools.mkdir(parents=True)
            (tools / "node").write_bytes(b"mock")
            with self.assertRaises(greenfield.Blocked):
                greenfield.node_commands(root)
            (tools / "npm").write_bytes(b"mock")
            node, npm, env = greenfield.node_commands(root)
            self.assertEqual(node, str(tools / "node"))
            self.assertEqual(npm, str(tools / "npm"))
            self.assertTrue(env["PATH"].startswith(str(tools)))

    def test_hpi_existing_import_rejects_changed_rights_record(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "manifest.json").write_text('{"rights_record_sha256":"first"}')
            with patch.object(greenfield, "verify_hpi", return_value={"status": "VERIFIED"}):
                with self.assertRaises(greenfield.Blocked):
                    greenfield.hpi_import(root, {"rights_record_sha256": "different"})

    def test_deep_research_source_check_never_enables_extra_tools(self):
        with tempfile.TemporaryDirectory() as d:
            source = pathlib.Path(d)
            validator = source / "scripts" / "validate_coverage.py"
            validator.parent.mkdir()
            validator.write_text("# test validator\\n")
            result = greenfield.deep_research_check(source)
            self.assertEqual(result["status"], "SOURCE_CHECKED_ONLY")
            self.assertFalse(result["mcp_tools_enabled"])
            self.assertEqual(len(result["validator_sha256"]), 64)

    def test_no_filesystem_mutation_from_plan(self):
        self.assertTrue(callable(greenfield.cli))
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse((pathlib.Path(d) / "greenfield").exists())


if __name__ == "__main__":
    unittest.main()
