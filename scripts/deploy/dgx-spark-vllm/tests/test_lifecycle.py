#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local failure-gate tests; temp fixtures and fake systemd, no GPU/SSH/sudo.

python3 -B scripts/deploy/dgx-spark-vllm/tests/test_lifecycle.py
profile fixtures -> gates / cutover failures -> assert preservation and rollback
"""
import copy
import os
import pwd
import hashlib
import io
import json
import sys
import tempfile
import socket
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules import profiles, compatibility, lifecycle, deployment, verifier
from modules.common import Context, atomic_json

PACKAGE = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.profile = profiles.load(PACKAGE, "kolibri-1")
        self.profile["defaults"]["user"] = pwd.getpwuid(os.geteuid()).pw_name

    def test_fresh_host_absent_unit_is_distinct_from_unavailable_systemd(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = Context(PACKAGE, self.profile)
            ctx.unit_path = Path(temp) / 'absent.service'
            ctx.state_path = Path(temp) / 'absent.json'
            result = Mock(returncode=1, stdout='LoadState=not-found\nActiveState=inactive\nMainPID=0\n')
            with patch.object(lifecycle.subprocess, 'run', return_value=result):
                self.assertIsNone(lifecycle.managed(ctx))
            result = Mock(returncode=1, stdout='', stderr='bus unavailable')
            with patch.object(lifecycle.subprocess, 'run', return_value=result), self.assertRaises(profiles.ContractError):
                lifecycle.service_state(ctx)

    def test_port_guard_rejects_a_live_listener(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            server.listen()
            profile = copy.deepcopy(self.profile)
            profile["model"]["server"]["port"] = server.getsockname()[1]
            with self.assertRaises(profiles.ContractError):
                lifecycle.ensure_free_port(Context(PACKAGE, profile))

    def test_port_guard_allows_closed_listener_with_time_wait(self):
        with socket.socket() as server, socket.socket() as client:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            address = server.getsockname()
            server.listen()
            client.connect(address)
            accepted, _ = server.accept()
            accepted.close()  # Server performs the active close.
            self.assertEqual(client.recv(1), b"")
            client.close()
            server.close()
            with socket.socket() as plain:
                with self.assertRaises(OSError):
                    plain.bind(address)  # Reproduces the previous false conflict.
            profile = copy.deepcopy(self.profile)
            profile["model"]["server"]["port"] = address[1]
            lifecycle.ensure_free_port(Context(PACKAGE, profile))

    def test_profiles_and_fixed_context(self):
        self.assertEqual(self.profile["model"]["server"]["max_model_len"], 262144)
        self.assertFalse(profiles.load(PACKAGE, "mistral-small-4")["model"]["enabled"])
        schema = profiles.read_json(PACKAGE / "config/schema.json")
        for value in ("auto", 131072, True, None):
            model = copy.deepcopy(self.profile["model"])
            model["server"]["max_model_len"] = value
            with self.assertRaises(profiles.ContractError):
                profiles.validate(model, schema["$defs"]["model"], root=schema)

    def test_unknown_key_and_shell_package_rejected(self):
        schema = profiles.read_json(PACKAGE / "config/schema.json")
        for key, value in (("server_args", ["--max-model-len", "auto"]), ("packages", ["vllm;touch /tmp/unwanted"])):
            model = copy.deepcopy(self.profile["model"])
            model[key] = value
            with self.assertRaises(profiles.ContractError):
                profiles.validate(model, schema["$defs"]["model"], root=schema)

    def test_duplicate_keys_and_nan_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profile.json"
            for text in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":1,}'):
                path.write_text(text)
                with self.assertRaises(profiles.ContractError):
                    profiles.read_json(path)

    def test_physical_memory_gate_reports_host_swap_without_counting_it(self):
        model = self.profile["model"]
        before = copy.deepcopy(model)
        mem = {"MemTotal": int(121.69 * GIB), "MemAvailable": 119 * GIB,
               "SwapTotal": 16 * GIB, "SwapFree": 16 * GIB}
        self.assertFalse(compatibility.check_memory(model, mem)["capacity_proven"])
        resident_cached = dict(mem, SwapFree=mem["SwapTotal"] - 28672, SwapCached=28672)
        self.assertEqual(compatibility.check_memory(model, resident_cached)["host_nonresident_swap_bytes"], 0)
        host_swap = dict(mem, SwapFree=15 * GIB)
        self.assertEqual(compatibility.check_memory(model, host_swap)["host_nonresident_swap_bytes"], GIB)
        self.assertTrue(compatibility.check_memory(model, host_swap)["host_swap_warning"])
        for changed in ({"MemAvailable": 100 * GIB},):
            bad = dict(mem, **changed)
            with self.assertRaises(profiles.ContractError):
                compatibility.check_memory(model, bad)
        self.assertEqual(model, before)
        too_small = copy.deepcopy(model)
        too_small["server"]["gpu_memory_utilization"] = 0.5
        with self.assertRaises(profiles.ContractError):
            compatibility.check_memory(too_small, mem)

    def test_checkpoint_mismatch_rejected(self):
        ctx = Context(PACKAGE, self.profile)
        good = {"architectures": ["Kolibri1ForCausalLM"], "max_position_embeddings": 262144,
                "quantization_config": {"quant_method": "fp8"}}
        compatibility.model_config(ctx, good)
        for key, value in (("architectures", ["Other"]), ("max_position_embeddings", 131072), ("quantization_config", {"quant_method": "gptq"})):
            with self.assertRaises(profiles.ContractError):
                compatibility.model_config(ctx, dict(good, **{key: value}))

    def test_server_argv_exact_context(self):
        with tempfile.TemporaryDirectory() as temp:
            release = Path(temp)
            atomic_json(release / "weights.json", {"snapshot": "/safe/model"})
            argv = lifecycle.server_argv(self.profile, release)
            self.assertEqual(argv[argv.index("--max-model-len") + 1], "262144")
            self.assertNotIn("auto", argv)
            self.assertIn("--enable-auto-tool-choice", argv)

    def test_health_does_not_accept_reduced_or_missing_context(self):
        ctx = Context(PACKAGE, self.profile)
        for length in (None, 131072):
            with patch.object(verifier, "request", side_effect=[{}, {"data": [{"id": "kolibri-1", "max_model_len": length}]}]):
                with self.assertRaises(profiles.ContractError):
                    verifier.health(ctx)

    def fixture(self, temp):
        ctx = Context(PACKAGE, self.profile)
        ctx.base = Path(temp) / "build"
        ctx.base.mkdir()
        ctx.log_root = Path(temp) / "logs"
        ctx.log_root.mkdir()
        ctx.unit_path = Path(temp) / "server.service"
        ctx.state_path = ctx.base / "state.json"
        ctx.event = Mock()
        previous = ctx.base / "releases/previous"
        previous.mkdir(parents=True)
        (previous / "server.service").write_text("previous unit")
        atomic_json(previous / "profile.json", self.profile)
        ctx.unit_path.write_text("previous unit")
        state = {"owner": "AI-Model/dgx-spark-vllm/v1", "model": ctx.id, "release": str(previous),
                 "unit_sha256": hashlib.sha256(b"previous unit").hexdigest(), "fingerprint": "old"}
        atomic_json(ctx.state_path, state)
        return ctx, state

    def test_unowned_and_diverged_unit_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            ctx.unit_path.write_text("unexpected remote change")
            with self.assertRaises(profiles.ContractError):
                lifecycle.managed(ctx)
            self.assertEqual(ctx.unit_path.read_text(), "unexpected remote change")
            ctx.state_path.unlink()
            with self.assertRaises(profiles.ContractError):
                lifecycle.managed(ctx)

    def test_same_deploy_does_not_install_or_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            state["fingerprint"] = profiles.fingerprint(ctx.profile, PACKAGE)
            with patch.object(lifecycle, "managed", return_value=state), \
                 patch.object(lifecycle, "service_state", return_value={"ActiveState": "active"}), \
                 patch.object(verifier, "health", return_value={"healthy": True}), \
                 patch.object(environment_module(), "prepare") as prepare, \
                 patch.object(lifecycle, "systemctl") as systemctl:
                deployment.deploy(ctx)
                prepare.assert_not_called()
                systemctl.assert_not_called()

    def test_staging_failure_leaves_existing_server_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            with patch.object(lifecycle, "managed", return_value=state), \
                 patch.object(compatibility, "host", return_value={}), \
                 patch.object(environment_module(), "snapshot_source"), \
                 patch.object(environment_module(), "prepare", side_effect=profiles.ContractError("no wheel")), \
                 patch.object(lifecycle, "systemctl") as systemctl:
                with self.assertRaises(profiles.ContractError):
                    deployment.deploy(ctx)
                systemctl.assert_not_called()
                self.assertEqual(ctx.unit_path.read_text(), "previous unit")
                self.assertEqual(profiles.read_json(ctx.state_path), state)

    def test_failed_cutover_rolls_back_running_previous_release(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            def install(c, source):
                c.unit_path.write_bytes(Path(source).read_bytes())
            with patch.object(lifecycle, "managed", return_value=state), \
                 patch.object(lifecycle, "service_state", return_value={"ActiveState": "active"}), \
                 patch.object(compatibility, "host", return_value={}), \
                 patch.object(environment_module(), "snapshot_source"), \
                 patch.object(environment_module(), "prepare", return_value="python"), \
                 patch.object(environment_module(), "download"), \
                 patch.object(deployment, "run", return_value=""), \
                 patch.object(lifecycle, "ensure_free_port"), \
                 patch.object(lifecycle, "install_unit", side_effect=install), \
                 patch.object(lifecycle, "systemctl") as systemctl, \
                 patch.object(verifier, "wait", side_effect=[profiles.ContractError("failed engine"), {"healthy": True}]):
                with self.assertRaises(profiles.ContractError):
                    deployment.deploy(ctx)
                self.assertEqual(ctx.unit_path.read_text(), "previous unit")
                self.assertEqual(profiles.read_json(ctx.state_path), state)
                tx = profiles.read_json(ctx.base / (ctx.id + "-transaction.json"))
                self.assertEqual(tx["phase"], "rolled_back")
                self.assertEqual([call[0][1] for call in systemctl.call_args_list], ["stop", "start", "stop", "start"])

    def test_long_request_requires_exact_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            responses = [{"tokens": [42]}, {"usage": {"prompt_tokens": 262112, "completion_tokens": 32, "total_tokens": 262144}}]
            with patch.object(lifecycle, "managed", return_value=state), \
                 patch.object(lifecycle, "service_state", return_value={"MemorySwapCurrent": "0", "MemorySwapMax": "0"}), \
                 patch.object(verifier, "health", return_value={"advertised_context": 262144}), \
                 patch.object(verifier, "smoke", return_value={"usage": {"prompt_tokens": 8}}), \
                 patch.object(verifier, "request", side_effect=responses) as request:
                result = verifier.verify(ctx, long_context=True)
                self.assertTrue(result["full_context_request_verified"])
                self.assertEqual(len(request.call_args[0][2]["prompt"]), 262112)

    def test_first_failed_deployment_removes_only_its_owned_unit(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, old = self.fixture(temp)
            ctx.state_path.unlink()
            candidate = ctx.base / "releases/candidate"
            candidate.mkdir()
            (candidate / "server.service").write_text("candidate unit")
            ctx.unit_path.write_text("candidate unit")
            transaction = {"previous": None, "candidate": str(candidate),
                           "candidate_unit": str(candidate / "server.service"),
                           "was_active": False, "phase": "switching"}
            def fake_run(argv, **kwargs):
                if "rm" in list(map(str, argv)):
                    self.assertEqual(Path(argv[-1]), ctx.unit_path)
                    ctx.unit_path.unlink()
                return ""
            with patch.object(deployment, "run", side_effect=fake_run), \
                 patch.object(lifecycle, "systemctl"), \
                 patch.object(lifecycle, "service_state", return_value={"ActiveState": "inactive", "MainPID": "0"}):
                deployment.rollback(ctx, transaction)
            self.assertFalse(ctx.unit_path.exists())
            self.assertTrue(candidate.exists())
            self.assertTrue(Path(old["release"]).exists())

    def test_rollback_refuses_unexpected_unit_change(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            candidate = ctx.base / "releases/candidate"
            candidate.mkdir()
            (candidate / "server.service").write_text("candidate unit")
            ctx.unit_path.write_text("unexpected external unit")
            transaction = {"previous": state, "candidate": str(candidate),
                           "candidate_unit": str(candidate / "server.service"), "was_active": True}
            with patch.object(lifecycle, "systemctl") as systemctl:
                with self.assertRaises(profiles.ContractError):
                    deployment.rollback(ctx, transaction)
                systemctl.assert_not_called()
                self.assertEqual(ctx.unit_path.read_text(), "unexpected external unit")

    def test_interrupted_cutover_recovery_is_explicit_in_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            transaction = {"phase": "switching", "previous": state}
            atomic_json(ctx.base / (ctx.id + "-transaction.json"), transaction)
            with patch.object(deployment, "rollback") as rollback:
                deployment.recover_interrupted(ctx)
                rollback.assert_called_once_with(ctx, transaction)

    def test_clean_environment_ignores_serving_overrides(self):
        ctx = Context(PACKAGE, self.profile)
        with patch.dict("os.environ", {"VLLM_MAX_MODEL_LEN": "123", "PYTHONPATH": "/foreign",
                                       "HF_TOKEN": "fake-fixture", "PIP_INDEX_URL": "https://foreign.invalid"}):
            env = ctx.environment()
        for key in ("VLLM_MAX_MODEL_LEN", "PYTHONPATH", "HF_TOKEN", "PIP_INDEX_URL"):
            self.assertNotIn(key, env)
        self.assertIn("runtime/spark-a922/models", env["HF_HOME"])
        for key in ("CUDA_CACHE_PATH", "VLLM_CACHE_ROOT", "FLASHINFER_WORKSPACE_BASE",
                    "TORCHINDUCTOR_CACHE_DIR", "NUMBA_CACHE_DIR", "HF_MODULES_CACHE"):
            self.assertTrue(env[key].startswith(str(ctx.root) + "/"), key)

    def test_vendor_exception_rejects_any_additional_pip_error(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            result = Mock(returncode=1, stdout=ctx.defaults["wheel_metadata_exceptions"][0]["diagnostic"] + "\nother-package has incompatible dependency\n")
            with patch.object(environment_module().subprocess, "run", return_value=result):
                with self.assertRaises(profiles.ContractError):
                    environment_module().check_dependencies(ctx, ctx.base, "python", ctx.log_root / "install.log")

    def test_start_refuses_changed_profile_without_stopping_server(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            with patch.object(lifecycle, "managed", return_value=state), \
                 patch.object(lifecycle, "systemctl") as systemctl:
                with self.assertRaises(profiles.ContractError):
                    deployment.start(ctx, restart=True)
                systemctl.assert_not_called()

    def test_start_and_stop_converge_without_restarting(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            state["fingerprint"] = profiles.fingerprint(ctx.profile, PACKAGE)
            with patch.object(lifecycle, "managed", return_value=state), \
                 patch.object(lifecycle, "service_state", return_value={"ActiveState": "active"}), \
                 patch.object(verifier, "health", return_value={"healthy": True}), \
                 patch.object(lifecycle, "systemctl") as systemctl:
                deployment.start(ctx)
                systemctl.assert_not_called()
            with patch.object(lifecycle, "managed", return_value=state), \
                 patch.object(lifecycle, "service_state", return_value={"ActiveState": "inactive", "MainPID": "0"}), \
                 patch.object(lifecycle, "systemctl") as systemctl:
                deployment.stop(ctx)
                systemctl.assert_not_called()

    def test_successful_cutover_backs_up_previous_unit_and_commits(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            def install(c, source):
                release = Path(source).parent
                self.assertEqual((release / "previous.service").read_text(), "previous unit")
                self.assertEqual(profiles.read_json(release / "previous-state.json"), state)
                c.unit_path.write_bytes(Path(source).read_bytes())
            with patch.object(lifecycle, "managed", return_value=state), \
                 patch.object(lifecycle, "service_state", return_value={"ActiveState": "active"}), \
                 patch.object(compatibility, "host", return_value={}), \
                 patch.object(environment_module(), "snapshot_source"), \
                 patch.object(environment_module(), "prepare", return_value="python"), \
                 patch.object(environment_module(), "download"), \
                 patch.object(deployment, "run", return_value=""), \
                 patch.object(lifecycle, "ensure_free_port"), \
                 patch.object(lifecycle, "install_unit", side_effect=install), \
                 patch.object(lifecycle, "systemctl"), \
                 patch.object(verifier, "wait", return_value={"advertised_context": 262144}), \
                 patch.object(verifier, "smoke", return_value={"usage": {"completion_tokens": 8}}):
                result = deployment.deploy(ctx)
            self.assertNotEqual(result["release"], state["release"])
            self.assertEqual(profiles.read_json(ctx.state_path), result)
            transaction = profiles.read_json(ctx.base / (ctx.id + "-transaction.json"))
            self.assertEqual(transaction["phase"], "committed")
            self.assertTrue((Path(state["release"]) / "server.service").exists())

    def test_weight_integrity_uses_pinned_file_hash_not_hub_blob_id(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            # Exercise the original checkpoint download path independently of
            # an optional deployment-specific calibration overlay.
            ctx.model.pop("kv_calibration", None)
            ctx.root = Path(temp) / "runtime"
            hub = ctx.root / "models/huggingface/hub"
            snapshot = hub / ("models--" + ctx.model["repository"].replace("/", "--")) / "snapshots" / ctx.model["revision"]
            snapshot.mkdir(parents=True)
            blob = hub / "blobs" / ("d" * 64)
            blob.parent.mkdir()
            blob.write_bytes(b"fixture-weights")
            name = "model-00001-of-00001.safetensors"
            (snapshot / name).symlink_to(blob)
            atomic_json(snapshot / "config.json", {"architectures": ["Kolibri1ForCausalLM"],
                        "max_position_embeddings": 262144, "quantization_config": {"quant_method": "fp8"}})
            atomic_json(snapshot / "model.safetensors.index.json", {"weight_map": {"tensor": name}})
            log = ctx.log_root / (ctx.id + "-" + ctx.run_id + "-download.log")
            log.write_text(json.dumps({"snapshot": str(snapshot)}) + "\n")
            release = ctx.base / "checking"
            release.mkdir()
            digest = hashlib.sha256(blob.read_bytes()).hexdigest()
            metadata = {"sha": ctx.model["revision"], "siblings": [{"rfilename": name,
                        "lfs": {"size": blob.stat().st_size, "sha256": digest}}]}
            opener = Mock()
            opener.open.side_effect = lambda *a, **kw: io.BytesIO(json.dumps(metadata).encode())
            with patch.object(environment_module(), "run"), \
                 patch.object(environment_module().urllib.request, "build_opener", return_value=opener):
                self.assertEqual(environment_module().download(ctx, release, "python"), snapshot)
                record = profiles.read_json(release / "weights.json")
                self.assertEqual(record["shards"][0]["official_lfs_sha256"], digest)
                self.assertNotEqual(blob.name, digest)
                metadata["siblings"][0]["lfs"]["sha256"] = "0" * 64
                with self.assertRaises(profiles.ContractError):
                    environment_module().download(ctx, release, "python")

    def test_cuda_budget_rejects_low_device_free_memory(self):
        ctx = Context(PACKAGE, self.profile)
        with patch.object(compatibility, "run", return_value=json.dumps({"free": 8 * GIB, "total": 121 * GIB})):
            with self.assertRaises(profiles.ContractError):
                compatibility.cuda_budget(ctx, "python")
        with patch.object(compatibility, "run", return_value=json.dumps({"free": 119 * GIB, "total": 121 * GIB})):
            self.assertGreater(compatibility.cuda_budget(ctx, "python")["free"], 112 * GIB)

    def test_cache_advice_preserves_files_and_skips_foreign_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx = Context(PACKAGE, self.profile)
            ctx.root = Path(temp) / "runtime"
            ctx.base = ctx.root / "build/dgx-spark-vllm"
            ctx.base.mkdir(parents=True)
            own = ctx.base / "owned.bin"
            own.write_bytes(b"x" * 1024 ** 2)
            foreign = Path(temp) / "foreign.bin"
            foreign.write_bytes(b"y" * 1024 ** 2)
            (ctx.base / "foreign-link").symlink_to(foreign)
            before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (own, foreign)}
            result = compatibility.reclaim_owned_cache(ctx)
            self.assertEqual(result["files_advised"], 1)
            self.assertFalse(result["contents_modified"])
            for path, digest in before.items():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_verify_rejects_model_swap_before_sending_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx, state = self.fixture(temp)
            with patch.object(lifecycle, "managed", return_value=state), \
                 patch.object(lifecycle, "service_state", return_value={"MemorySwapCurrent": "4096", "MemorySwapMax": "0"}), \
                 patch.object(verifier, "request") as request:
                with self.assertRaises(profiles.ContractError):
                    verifier.verify(ctx)
                request.assert_not_called()


def environment_module():
    from modules import environment
    return environment


if __name__ == "__main__":
    unittest.main(verbosity=2)
