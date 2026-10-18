"""Calibration failure gates with synthetic tensors; no GPU or host mutations."""
import copy
import math
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import json
import hashlib
import ast
import importlib.util
from types import ModuleType
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.calibration import scales, prompts, check_loaded, export_bf16_scales, export_kv_only_scales
from modules.profiles import ContractError
from modules import environment
from modules import verifier


class CalibrationTests(unittest.TestCase):
    def test_nonempty_degenerate_calibrated_completion_is_rejected(self):
        ctx = SimpleNamespace(id='kolibri-1', model={'kv_calibration': {}, 'verification': {'smoke_tokens': 64}},
                              event=lambda *a, **k: None)
        response = {'choices': [{'text': ' of of of of'}], 'usage': {'completion_tokens': 64}}
        with patch.object(verifier, 'request', return_value=response):
            with self.assertRaises(ContractError):
                verifier.smoke(ctx)
        response['choices'][0]['text'] = ' Berlin. It is the capital.'
        with patch.object(verifier, 'request', return_value=response):
            self.assertTrue(verifier.smoke(ctx)['semantic_fixture_verified'])

    def test_bf16_query_scope_preserves_observed_kv_without_query_rescaling(self):
        raw = scales(self.observations(), 1.1, 448)
        original = copy.deepcopy(raw)
        full = export_bf16_scales(raw)
        kv = export_kv_only_scales(raw)
        self.assertEqual(raw, original)
        for name, row in kv.items():
            self.assertEqual((row['q_scale'], row['prob_scale']), (1.0, 1.0))
            self.assertEqual((row['k_scale'], row['v_scale']), (full[name]['k_scale'], full[name]['v_scale']))
        missing = copy.deepcopy(raw)
        next(iter(missing.values())).pop('v_scale')
        with self.assertRaises(ContractError):
            export_kv_only_scales(missing)

    def test_bf16_export_preserves_bounds_and_is_exactly_representable(self):
        import struct
        values = scales(self.observations(), 1.1, 448)
        rounded = export_bf16_scales(values)
        self.assertEqual(export_bf16_scales(rounded), rounded)
        for name, row in rounded.items():
            for field, value in row.items():
                self.assertGreaterEqual(value, values[name][field])
                self.assertLessEqual(value / values[name][field], 1.008)
                self.assertEqual(struct.unpack('>I', struct.pack('>f', value))[0] & 65535, 0)
        self.assertGreaterEqual(next(iter(rounded.values()))['prob_scale'] * 448, 1)

    def test_prepare_validates_flat_ids_before_any_llm_import(self):
        class Tokenizer:
            def __len__(self):
                return 4000
            def apply_chat_template(self, messages, **kwargs):
                return list(range(3000)) if kwargs.get("return_dict") is False else {"input_ids": list(range(3000))}
        fake = ModuleType("vllm"); fake.__path__ = []
        plugins = ModuleType("vllm.plugins"); plugins.load_general_plugins = lambda: None
        tokenizers = ModuleType("vllm.tokenizers"); tokenizers.get_tokenizer = lambda _: Tokenizer()
        path = Path(__file__).resolve().parents[1] / "calibrate-worker.py"
        spec = importlib.util.spec_from_file_location("calibration_input_worker", path)
        worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {"vllm": fake, "vllm.plugins": plugins, "vllm.tokenizers": tokenizers}):
            job = Path(temp) / "job.json"
            job.write_text(json.dumps({"snapshot": "unused", "spec": {"samples": 32,
                "languages": ["en", "de", "fr", "code"], "input_tokens": 2048}}))
            with patch.object(sys, "argv", [str(path), "--job", str(job), "--prepare"]):
                worker.main()  # Fake vllm deliberately has no LLM constructor.
            prepared = json.loads((Path(temp) / "prepared-inputs.json").read_text())
            self.assertEqual(len(prepared["inputs"]), 32)
            self.assertEqual({len(r["prompt_token_ids"]) for r in prepared["inputs"]}, {2048})
            self.assertEqual(prepared["inputs"][0]["prompt_token_ids"][-64:], list(range(2936, 3000)))

    def test_observer_rpc_uses_only_named_methods_under_secure_serialization(self):
        worker = Path(__file__).resolve().parents[1] / "calibrate-worker.py"
        tree = ast.parse(worker.read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in ("collective_rpc", "apply_model")]
        self.assertEqual({n.func.attr for n in calls}, {"collective_rpc"})
        self.assertEqual({n.args[0].value for n in calls}, {"calibration_begin", "calibration_end"})
        self.assertTrue(all(isinstance(n.args[0], ast.Constant) for n in calls))

    def observations(self):
        return {"model.layers.%d.self_attn.attn" % i:
                {"calls": 64, "tokens": 65536, "absmax": {"q": 8.0, "k": 7.0, "v": 50.0}} for i in range(50)}

    def test_coverage_and_nonfinite_values_refused(self):
        valid = self.observations()
        self.assertEqual(len(scales(valid, 1.1, 448)), 50)
        for value in (math.nan, math.inf, -1, 0):
            changed = copy.deepcopy(valid)
            next(iter(changed.values()))["absmax"]["k"] = value
            with self.assertRaises(ContractError):
                scales(changed, 1.1, 448)
        next(iter(valid.values()))["tokens"] = 65535
        with self.assertRaises(ContractError):
            scales(valid, 1.1, 448)

    def test_actual_and_host_scale_must_match(self):
        expected = scales(self.observations(), 1.1, 448)
        modules = []
        for name, values in expected.items():
            attrs = {"_" + field: SimpleNamespace(item=lambda v=value: v) for field, value in values.items()}
            attrs.update({"_" + field + "_float": value for field, value in values.items()})
            modules.append((name, SimpleNamespace(**attrs)))
        model = SimpleNamespace(named_modules=lambda: modules)
        self.assertEqual(check_loaded(model, expected), expected)
        modules[0][1]._k_scale_float = 1.0
        with self.assertRaises(RuntimeError):
            check_loaded(model, expected)

    def test_inputs_are_deterministic_and_separate(self):
        spec = {"samples": 32, "languages": ["en", "de", "fr", "code"]}
        rows = prompts(spec)
        self.assertEqual(rows, prompts(spec))
        self.assertEqual(len({row["text"] for row in rows}), 32)
        self.assertEqual([sum(r["language"] == x for r in rows) for x in spec["languages"]], [8] * 4)

    def test_environment_is_borrowed_without_package_install_and_drift_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, release = root / "baseline", root / "candidate"
            source.mkdir(); release.mkdir(); (source / "venv").mkdir()
            frozen = "synthetic-package==1.0\n"
            (source / "requirements.lock").write_text(frozen)
            original = {"id": "kolibri-1", "revision": "a" * 40, "packages": ["synthetic-package==1.0"]}
            (source / "profile.json").write_text(json.dumps({"defaults": {}, "model": original}))
            model = dict(original, kv_calibration={"manifest": "unused", "sha256": "unused", "source_release": str(source),
                       "requirements_sha256": hashlib.sha256(frozen.encode()).hexdigest()})
            ctx = SimpleNamespace(model=model, defaults={}, environment=lambda *a: {}, event=lambda *a, **k: None)
            with patch("modules.calibration.validate_manifest"), patch("modules.lifecycle.managed", return_value={"release": str(source)}), patch("modules.environment.run", return_value=frozen) as runner:
                self.assertEqual(environment.prepare(ctx, release), release / "venv/bin/python")
                self.assertEqual((release / "venv").resolve(), source / "venv")
                self.assertEqual(runner.call_args.args[0][-2:], ["freeze", "--all"])
                changed = root / "changed"; changed.mkdir()
                ctx.model["packages"] = ["changed==2"]
                with self.assertRaises(ContractError):
                    environment.prepare(ctx, changed)
                self.assertFalse((changed / "venv").exists())


if __name__ == "__main__":
    unittest.main()
