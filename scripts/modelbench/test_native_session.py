"""Real assignment preparation/reuse; synthetic runtime/data, no model or service."""
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import assignment
import native_session as session
import inference_transport as transport
import worker as w


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.runtime=self.base/'runtime';self.runtime.mkdir(mode=0o700)
        self.path=self.base/'profile.json'
        files=assignment.payload({n:(ROOT/n).read_bytes() for n in (*assignment.COPIED,'docs/RUNBOOK.md')})
        archive=self.base/'assignment.tar';archive.write_bytes(assignment.archive_bytes(files))
        provenance=self.base/'assignment.json';w.write(provenance,{'identity':{'source_sha':'a'*40,'archive_sha256':w.digest(archive),'files':{n:w.sha(raw) for n,raw in files.items()}}})
        fs=self.base/'rootfs';(fs/'usr/bin').mkdir(parents=True);(fs/'usr/bin/python3').write_text('synthetic runtime')
        ext=self.base/'extension';(ext/'bin').mkdir(parents=True);(ext/'dist').mkdir()
        w.write(ext/'package.json',{'publisher':'kilocode','name':'kilo-code','version':'7.8.17'})
        (ext/'bin/kilo').write_text('synthetic binary');(ext/'dist/extension.js').write_text('synthetic extension')
        bundle=self.base/'train.jsonl';bundle.write_text(''.join(json.dumps({'case_id':str(i),'text':'Alice\nBob','coordinate_basis':'annotated_text_codepoints','labels':[]})+'\n' for i in range(12)))
        rights=self.base/'rights.json';budget=json.loads(files['config/budget.json'])
        w.write(rights,{'approved':True,'usage':'internal-train-only','reviewer':'fixture','legal_basis':'fixture only','source_revision':budget['hpi_train']['pinned_ref']})
        for n in ['brave','node','mcp-schema','lock','qualifier']:(self.base/n).write_text('synthetic '+n)
        browser=self.base/'browser.json';assets={}
        for n in ['brave_resources','mcp_modules']:
            d=self.base/n;d.mkdir();(d/'fixture').write_text(n);assets[n]={'path':str(d),'tree_sha256':session.native_browser.asset_tree(d)}
        w.write(browser,dict(assets,root='replaced',rootfs={'path':str(fs),'tree_sha256':w.tree(fs)},snapshots={'path':'unused by preparation','sha256':'0'*64}))
        tools=[{'name':name,'parameters':{'type':'object','properties':{}}} for name in sorted(session.BROWSER|{'bash','read','write','edit'})]
        schema=self.base/'wire.json';w.write(schema,{'tools':tools,'pins':{t['name']:transport.sha(transport.encoded(transport.schema(t['parameters']))) for t in tools}})
        self.value={'schema_version':1,'runtime_root':str(self.runtime),'run_id':'synthetic-seed-1','seed':1,'source_sha':'a'*40,
            'assignment':session.artifact(archive),'assignment_receipt':session.artifact(provenance),'train_bundle':session.artifact(bundle),
            'rights_record':session.artifact(rights),'approve_worker_disclosure':True,'rootfs':{'path':str(fs),'tree_sha256':w.tree(fs)},
            'extension':{'path':str(ext),'tree_sha256':w.tree(ext)},'python':session.artifact(Path(sys.executable).resolve()),
            'browser_profile':session.artifact(browser),'wire_schema':session.artifact(schema),
            'model':{'id':'kolibri-1','revision':'fixture','context_tokens':262144,'local_inference_only':True,'tokenizer_sha256':'1'*64,'backend_identity_sha256':'2'*64},
            'artifacts':{n:session.artifact(p) for n,p in {'kilo':ext/'bin/kilo','brave':self.base/'brave','node':self.base/'node','mcp_schema':self.base/'mcp-schema','dependency_lock':self.base/'lock'}.items()},
            'qualification':session.artifact(self.base/'qualifier'),'limits':{'address_space_mib':4096,'file_size_mib':64,'open_files':256,'processes':256}}
        w.write(self.path,self.value);self.dest=self.runtime/'build/synthetic-seed-1'

    def test_prepare_complete_pins_before_channel_start_and_repeat_without_rewrites(self):
        original=w.tree(self.value['extension']['path'])
        with patch.object(session.transport,'model_runtime_identity',side_effect=AssertionError('No live model lookup')),patch.object(w,'peer',side_effect=AssertionError('No sockets before preparation')):
            first=session.prepared(self.path)
            before={name:((self.dest/name).read_bytes(),(self.dest/name).stat().st_mtime_ns) for name in first['sealed']}
            again=session.prepared(self.path)
        self.assertTrue(again['reused']);self.assertEqual(first['status'],'PREPARED_NOT_READY')
        self.assertEqual(before,{name:((self.dest/name).read_bytes(),(self.dest/name).stat().st_mtime_ns) for name in first['sealed']})
        self.assertEqual(w.tree(self.value['extension']['path']),original)
        cfg=w.read(self.dest/'toolchain.json');policy=w.read(self.dest/'policy.json');record=w.read(self.dest/'synthetic-seed-1/run.json')
        self.assertEqual(cfg['agent']['transport'],'native-visible');self.assertNotIn('argv',cfg['agent'])
        self.assertEqual(record['budget'],w.read(ROOT/'config/budget.json'));self.assertIsNone(record['execution_wall_seconds'])
        self.assertEqual(policy['qualification_turns'],3);self.assertEqual(policy['qualification_output_tokens'],2048)
        self.assertEqual(policy['execution']['record']['sha256'],w.digest(self.dest/'synthetic-seed-1/run.json'))
        self.assertEqual(policy['execution']['toolchain']['sha256'],w.digest(self.dest/'toolchain.json'))
        self.assertEqual(cfg['channels']['inference']['peer_cmdline_sha256'],w.sha(b'\0'.join(a.encode() for a in session.argv(self.dest,self.value,'inference'))+b'\0'))
        self.assertTrue((self.dest/'native_inspection.py').exists())
        self.assertTrue((self.dest/'synthetic-seed-1/workspace/docs/COORDINATOR.md').exists())

    def test_changed_input_refuses_before_creation(self):
        Path(self.value['artifacts']['brave']['path']).write_text('drift')
        with self.assertRaisesRegex(w.Blocked,'pin changed'):session.prepared(self.path)
        self.assertFalse(self.dest.exists())

    def test_changed_output_is_preserved_and_refused(self):
        session.prepared(self.path);p=self.dest/'policy.json';p.write_text('drift')
        with self.assertRaisesRegex(w.Blocked,'source changed'):session.prepared(self.path)
        self.assertEqual(p.read_text(),'drift')

    def test_incomplete_run_never_replayed_or_overwritten(self):
        self.dest.mkdir(parents=True);p=self.dest/'unknown';p.write_text('retained')
        with self.assertRaises((OSError,w.Blocked)):session.prepared(self.path)
        self.assertEqual(p.read_text(),'retained')

    def test_bad_seed_model_and_disclosure_refused(self):
        for key,value in [('seed',41),('approve_worker_disclosure',False),('model',dict(self.value['model'],context_tokens=131072))]:
            with self.subTest(key=key):
                self.path.write_bytes(w.encoded(dict(self.value,**{key:value})))
                with self.assertRaises(w.Blocked):session.prepared(self.path)
                self.assertFalse(self.dest.exists())

    def test_wire_schema_mismatch_refused(self):
        p=Path(self.value['wire_schema']['path']);schema=w.read(p);schema['pins']['bash']='f'*64;p.write_bytes(w.encoded(schema))
        self.value['wire_schema']=session.artifact(p);self.path.write_bytes(w.encoded(self.value))
        with self.assertRaisesRegex(w.Blocked,'schemas required'):session.prepared(self.path)
        self.assertFalse(self.dest.exists())

    def test_active_session_reuses_without_submission_and_stopped_session_refuses(self):
        session.prepared(self.path)
        actual={'ActiveState':'active','InvocationID':'same','MainPID':'123'}
        w.write(self.dest/'session-runtime.json',{'synthetic':True})
        w.write(self.dest/'session-started.json',{'unit_state':actual,'prepared_sha256':w.digest(self.dest/'session-prepared.json'),'runtime_sha256':w.digest(self.dest/'session-runtime.json')})
        with patch.object(session,'state',return_value=actual),patch.object(session.subprocess,'run') as command:
            self.assertTrue(session.start(self.path)['reused']);command.assert_not_called()
        with patch.object(session,'state',return_value=dict(actual,ActiveState='failed')),patch.object(session.subprocess,'run') as command:
            with self.assertRaisesRegex(w.Blocked,'no automatic restart'):session.start(self.path)
            command.assert_not_called()

    def test_uncertain_intent_never_submits_another_service(self):
        session.prepared(self.path);w.write(self.dest/'session-intent.json',{'synthetic':True})
        with patch.object(session,'state',return_value={'LoadState':'not-found'}),patch.object(session.subprocess,'run') as command:
            with self.assertRaisesRegex(w.Blocked,'no automatic replay'):session.start(self.path)
            command.assert_not_called()

    def test_stop_refuses_replaced_unit(self):
        session.prepared(self.path)
        w.write(self.dest/'session-started.json',{'unit_state':{'InvocationID':'original'}})
        w.write(self.dest/'session-intent.json',{'profile_sha256':w.digest(self.path),'unit':session.unit(self.value)})
        with patch.object(session,'state',return_value={'InvocationID':'other','ExecStart':str(self.dest/'native_session.py')}),patch.object(session.subprocess,'run') as command:
            with self.assertRaisesRegex(w.Blocked,'refusing stop'):session.stop_session(self.path)
            command.assert_not_called()

    def test_stop_owned_session_after_installed_artifact_drift(self):
        session.prepared(self.path)
        actual={'InvocationID':'same','ActiveState':'active','ExecStart':str(self.dest/'native_session.py')}
        w.write(self.dest/'session-started.json',{'unit_state':actual})
        w.write(self.dest/'session-intent.json',{'profile_sha256':w.digest(self.path),'unit':session.unit(self.value)})
        w.write(self.dest/'session-finished.json',{'status':'STOPPED','child_exit_codes':[-15,-15],'backend_stop_verified':True})
        Path(self.value['artifacts']['brave']['path']).write_text('native package was updated')
        with patch.object(session,'state',side_effect=[actual,dict(actual,ActiveState='inactive')]),patch.object(session.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as command:
            result=session.stop_session(self.path)
        self.assertEqual(result['status'],'STOPPED_PRESERVED');command.assert_called_once()
        self.assertEqual(command.call_args.args[0],['systemctl','--user','stop',session.unit(self.value)])

    def test_backend_stop_checks_invocation_before_owned_force_kill(self):
        session.prepared(self.path);settings=w.read(self.dest/'gui.json')
        actual={'ActiveState':'active','InvocationID':'same','ExecStart':str(self.dest/'native_gui.py')+' --configuration '+str(self.dest/'gui.json')}
        w.write(self.dest/'backend-intent.json',{'unit':session.native_gui.unit(settings),'configuration_sha256':w.digest(self.dest/'gui.json')})
        w.write(self.dest/'backend-receipt.json',{'unit_state':actual})
        with patch.object(session.native_gui,'state',side_effect=[actual,actual,dict(actual,ActiveState='failed')]),patch.object(session.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as command:
            self.assertTrue(session.stop_backend(self.dest,settings))
        self.assertEqual(command.call_count,3)
        self.assertEqual(command.call_args_list[1].args[0],['systemctl','--user','kill','--kill-whom=all','--signal=KILL',session.native_gui.unit(settings)])
        with patch.object(session.native_gui,'state',side_effect=[actual,dict(actual,InvocationID='replaced')]),patch.object(session.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as command:
            with self.assertRaisesRegex(w.Blocked,'replaced during stop'):session.stop_backend(self.dest,settings)
        self.assertEqual(command.call_count,1)

    def test_busy_missing_and_oversized_metrics_fail_before_generation(self):
        from unittest.mock import Mock
        for raw,passed in [(b'vllm:num_requests_running{model_name="kolibri-1"} 0\nvllm:num_requests_waiting{model_name="kolibri-1"} 0\n',True),(b'vllm:num_requests_running 1\nvllm:num_requests_waiting 0\n',False),(b'not metrics',False),(b'x'*(2*1024*1024+1),False)]:
            reply=Mock(status=200);reply.read.return_value=raw;connection=Mock();connection.getresponse.return_value=reply
            with patch.object(session.http.client,'HTTPConnection',return_value=connection) as connect:
                if passed:session.model_idle()
                else:
                    with self.assertRaises(w.Blocked):session.model_idle()
            connect.assert_called_once_with('127.0.0.1',8000,timeout=5)
            connection.request.assert_called_once_with('GET','/metrics');connection.close.assert_called_once()

    def test_partial_start_reaps_real_owned_children_and_releases_model_lock(self):
        identity={'synthetic':'no real model access'}
        self.value['model']['backend_identity_sha256']=transport.sha(transport.encoded(identity))
        self.path.write_bytes(w.encoded(self.value));session.prepared(self.path)
        w.write(self.dest/'session-intent.json',{'profile_sha256':w.digest(self.path),'prepared_sha256':w.digest(self.dest/'session-prepared.json')})
        processes=[];popen=subprocess.Popen;killpg=os.killpg;cleanup_checks=[]
        def spawn(*a,**kw):
            child=popen(*a,**kw);processes.append(child);return child
        def guarded_killpg(pid,sig):
            with (self.runtime/'tools/benchmark/benchmark.lock').open('a') as contender:
                with self.assertRaises(BlockingIOError):session.fcntl.flock(contender,session.fcntl.LOCK_EX|session.fcntl.LOCK_NB)
            cleanup_checks.append(pid);return killpg(pid,sig)
        def argv(root,value,which):
            path=root/which/('inference.sock' if which=='inference' else 'browser.sock')
            code='import socket,time;s=socket.socket(socket.AF_UNIX);s.bind('+repr(str(path))+');s.listen();time.sleep(60)'
            return [sys.executable,'-B','-c',code]
        with patch.object(session.native_controls,'run',return_value={'fixture':True}),patch.object(session,'model_idle',return_value={'fixture':True}),patch.object(session,'stop_backend',return_value=True),patch.object(session.os,'killpg',side_effect=guarded_killpg),patch.object(session.transport,'model_runtime_identity',return_value=identity),patch.object(session,'argv',side_effect=argv),patch.object(session.subprocess,'Popen',side_effect=spawn),patch.object(w,'peer',return_value={'fixture':True}),patch.object(session.native_gui,'ensure',side_effect=w.Blocked('synthetic backend failure')):
            with self.assertRaisesRegex(w.Blocked,'synthetic backend failure'):session.serve(self.path)
        self.assertEqual(len(processes),2);self.assertTrue(all(p.poll() is not None for p in processes));self.assertEqual(len(cleanup_checks),2)
        result=w.read(self.dest/'session-finished.json');self.assertEqual(result['status'],'FAILED')
        self.assertFalse((self.dest/'session-runtime.json').exists())
        with (self.runtime/'tools/benchmark/benchmark.lock').open('a') as lock:
            session.fcntl.flock(lock,session.fcntl.LOCK_EX|session.fcntl.LOCK_NB)


if __name__=='__main__':unittest.main()
