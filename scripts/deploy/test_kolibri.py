"""Offline safety regression for the single-model orchestration entrypoint."""
import contextlib
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('kolibri_entrypoint', Path(__file__).with_name('kolibri.py'))
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)
CTX, POLICY, PLAN = entry.load_plan(ROOT)
from modules import lifecycle, deployment
from modules.common import atomic_json
from modules.profiles import ContractError


class EntryTests(unittest.TestCase):
    def test_plan_is_read_only_and_rejects_other_model_argument(self):
        with patch.object(entry, 'submit') as submit, patch.object(entry, 'status') as status:
            self.assertEqual(entry.main(['plan']), 0)
            submit.assert_not_called(); status.assert_not_called()
        with self.assertRaises(SystemExit) as error:
            entry.main(['deploy', 'mistral-small-4'])
        self.assertEqual(error.exception.code, 2)

    def test_json_policy_rejects_unknown_keys_and_unsafe_deadline(self):
        from modules import profiles
        original = profiles.read_json
        for change in ({'unknown': True}, {'runtime_seconds': 7200}):
            def altered(path):
                data=original(path)
                if Path(path).name=='kolibri-deployment.json':data.update(change)
                return data
            with patch.object(profiles, 'read_json', side_effect=altered), self.assertRaises(ContractError):
                entry.load_plan(ROOT)

    def test_missing_calibration_fails_before_systemd_or_runtime_initialization(self):
        with patch.object(CTX, 'identity'), patch.object(entry, 'SPARK_ROOT', ROOT), \
             patch.object(entry.platform, 'node', return_value=CTX.defaults['hostname']), \
             patch.object(CTX, 'initialize') as initialize, patch.object(entry.subprocess, 'run') as run, \
             patch.object(entry, 'calibration_artifact', side_effect=ContractError('missing calibration')):
            with self.assertRaises(ContractError):entry.submit(CTX,POLICY,PLAN,'deploy',ROOT)
            initialize.assert_not_called();run.assert_not_called()

    def test_completed_acceptance_reused_failed_one_requires_review(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx=SimpleNamespace(root=Path(temp),model=CTX.model)
            p=ctx.root/'tools/benchmark/acceptances/accepted/receipt.json';p.parent.mkdir(parents=True)
            state={'release':'retained-v5','fingerprint':'f'*64}
            data={'run_id':'accepted','release':state['release'],'manifest_sha256':ctx.model['kv_calibration']['sha256'],
                  'after':{'unit':{'MainPID':'123'}},'status':'VERIFIED_CAPACITY_AND_SEMANTIC_PROTOCOL'}
            p.write_text(json.dumps(data));self.assertEqual(entry.acceptance_id(ctx,state,'123'),('accepted',True))
            self.assertEqual(entry.acceptance_id(ctx,state,'456'),('deployment-'+('f'*12)+'-456',False))
            data['status']='FAILED';p.write_text(json.dumps(data))
            with self.assertRaises(ContractError):entry.acceptance_id(ctx,state,'123')

    def test_active_benchmark_preserved_and_lifecycle_not_entered(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx=SimpleNamespace(root=Path(temp));p=ctx.root/'tools/benchmark/active-run.json';p.parent.mkdir(parents=True);p.write_text('{"run_id":"existing"}')
            with self.assertRaises(ContractError), entry.benchmark_guard(ctx):self.fail('guard entered')
            self.assertEqual(p.read_text(),'{"run_id":"existing"}')

    def test_busy_model_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx=SimpleNamespace(root=Path(temp))
            with patch.object(lifecycle,'service_state',return_value={'ActiveState':'active'}), \
                 patch.object(entry,'metrics',return_value='vllm:num_requests_running{model="kolibri-1"} 1\n'):
                with self.assertRaises(ContractError),entry.benchmark_guard(ctx):self.fail('guard entered')

    def test_acceptance_rollback_preserves_committed_journals(self):
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);candidate={'release':str(base/'candidate')};before={'release':'original'}
            ctx=SimpleNamespace(base=base,id='kolibri-1',locked=contextlib.nullcontext)
            folder=base/'operation';folder.mkdir();Path(candidate['release']).mkdir()
            journal=base/'kolibri-1-transaction.json';transaction={'phase':'committed','candidate':candidate['release'],'previous':before}
            atomic_json(journal,transaction);atomic_json(Path(candidate['release'])/'transaction.json',transaction)
            original=journal.read_bytes()
            with patch.object(entry,'benchmark_guard',return_value=contextlib.nullcontext()), \
                 patch.object(lifecycle,'managed',return_value=candidate),patch.object(lifecycle,'service_state',return_value={'MainPID':'1'}), \
                 patch.object(deployment,'rollback') as rollback:
                self.assertTrue(entry.rollback_candidate(ctx,folder,before,candidate));rollback.assert_called_once()
            self.assertEqual((folder/'transaction-before-acceptance-rollback.json').read_bytes(),original)
            with patch.object(deployment,'rollback') as rollback:
                self.assertFalse(entry.rollback_candidate(ctx,folder,before,before));rollback.assert_not_called()

    def test_rollback_refuses_remote_divergence(self):
        with tempfile.TemporaryDirectory() as temp:
            ctx=SimpleNamespace(locked=contextlib.nullcontext)
            with patch.object(entry,'benchmark_guard',return_value=contextlib.nullcontext()), \
                 patch.object(lifecycle,'managed',return_value={'release':'unexpected'}),patch.object(deployment,'rollback') as rollback:
                with self.assertRaises(ContractError):entry.rollback_candidate(ctx,Path(temp),{'release':'old'},{'release':'candidate'})
                rollback.assert_not_called()

    def test_failed_child_and_timeout_preserve_failed_step_without_retries(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);receipt={'steps':[]}
            with self.assertRaises(ContractError):
                entry.run_step(folder,receipt,'failure',[sys.executable,'-B','-c','raise SystemExit(7)'],5,None)
            self.assertEqual(receipt['steps'][0]['exit_code'],7)
            self.assertTrue((folder/'failure.log').exists())
            with self.assertRaises(subprocess.TimeoutExpired):
                entry.run_step(folder,receipt,'timeout',[sys.executable,'-B','-c','import time;time.sleep(5)'],0.02,None)
            self.assertTrue((folder/'timeout.log').exists())
            self.assertEqual(receipt['steps'][-1]['status'], 'FAILED')

    def test_worker_reuses_acceptance_and_rolls_back_new_candidate_on_failure(self):
        for changed, failure in ((False, False), (True, True)):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                base=Path(temp); folder=base/'operations/job';folder.mkdir(parents=True)
                ctx=SimpleNamespace(base=base,root=base,id='kolibri-1',package=CTX.package,
                    defaults=CTX.defaults,identity=lambda:None,environment=lambda:{})
                job=dict(PLAN,action='deploy',policy=POLICY,
                    driver_sha256=hashlib.sha256(Path(entry.__file__).read_bytes()).hexdigest())
                atomic_json(folder/'job.json',job)
                before={'release':'old','fingerprint':PLAN['fingerprint']}
                candidate={'release':'new' if changed else 'old','fingerprint':PLAN['fingerprint']}
                states=[before,candidate,candidate]
                def step(folder,receipt,name,*args):
                    receipt['steps'].append({'name':name})
                    if failure and name=='acceptance':raise ContractError('fixture failure')
                with patch.object(entry,'load_plan',return_value=(ctx,POLICY,PLAN)), \
                     patch.object(entry,'job_provenance',return_value={'unit':'fixture'}), \
                     patch.object(entry,'calibration_artifact',return_value={'status':'verified'}), \
                     patch.object(entry,'benchmark_guard',return_value=contextlib.nullcontext()), \
                     patch.object(lifecycle,'managed',side_effect=states), \
                     patch.object(lifecycle,'service_state',return_value={'MainPID':'123'}), \
                     patch.object(entry,'acceptance_id',return_value=('existing',True)), \
                     patch.object(entry,'run_step',side_effect=step), \
                     patch.object(entry,'rollback_candidate',return_value=True) as rollback:
                    if failure:
                        with self.assertRaises(ContractError):entry.run_worker(folder)
                        rollback.assert_called_once_with(ctx,folder,before,candidate)
                    else:
                        self.assertEqual(entry.run_worker(folder),0);rollback.assert_not_called()
                result=json.loads((folder/'receipt.json').read_text())
                self.assertEqual(result['status'],'FAILED' if failure else 'COMPLETED')
                self.assertTrue(result['acceptance']['reused_completed_id'])
                self.assertEqual([s['name'] for s in result['steps']],['lifecycle','acceptance'])


if __name__=='__main__':unittest.main()
