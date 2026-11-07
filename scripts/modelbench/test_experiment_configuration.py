"""Contract regressions: frozen budgets, private TRAIN scope, idempotence and stop."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from modelbench import common as c,pipeline
spec=importlib.util.spec_from_file_location('configure_experiment',ROOT/'scripts/configure-experiment.py')
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)


class ConfigurationTests(unittest.TestCase):
    def source(self,folder,seeds=(41,42,43),extra=None):
        path=folder/'source.tar'
        files={'config/budget.json':json.dumps({'seeds':list(seeds),'context_tokens':262144}).encode()}
        for name in ['AGENTS.md','TASKS.md','docs/OFFLINE_AGENT_PROMPT.md','docs/CONTRACT.md']:files[name]=b'Frozen contract'
        if extra:files.update(extra)
        with tarfile.open(path,'w') as out:
            for name,raw in files.items():
                info=tarfile.TarInfo(name);info.size=len(raw);out.addfile(info,io.BytesIO(raw))
        record=folder/'source.json';record.write_text(json.dumps({'approved_commit':'1'*40,'archive_sha256':c.digest(path),'files':{name:{'sha256':__import__('hashlib').sha256(raw).hexdigest()} for name,raw in files.items()}}))
        return {'coding':{'source_record':{'path':str(record),'sha256':c.digest(record)},'package':{'path':str(path),'sha256':c.digest(path)},'source_sha':'1'*40,'seeds':list(seeds)},'model':{'context_tokens':262144}}

    def test_disabled_component_does_not_require_placeholder_pins(self):
        value={'enabled':False,'runtime':{'python':{'path':None,'sha256':None}}}
        with patch.object(c,'safe') as paths:
            self.assertEqual(setup.pin_existing(value),value)
            paths.assert_not_called()

    def test_disabled_coding_never_opens_private_train_or_source(self):
        config=json.loads((ROOT/'config/benchmark.example.json').read_text())
        config['coding']['enabled']=False
        for spec in config['benchmarks'].values():spec['enabled']=False
        profile={'schema_version':1,'experiment':config,'train_source_manifest':{'path':None,'sha256':None},'host_evidence':[]}
        with patch.object(setup,'source_contract') as source, patch.object(setup,'train_check') as train:
            result,readiness=setup.prepare(profile)
            self.assertEqual(readiness['status'],'READY_FOR_REVIEW')
            self.assertEqual(readiness['phase4_blockers'],[])
            self.assertEqual(readiness['checks']['train']['status'],'NOT_REQUESTED')
            source.assert_not_called();train.assert_not_called()

    def test_actual_frozen_seeds_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.source(Path(tmp));self.assertEqual(setup.source_contract(config)['seeds'],[41,42,43])

    def test_source_seed_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.source(Path(tmp));config['coding']['seeds']=[1,2,3]
            with self.assertRaisesRegex(c.Blocked,'seeds differ'):setup.source_contract(config)

    def test_archive_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.source(Path(tmp),extra={'../escape':b'x'})
            with self.assertRaisesRegex(c.Blocked,'Unsafe source'):setup.source_contract(config)

    def test_context_must_not_be_reduced(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=self.source(Path(tmp));config['model']['context_tokens']=131072
            with self.assertRaisesRegex(c.Blocked,'context'):setup.source_contract(config)

    def test_false_train_disclosure_never_reads_source_or_approves_gold(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rights=root/'rights.json';rights.write_text(json.dumps({'approved':True,'worker_disclosure_approved':False,'local_models_only':True}))
            bundle=root/'train.jsonl';bundle.write_bytes(b'private synthetic test')
            manifest=root/'manifest.json';manifest.write_text('{}')
            pin=lambda p:{'path':str(p),'sha256':c.digest(p)}
            config={'coding':{'rights_record':pin(rights),'train_bundle':pin(bundle),'approve_worker_disclosure':True}}
            with patch.object(setup.greenfield,'verify_hpi') as verify:
                with self.assertRaisesRegex(c.Blocked,'disclosure'):setup.train_check(config,pin(manifest))
                verify.assert_not_called()

    def test_supplied_wrong_hash_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'artifact';path.write_bytes(b'new')
            with self.assertRaisesRegex(c.Blocked,'hash differs'):setup.pin_existing({'path':str(path),'sha256':'0'*64})

    def test_repeat_publication_does_not_touch_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'config';config={'fixed':True};receipt={'status':'BLOCKED','configuration_sha256':'a','technical_blockers':[],'phase4_blockers':['external gate']}
            setup.publish(root,config,receipt)
            snapshot=lambda:{p.name:(p.read_bytes(),p.stat().st_mode,p.stat().st_mtime_ns) for p in root.iterdir()}
            before=snapshot();setup.publish(root,config,receipt);self.assertEqual(snapshot(),before)

    def test_changed_input_preserves_both_existing_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'config';receipt={'status':'BLOCKED','configuration_sha256':'a','technical_blockers':[],'phase4_blockers':[]}
            setup.publish(root,{'fixed':True},receipt);before={p.name:p.read_bytes() for p in root.iterdir()}
            with self.assertRaisesRegex(c.Blocked,'new output'):setup.publish(root,{'fixed':False},receipt)
            self.assertEqual({p.name:p.read_bytes() for p in root.iterdir()},before)

    def test_disabled_coding_never_touches_worker(self):
        with patch.object(pipeline.worker,'validate_config') as worker,patch.object(c,'pin') as pin:
            with self.assertRaisesRegex(c.Blocked,'explicitly disabled'):pipeline.coding({'coding':{'enabled':False}},None,None,'run',41)
            worker.assert_not_called();pin.assert_not_called()

    def test_unqualified_adapter_never_runs_a_command(self):
        from modelbench import adapters
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);exe=root/'adapter';exe.write_text('#!/bin/sh\nexit 0\n')
            data=root/'data';data.write_text('synthetic')
            pin=lambda p:{'path':str(p),'sha256':c.digest(p)}
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'schema_version':1,'files':[dict(pin(data),revision='synthetic-v1')]}))
            definition=root/'definition.json';definition.write_text(json.dumps({'qualification_status':'BLOCKED'}))
            spec={'executable':pin(exe),'data_manifest':pin(manifest),'definition':pin(definition),'version':'fixed-v1','timeout_seconds':1}
            with patch.object(c,'execute') as execute:
                with self.assertRaisesRegex(c.Blocked,'not qualified'):adapters.external(spec,{'benchmark':'swe_bench'},root)
                execute.assert_not_called()

    def test_runtime_metadata_must_match_complete_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);python=root/'python';python.write_bytes(b'owned interpreter');lock=root/'lock';lock.write_text('lm_eval==0.4.13\n')
            pin=lambda p:{'path':str(p),'sha256':c.digest(p)}
            runtime={'python':pin(python),'requirements_lock':pin(lock),'distribution':'lm_eval','version':'0.4.13'}
            result=subprocess.CompletedProcess([],0,json.dumps([['lm_eval','0.4.13',False],['unexpected','1.0',False]]),'')
            with patch.object(setup.subprocess,'run',return_value=result):
                with self.assertRaisesRegex(c.Blocked,'full distribution lock'):setup.runtime_check(runtime)

if __name__=='__main__':unittest.main()
