"""Regressions for native official-tool CLI compatibility discovered live."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from modelbench import adapters


class StopBeforeInference(Exception):
    pass


class OfficialAdapterTests(unittest.TestCase):
    def test_offline_cache_contains_only_identical_pinned_tokenizer_bytes(self):
        from modelbench import common as c
        config=json.loads((ROOT/'config/benchmark.example.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'tokenizer';source.mkdir()
            for name in ['tokenizer.json','tokenizer_config.json']:(source/name).write_text('{}')
            manifest=root/'data.json';manifest.write_text(json.dumps({'schema_version':1,'files':[{'path':str(p),'sha256':c.digest(p),'revision':config['model']['revision']} for p in source.iterdir()]}))
            spec={'tokenizer':str(source),'data_manifest':{'path':str(manifest),'sha256':c.digest(manifest)}}
            folder=c.private_directory(root/'evidence');home=adapters.aiperf_tokenizer(spec,config['model'],folder)
            snapshot=home/'hub/models--Aleph-Alpha--Kolibri-1/snapshots'/config['model']['revision']
            self.assertEqual(sorted(p.name for p in snapshot.iterdir()),['tokenizer.json','tokenizer_config.json'])
            self.assertTrue(all(not p.is_symlink() and p.read_bytes()==(source/p.name).read_bytes() for p in snapshot.iterdir()))
            with self.assertRaisesRegex(c.Blocked,'appeared concurrently'):adapters.aiperf_tokenizer(spec,config['model'],folder)

    def test_official_zero_error_schema_requires_all_three_observations(self):
        data={'completed_request_count':{'avg':4},'request_error_rate':{'avg':0.0},'error_summary':[]}
        self.assertEqual(adapters.request_errors(data,4),0)
        for change in [{'completed_request_count':{'avg':3}},{'request_error_rate':{'avg':2}},{'error_summary':[{'failed':1}]}]:
            self.assertIsNone(adapters.request_errors(dict(data,**change),4))
        self.assertIsNone(adapters.request_errors({},4))

    def test_retained_bfcl_keeps_original_evidence_and_denies_drift(self):
        from modelbench import common as c,resume,kolibri
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=c.private_directory(root/'old');source=c.private_directory(run/'phase');folder=c.private_directory(root/'new')
            spec={'enabled':True,'adapter':{'version':'fixed'}};model={'id':'kolibri-1'}
            config={'model':model,'benchmarks':{'bfcl':spec}};c.save(run/'configuration.json',config)
            c.save(source/'raw.json',{'synthetic':'call result'})
            phase={'id':'bfcl','status':'PASS','evidence_directory':'phase','result':{'status':'PASS','benchmark':'bfcl','run_id':'original','metrics':{'correct':{'value':1,'unit':'ratio'}}}}
            resume.seal(run,phase,'fixed')
            state={'identity':{'configuration_sha256':c.fingerprint(config)},'live_identity':{'service':{'PID':'fixed'}},'fingerprint':'fixed','phases':[phase]}
            c.save(run/'state.json',state);selection=root/'selection.json';c.save(selection,{'schema_version':1,'source_state':{'path':str(run/'state.json'),'sha256':c.digest(run/'state.json')}})
            selected=dict(spec,retained={'path':str(selection),'sha256':c.digest(selection)})
            with patch.object(kolibri,'service_identity',return_value={'PID':'fixed'}),patch.object(c,'execute',side_effect=AssertionError('no scorer/model command')):
                result=adapters.retained_bfcl(selected,model,folder)
                self.assertEqual(result['repeated_model_requests'],0);self.assertEqual(result['run_id'],'original')
                for item in result['external_evidence']:c.pin(item)
                with self.assertRaisesRegex(c.Blocked,'protocol/model'):adapters.retained_bfcl(dict(selected,adapter={'version':'changed'}),model,folder)
                (source/'raw.json').write_text('tampered')
                with self.assertRaisesRegex(c.Blocked,'evidence changed'):adapters.retained_bfcl(selected,model,folder)
            with patch.object(kolibri,'service_identity',return_value={'PID':'changed'}):
                with self.assertRaisesRegex(c.Blocked,'backend process'):adapters.retained_bfcl(selected,model,folder)

    def test_retained_exports_require_sealed_matching_source_and_live_backend(self):
        from modelbench import common as c,resume,kolibri
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=c.private_directory(root/'old');evidence=c.private_directory(run/'phase')
            spec={'request_count':4};model={'id':'kolibri-1'}
            config={'model':model,'benchmarks':{'aiperf':spec}}
            c.save(run/'configuration.json',config)
            phase={'id':'aiperf','name':'AIPerf','kind':'performance','status':'NOT_EVALUATED','attempt':1,'evidence_directory':'phase'}
            trials=[]
            for concurrency in [1,2,4]:
                for repeat in [1,2,3]:
                    path=evidence/(str(concurrency)+'-'+str(repeat)+'.json');c.save(path,{'synthetic':'export'})
                    trials.append({'concurrency':concurrency,'repeat':repeat,'raw_export':path.name,'raw_sha256':c.digest(path)})
            phase['result']={'trials':trials};resume.seal(run,phase,'fixed')
            state={'identity':{'configuration_sha256':c.fingerprint(config)},'live_identity':{'service':{'PID':'fixed'}},'fingerprint':'fixed','phases':[phase]}
            c.save(run/'state.json',state)
            manifest=root/'retained.json';c.save(manifest,{'schema_version':1,'source_state':{'path':str(run/'state.json'),'sha256':c.digest(run/'state.json')}})
            selected=dict(spec,retained={'path':str(manifest),'sha256':c.digest(manifest)})
            with patch.object(kolibri,'service_identity',return_value={'PID':'fixed'}):
                self.assertEqual(len(adapters.retained_aiperf(selected,model)),9)
                with self.assertRaisesRegex(c.Blocked,'inputs differ'):adapters.retained_aiperf(dict(selected,request_count=8),model)
                (evidence/'1-1.json').write_text('tamper')
                with self.assertRaisesRegex(c.Blocked,'evidence changed'):adapters.retained_aiperf(selected,model)
            with patch.object(kolibri,'service_identity',return_value={'PID':'changed'}):
                with self.assertRaisesRegex(c.Blocked,'backend process'):adapters.retained_aiperf(selected,model)

    def test_lm_eval_cli_overrides_task_yaml_output_limits_explicitly(self):
        config=json.loads((ROOT/'config/benchmark.example.json').read_text());spec=config['benchmarks']['lm_eval']
        spec['output_tokens']=128
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for field in ['tokenizer','hf_home','include_path']:
                path=root/field;path.mkdir();spec[field]=str(path)
            def launch(argv,*args,**kwargs):
                self.assertEqual(argv[argv.index('--gen_kwargs')+1],'max_tokens=128,max_gen_toks=128')
                self.assertIn('max_gen_toks=128',argv[argv.index('--model_args')+1])
                raise StopBeforeInference()
            with patch.object(adapters,'runtime',return_value=Path(sys.executable)),patch.object(adapters,'pinned_dataset'),patch.object(adapters.c,'execute',side_effect=launch):
                with self.assertRaises(StopBeforeInference):adapters.lm_eval(spec,config['model'],root/'evidence')

    def test_bfcl_result_binds_definition_and_actual_raw_evidence(self):
        import importlib.util, io
        from modelbench import common as c
        module_spec=importlib.util.spec_from_file_location('bfcl_adapter',ROOT/'scripts/bfcl-adapter.py')
        adapter=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(adapter)
        model={'id':'kolibri-1','base_url':'http://127.0.0.1:8000/v1'}
        request=dict(schema_version=1,request_sha256='r',adapter_version='v',data_manifest_sha256='d',definition_sha256='exact-definition',benchmark='bfcl',model=model,seed=1)
        case={'id':'synthetic','question':[[{'role':'user','content':'synthetic'}]],'function':[]}
        definition={'qualification_status':'QUALIFIED','max_output_tokens':32,'request_timeout_seconds':10,'artifacts':[]}
        class Reply(io.BytesIO): status=200
        class Opener:
            def open(self,*args,**kwargs):return Reply(json.dumps({'model':'kolibri-1','choices':[{'message':{'tool_calls':[]}}]}).encode())
        with tempfile.TemporaryDirectory() as tmp,patch.object(adapter,'load',return_value=[(case,[])]),patch.object(adapter,'score',return_value={'valid':False}),patch.object(adapter.urllib.request,'build_opener',return_value=Opener()):
            folder=Path(tmp);result=adapter.run(definition,request,folder)
            self.assertEqual(result['definition_sha256'],'exact-definition')
            self.assertEqual(result['metrics']['correct']['value'],0)
            self.assertEqual({item['path'] for item in result['evidence']},{'cases.json','synthetic-request.json','synthetic-response.json'})
            for item in result['evidence']:self.assertEqual(item['sha256'],c.digest(folder/item['path']))

    def test_retained_quality_requires_complete_matching_and_untampered_run(self):
        from modelbench import common as c,resume,kolibri
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=c.private_directory(root/'old');evidence=c.private_directory(run/'phase');folder=c.private_directory(root/'new')
            spec={'limit':1};model={'id':'kolibri-1'};config={'model':model,'benchmarks':{'lm_eval':spec}}
            c.save(run/'configuration.json',config);c.save(evidence/'raw.json',{'actual':'result'})
            phase={'id':'lm_eval','status':'PASS','evidence_directory':'phase','result':{'status':'PASS','raw_result':'raw.json','raw_sha256':c.digest(evidence/'raw.json')}}
            resume.seal(run,phase,'fixed')
            state={'identity':{'configuration_sha256':c.fingerprint(config)},'live_identity':{'service':{'PID':'fixed'}},'fingerprint':'fixed','phases':[phase]}
            c.save(run/'state.json',state);manifest=root/'retained.json';c.save(manifest,{'schema_version':1,'source_state':{'path':str(run/'state.json'),'sha256':c.digest(run/'state.json')}})
            selected=dict(spec,retained={'path':str(manifest),'sha256':c.digest(manifest)})
            with patch.object(kolibri,'service_identity',return_value={'PID':'fixed'}):
                result=adapters.retained_lm_eval(selected,model,folder);self.assertEqual(result['repeated_model_requests'],0)
                self.assertEqual((folder/result['raw_result']).read_bytes(),(evidence/'raw.json').read_bytes())
                with self.assertRaisesRegex(c.Blocked,'inputs differ'):adapters.retained_lm_eval(dict(selected,limit=2),model,folder)
                (evidence/'raw.json').write_text('tampered')
                with self.assertRaisesRegex(c.Blocked,'evidence changed'):adapters.retained_lm_eval(selected,model,folder)

    def test_no_warmup_uses_unset_trigger_not_rejected_zero(self):
        config = json.loads((ROOT / 'config/benchmark.example.json').read_text())
        spec = config['benchmarks']['aiperf']
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); tokenizer = folder / 'tokenizer'; tokenizer.mkdir()
            spec['tokenizer'] = str(tokenizer)
            def launch(argv, *args, **kwargs):
                if '-c' in argv:
                    self.assertEqual(kwargs['env']['HF_HUB_OFFLINE'], '1')
                    return {'exit_code':0}
                self.assertNotIn('--warmup-request-count', argv)
                self.assertNotIn('--num-warmup-requests', argv)
                self.assertNotIn('--warmup-duration', argv)
                self.assertIn('--streaming', argv)
                self.assertEqual(argv[argv.index('--tokenizer-revision')+1], config['model']['revision'])
                self.assertEqual(argv[argv.index('--tokenizer')+1], 'Aleph-Alpha/Kolibri-1')
                self.assertEqual(argv[argv.index('--endpoint') + 1], '/v1/chat/completions')
                raise StopBeforeInference()
            with patch.object(adapters, 'runtime', return_value=Path(sys.executable)), \
                 patch.object(adapters, 'pinned_dataset'), patch.object(adapters, 'aiperf_tokenizer', return_value=folder/'hf-home'), patch.object(adapters.c, 'execute', side_effect=launch):
                with self.assertRaises(StopBeforeInference):
                    adapters.aiperf(spec, config['model'], folder / 'evidence')


if __name__ == '__main__':
    unittest.main()
