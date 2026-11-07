"""Readiness input boundaries and explicit21-check mapping; no promotion/model."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import copy

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('native_readiness',ROOT/'tools/native_readiness.py');ready=importlib.util.module_from_spec(spec);spec.loader.exec_module(ready)


class ReadinessTests(unittest.TestCase):
    def events(self):
        tools=['playwright_browser_navigate','playwright_browser_snapshot','playwright_browser_tabs']
        common={'route':'/v1/chat/completions','method':'POST','execution_stage':'qualification','effective_output_tokens':2048}
        rows=[dict(common,request_number=i,status=200,upstream_started=True,completed=True,phase='completed',tool_calls=1,tools=tools,usage={'completion_tokens':i*10}) for i in [1,2,3]]
        rows.append(dict(common,status=403,upstream_started=False,completed=False,reason='Qualification complete; C01 readiness required'))
        return rows

    def test_actual_route_complete_usage_and_exact_denial_are_required(self):
        rows=self.events();ready.verify_events(rows,{'generated_tokens':60})
        for mutation in ['route','path-instead-of-route','incomplete','number','usage','cap','generic403','allocated-denial']:
            value=copy.deepcopy(rows)
            if mutation=='route':value[0]['route']='/other'
            elif mutation=='path-instead-of-route':value[0]['path']=value[0].pop('route')
            elif mutation=='incomplete':value[0]['completed']=False
            elif mutation=='number':value[0]['request_number']=2
            elif mutation=='usage':value[0]['usage']['completion_tokens']=11
            elif mutation=='cap':value[0]['effective_output_tokens']=32768
            elif mutation=='generic403':value[3]['reason']='unrelated denial'
            else:value[3]['request_number']=4
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):ready.verify_events(value,{'generated_tokens':60})

    def test_each_publication_crash_resumes_exact_bytes_and_gate_is_last(self):
        sys.path.insert(0,str(ROOT/'tools'));import worker
        for crash_at in [1,2,3]:
            with self.subTest(crash_at=crash_at),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);folder=root/'reviewed';folder.mkdir();run=root/'run';run.mkdir();(root/'inference').mkdir()
                receipt={'fixture':'no real READY'};wrapper={'fixture':'no real C01'};original=ready.immutable_json;writes=[]
                def crash(w,path,value):
                    original(w,path,value);writes.append(path)
                    if len(writes)==crash_at:raise InterruptedError('synthetic crash after publication')
                with patch.object(ready,'immutable_json',side_effect=crash),self.assertRaises(InterruptedError):ready.publish(worker,root,folder,run,receipt,wrapper)
                if crash_at<3:self.assertFalse((root/'inference/ready.json').exists())
                else:self.assertTrue((folder/'ready.json').exists());self.assertTrue((run/'readiness.json').exists())
                before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in writes}
                ready.publish(worker,root,folder,run,receipt,wrapper)
                self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in writes})
                self.assertEqual((root/'inference/ready.json').read_bytes(),worker.encoded(wrapper))

    def test_conflicting_partial_run_receipt_blocks_before_gate_and_is_preserved(self):
        sys.path.insert(0,str(ROOT/'tools'));import worker
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'reviewed';folder.mkdir();run=root/'run';run.mkdir();(root/'inference').mkdir()
            worker.write(run/'readiness.json',{'conflicting':'retained'})
            with self.assertRaisesRegex(worker.Blocked,'Conflicting partial'):ready.publish(worker,root,folder,run,{'fixture':'expected'},{'fixture':'closed'})
            self.assertFalse((root/'inference/ready.json').exists());self.assertEqual(ready.private_json(run/'readiness.json'),{'conflicting':'retained'})

    def test_positive_review_promotion_and_repeat_preserve_all_receipt_bytes(self):
        sys.path.insert(0,str(ROOT/'tools'));import worker,preflight,inference_transport
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'native-review';folder.mkdir(mode=0o700);run=root/'run';run.mkdir(mode=0o700);(root/'inference').mkdir(mode=0o700)
            configuration=root/'gui.json';worker.write(configuration,{'fixture':True})
            (root/'preflight.py').write_bytes(Path(preflight.__file__).read_bytes())
            proof=root/'proof.json';backend=root/'backend.json';worker.write(proof,{'fixture':'model proof'});worker.write(backend,{'fixture':'isolation'})
            index={'fingerprint':'fixture-fingerprint','peers':{},'adapter_sha256':ready.digest(Path(ready.__file__)),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'limits':['fixture only'],
                   'evidence':{'proof':{'path':str(proof),'sha256':ready.digest(proof)},'backend':{'path':str(backend),'sha256':ready.digest(backend)}}}
            worker.write(folder/'index.json',index)
            review=root/'review.json';worker.write(review,{'schema_version':1,'decision':'C00_ACCEPTED','independent_reviewer':'synthetic-test-only','fingerprint':index['fingerprint'],'evidence_index_sha256':ready.digest(folder/'index.json'),'findings':[],'limitations_acknowledged':index['limits']})
            config={'channels':{},'model':{'fixture':True,'backend_identity_sha256':'fixture-identity'}};record={'fingerprint':index['fingerprint']};value={'run_id':'fixture-run'};facts={'policy':{'fixture':True},'peers':{}}
            loaded=(worker,preflight,None,value,root,run,config,record,facts)
            def verify_published(directory,policy):
                gate=ready.private_json(root/'inference/ready.json');receipt=ready.private_json(folder/'ready.json')
                self.assertEqual(gate['receipt']['sha256'],ready.digest(folder/'ready.json'));self.assertEqual(receipt,ready.private_json(run/'readiness.json'))
                self.assertEqual(gate['created_unix'],receipt['created_unix']);self.assertEqual(receipt['policy_sha256'],inference_transport.sha(inference_transport.encoded(policy)))
                preflight.verify_ready(receipt,record,run,config)
            with patch.object(ready,'inspect',return_value=(folder,index)),patch.object(ready,'load',return_value=loaded),patch.object(inference_transport,'coding_gate',side_effect=verify_published):
                self.assertEqual(ready.promote(configuration,review)['status'],'READY')
                files=[folder/'promotion-intent.json',folder/'ready.json',run/'readiness.json',root/'inference/ready.json']
                before={p:(p.read_bytes(),p.stat().st_mtime_ns) for p in files}
                self.assertEqual(ready.promote(configuration,review)['status'],'READY_REUSED')
                self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in files})
                bad=worker.read(review);bad['findings']=['open finding'];review.write_bytes(worker.encoded(bad))
                with self.assertRaisesRegex(worker.Blocked,'independent current'):ready.promote(configuration,review)
                self.assertEqual(before,{p:(p.read_bytes(),p.stat().st_mtime_ns) for p in files})

    def test_resume_preserves_original_time_but_rejects_other_receipt_drift(self):
        sys.path.insert(0,str(ROOT/'tools'));import worker
        identity={'review':'fixed'};expected={'created_unix':200,'model':'fixed','checks':{'a':True}}
        old={'identity':identity,'receipt':dict(expected,created_unix=100)}
        self.assertEqual(ready.resumed_receipt(worker,old,identity,expected)['created_unix'],100)
        for field,value in [('model','changed'),('checks',{}),('created_unix','100')]:
            changed=copy.deepcopy(old);changed['receipt'][field]=value
            with self.subTest(field=field),self.assertRaises(worker.Blocked):ready.resumed_receipt(worker,changed,identity,expected)

    def test_every_sealed_project_module_origin_is_checked(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.dict(sys.modules,{'native_controls':SimpleNamespace(__file__=str(root/'native_controls.py'))}):ready.verify_module_origins(root,['native_controls'])
            with patch.dict(sys.modules,{'native_controls':SimpleNamespace(__file__='/elsewhere/native_controls.py')}),self.assertRaises(ValueError):ready.verify_module_origins(root,['native_controls'])

    def test_only_owned_private_regular_json_not_links_or_public_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'value.json';p.write_text('{"fixture":true}');p.chmod(0o600)
            self.assertEqual(ready.private_json(p),{'fixture':True})
            p.chmod(0o644)
            with self.assertRaises(ValueError):ready.private_json(p)
            p.chmod(0o600);link=root/'link';link.symlink_to(p)
            with self.assertRaises(ValueError):ready.private_json(link)
            link.unlink();os.link(p,link)
            with self.assertRaises(ValueError):ready.private_json(link)

    def test_all_contract_checks_have_explicit_evidence_and_limits(self):
        sys.path.insert(0,str(ROOT/'tools'));import preflight
        mapping=ready.check_map();self.assertEqual(set(mapping),preflight.CHECKS)
        self.assertEqual(len(mapping),21)
        for name,(basis,evidence,meaning) in mapping.items():
            with self.subTest(name=name):self.assertTrue(basis);self.assertTrue(evidence);self.assertGreater(len(meaning),20)
        self.assertIn('not an exercised HTTP redirect',mapping['redirect_to_private_denied'][2])
        self.assertIn('No successful',mapping['service_workers_blocked'][2])

    def test_unsupported_gui_cannot_load_code_or_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'gui.json';p.write_text(json.dumps({'root':str(root),'mode':'INSPECTION_NO_INFERENCE'}));p.chmod(0o600)
            with self.assertRaisesRegex(ValueError,'complete native'):ready.load(p)
            self.assertFalse((root/'inference/ready.json').exists())


if __name__=='__main__':unittest.main()
