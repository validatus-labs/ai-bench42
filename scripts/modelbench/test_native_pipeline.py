"""Native pipeline resume never falls back to legacy model/CLI generation."""
import json
from pathlib import Path
import sys
import tempfile
import copy
import subprocess
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modelbench import native_pipeline as native,common as c,resume,pipeline
import contextlib
from types import SimpleNamespace

class NativePipelineTests(unittest.TestCase):
    def test_pending_candidate_remains_same_explicit_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);reference={'fixture':'same native session'}
            with patch.object(native,'validate_reference',return_value=reference),patch.object(native,'invoke',side_effect=[{'status':'EXISTING_CANDIDATE_NOT_REPLAYED'},{'status':'RUNNING','session_id':'same'}]) as calls:
                result=native.coding({},folder,1)
            self.assertEqual(result['status'],'AWAITING_NATIVE_CANDIDATE');self.assertEqual([call.args[1] for call in calls.call_args_list],['start','status'])
            self.assertEqual(c.read(folder/'native-reference.json'),reference)
    def test_real_subprocess_uses_existing_controller_and_parses_bounded_json_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);script=root/'controller.py';script.write_text('import json;print(json.dumps({"status":"EXISTING_CANDIDATE_NOT_REPLAYED"}))');config=root/'gui.json';c.save(config,{'fixture':True})
            reference={'controller':{'path':str(script),'sha256':c.digest(script)},'configuration':{'path':str(config),'sha256':c.digest(config)}}
            result=native.invoke(reference,'start',root/'action');self.assertEqual(result['status'],'EXISTING_CANDIDATE_NOT_REPLAYED')
    def fixture(self,root):
        root.mkdir(parents=True,exist_ok=True)
        def pin(path):return {'path':str(path),'sha256':c.digest(path)}
        model={'id':'kolibri-1','revision':'fixed-revision','context_tokens':262144};profile={'run_id':'native-fixture','seed':1,'approve_worker_disclosure':True,'runtime_root':str(root/'runtime')}
        actual=root/'runtime/build/native-fixture';actual.mkdir(parents=True,mode=0o700)
        c.save(actual/'session-prepared.json',{'identity':{'profile':profile}})
        record={'fingerprint':'fixture-fingerprint','identity':{'run_id':'native-fixture','seed':1,'source_sha':'base','package_sha256':'package','train_sha256':'train','rights_record_sha256':'rights'},'execution_wall_seconds':None}
        toolchain={'agent':{'transport':'native-visible'},'model':model};gui={'mode':'GATED_NATIVE_TRIAL','run_id':'native-fixture','root':str(actual),'run_directory':'native-fixture'}
        for name,value in [('profile',profile),('record',record),('toolchain',toolchain)]:c.save(root/(name+'.json'),value)
        gui.update(record=pin(root/'record.json'),toolchain=pin(root/'toolchain.json'));c.save(root/'gui.json',gui)
        (root/'controller.py').write_text('synthetic controller source')
        cfg={'model':model,'coding':{'source_sha':'base','package':{'sha256':'package'},'train_bundle':{'sha256':'train'},'rights_record':{'sha256':'rights'},'approve_worker_disclosure':True,'elapsed_only':True,
             'native':{'controller':pin(root/'controller.py'),'sessions':{'1':{'run_id':'native-fixture','configuration':pin(root/'gui.json'),'profile':pin(root/'profile.json')}}}}}
        return cfg

    def test_real_reference_fixture_and_provenance_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=self.fixture(root);self.assertEqual(native.validate_reference(cfg,1)['run_id'],'native-fixture')
            for field in ['source_sha','package','train_bundle','rights_record','approve_worker_disclosure','elapsed_only']:
                changed=copy.deepcopy(cfg)
                if field in ['package','train_bundle','rights_record']:changed['coding'][field]['sha256']='changed'
                elif field in ['elapsed_only','approve_worker_disclosure']:changed['coding'][field]=False
                else:changed['coding'][field]='changed'
                with self.subTest(field=field),self.assertRaises(c.Blocked):native.validate_reference(changed,1)
            for field in ['id','revision','context_tokens']:
                changed=copy.deepcopy(cfg);changed['model'][field]='other'
                with self.subTest(model=field),self.assertRaises(c.Blocked):native.validate_reference(changed,1)
            with self.assertRaises(c.Blocked):native.validate_reference(cfg,2)
            (root/'record.json').write_text('{}')
            with self.assertRaises(c.Blocked):native.validate_reference(cfg,1)

    def test_native_resume_refuses_a_still_live_controller_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=self.fixture(root);reference=native.validate_reference(cfg,1);folder=root/'phase';folder.mkdir();c.save(folder/'native-reference.json',reference)
            child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)'])
            try:
                command={'status':'RUNNING','pid':child.pid,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'process_start_ticks':Path('/proc',str(child.pid),'stat').read_text().rsplit(')',1)[1].split()[19]}
                c.save(folder/'command.json',command)
                with self.assertRaisesRegex(c.Blocked,'still alive'):resume.may_retry(root,{'id':'coding-1','status':'INTERRUPTED','effects_started':True,'evidence_directory':'phase'})
            finally:child.terminate();child.wait(timeout=3)

    def test_capture_only_adapter_is_separately_bound_and_never_used_to_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=self.fixture(root);spec=cfg['coding']['native']['sessions']['1'];controller=root/'capture.py';controller.write_text('print("unused fixture")')
            profile=root/'capture.json';c.save(profile,{'original':cfg['coding']['native']['controller'],'configuration':spec['configuration'],'session_profile':spec['profile'],'run_id':spec['run_id'],'fingerprint':'fixture-fingerprint'})
            spec['resume_adapter']={'controller':{'path':str(controller),'sha256':c.digest(controller)},'profile':{'path':str(profile),'sha256':c.digest(profile)}}
            reference=native.validate_reference(cfg,1);calls=[]
            def execute(argv,folder,seconds):
                calls.append(argv);c.private_directory(folder);(folder/'output.log').write_text('{"status":"fixture"}');return {'exit_code':0}
            with patch.object(c,'execute',side_effect=execute):
                native.invoke(reference,'start',root/'start');native.invoke(reference,'status',root/'status');native.invoke(reference,'finish',root/'finish')
            self.assertIn(str(root/'controller.py'),calls[0]);self.assertNotIn(str(controller),calls[0]);self.assertTrue(all(str(controller) in argv and '--profile' in argv and '--configuration' not in argv for argv in calls[1:]))
            bad=c.read(profile);bad['fingerprint']='other';c.save(profile,bad);spec['resume_adapter']['profile']['sha256']=c.digest(profile)
            with self.assertRaises(c.Blocked):native.validate_reference(cfg,1)

    def test_visible_pass_never_substitutes_for_independent_complete_task_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);frozen={'candidate_tree_sha256':'tree','archive_sha256':'archive'};observed={'fingerprint':'fingerprint','visible':{'status':'PASS'},'worker_report':{'status':'PRESENT_UNREVIEWED','sha256':'report'}}
            self.assertEqual(native.development_review(run,frozen,observed)['status'],'DEVELOPMENT_REVIEW_REQUIRED')
            review={'schema_version':1,'independent_reviewer':'synthetic fixture only','fingerprint':'fingerprint','candidate_tree_sha256':'tree','archive_sha256':'archive','worker_report_sha256':'report','decision':'CHANGES_REQUIRED','findings':['required TRAIN evidence absent']}
            file=run/'independent-development-review.json';c.save(file,review);self.assertEqual(native.development_review(run,frozen,observed)['status'],'FAILED')
            review.update(decision='CANDIDATE_DEVELOPMENT_ACCEPTED',findings=[],worker_train_cases_verified=0,c01_c07_complete=True);c.save(file,review)
            with self.assertRaises(c.Blocked):native.development_review(run,frozen,observed)
            review['worker_train_cases_verified']=12;c.save(file,review);self.assertEqual(native.development_review(run,frozen,observed)['status'],'PASS')
            review['fingerprint']='other candidate';c.save(file,review)
            with self.assertRaises(c.Blocked):native.development_review(run,frozen,observed)

    def test_corrected_raw_logs_remain_pinned_after_phase_sealing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'worker';run.mkdir();output=run/'corrected';output.mkdir();frozen={'candidate_tree_sha256':'tree','archive_sha256':'archive'};observed={'fingerprint':'fingerprint','visible':{'status':'FAILED'},'worker_report':{'status':'PRESENT_UNREVIEWED','sha256':'report'}}
            c.save(output/'namespace.json',{});c.save(output/'result.json',{'status':'PASS'});(output/'tests.log').write_text('synthetic results')
            correction={'identity':{'fingerprint':'fingerprint','candidate_tree_sha256':'tree','archive_sha256':'archive','adapter_sha256':c.digest(Path(__file__).resolve().parents[2]/'tools/native_assessment.py')},'assessment':{'status':'PASS'},'status':'PASS','exit_code':0,'evidence':{name:{'path':name,'sha256':c.digest(output/name)} for name in ['namespace.json','result.json','tests.log']}}
            c.save(output/'receipt.json',correction)
            review={'schema_version':1,'independent_reviewer':'synthetic fixture only','fingerprint':'fingerprint','candidate_tree_sha256':'tree','archive_sha256':'archive','worker_report_sha256':'report','decision':'CHANGES_REQUIRED','findings':['incomplete task'],'corrected_assessment':{'path':str(output/'receipt.json'),'sha256':c.digest(output/'receipt.json')}}
            c.save(run/'independent-development-review.json',review);result=native.development_review(run,frozen,observed)
            self.assertEqual(len(result['external_evidence']),5)
            phase={'id':'coding-1','name':'fixture','kind':'coding','status':'PENDING'};folder=resume.begin(root,phase);phase.update(status='FAILED',result=result);resume.seal(root,phase,'fixture-fingerprint');resume.check_receipt(root,phase,'fixture-fingerprint')
            (output/'tests.log').write_text('drift outside phase folder')
            with self.assertRaises(c.Blocked):resume.check_receipt(root,phase,'fixture-fingerprint')

    def test_actual_native_workload_lock_blocks_benchmark_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);target={'runtime':str(root)};lock=c.private_directory(root/'tools/benchmark')/'benchmark.lock'
            config={'model':{'fixture':True},'benchmarks':{'aiperf':{'enabled':True}}};state={'live_identity':{'fixture':True},'phases':[{'kind':'installation','id':'verify','status':'PASS'}]}
            with c.locked(lock),patch.object(pipeline,'source_hashes',return_value={}),patch.object(pipeline,'current_backend',return_value={'fixture':True}),patch.object(pipeline.adapters,'aiperf',side_effect=AssertionError('must never execute')) as adapter:
                with self.assertRaisesRegex(c.Blocked,'exclusive benchmark lease'):pipeline.execute_phase(config,target,root,state,{'id':'aiperf'},{'controller_sources':{}},SimpleNamespace(_modelbench_acquired=True),'fixture')
                self.assertFalse(adapter.called)
            # Only an explicitly validated same-session native continuation
            # observes under its existing coordinator lease.
            with c.locked(lock),patch.object(native,'validate_reference',return_value={'run_id':'same'}) as validate:
                with native.workload_lease({'coding':{'native':{}}},target,'coding-1'):pass
                validate.assert_called_once()

    def test_adopted_registry_and_native_worker_use_the_same_actual_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.fixture(root/'worker');spec=config['coding']['native']['sessions']['1']
            profile=c.read(c.pin(spec['profile']));runtime=Path(profile['runtime_root'])
            # Deliberately different adoption/registry root reproduced live.
            target={'runtime':str(root/'adopted-registry')}
            lock=c.private_directory(runtime/'tools/benchmark')/'benchmark.lock'
            with c.locked(lock):
                with self.assertRaisesRegex(c.Blocked,'exclusive benchmark lease'):
                    with native.workload_lease(config,target,'aiperf'):self.fail('must not enter')
            with native.workload_lease(config,target,'aiperf'):pass
            self.assertFalse((root/'adopted-registry/tools/benchmark/benchmark.lock').exists())
            profile['runtime_root']=str(root/'wrong-runtime');c.save(Path(spec['profile']['path']),profile)
            spec['profile']['sha256']=c.digest(spec['profile']['path'])
            with self.assertRaisesRegex(c.Blocked,'runtime path differs'):
                with native.workload_lease(config,target,'aiperf'):self.fail('must not enter')
            self.assertFalse((root/'wrong-runtime').exists())
            profile['runtime_root']=str(runtime);profile['unprepared_change']=True
            c.save(Path(spec['profile']['path']),profile);spec['profile']['sha256']=c.digest(spec['profile']['path'])
            with self.assertRaisesRegex(c.Blocked,'actual prepared native worker'):
                with native.workload_lease(config,target,'aiperf'):self.fail('must not enter')

    def test_resuming_native_effect_requires_all_unchanged_pins_and_no_live_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'phase';folder.mkdir();spec={}
            for key in ['controller','configuration','profile','record']:
                file=root/(key+'.json');c.save(file,{'fixture':key});spec[key]={'path':str(file),'sha256':c.digest(file)}
            spec.update(schema_version=1,seed=1);c.save(folder/'native-reference.json',spec)
            phase={'id':'coding-1','status':'AWAITING_NATIVE_CANDIDATE','effects_started':True,'evidence_directory':'phase'}
            self.assertIsNone(resume.may_retry(root,phase))
            c.save(root/'controller.json',{'changed':True})
            with self.assertRaises(c.Blocked):resume.may_retry(root,phase)

if __name__=='__main__':unittest.main()
