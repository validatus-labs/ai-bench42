"""Native visible candidate lifecycle invariants; no live model or source repair."""
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import json,time,sqlite3
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_candidate as candidate
import worker as w

class CandidateTests(unittest.TestCase):
    def ledger(self):return {'requests':4,'generated_tokens':1400,'tool_calls':3,'reserved_tokens':0,'uncertain':False}
    def messages(self):return [{'info':{'role':'assistant','sessionID':'ses_fixture','providerID':'001','modelID':'kolibri-1','agent':'modelbench','time':{'completed':1}},'parts':[]}]
    def test_busy_uncertain_unsubmitted_and_wrong_model_never_finish(self):
        ledger=self.ledger();messages=self.messages()
        self.assertEqual(candidate.terminal_state({'ses_fixture':{'type':'busy'}},messages,dict(ledger,uncertain=True),'ses_fixture'),'RUNNING')
        for key,val in [('uncertain',True),('reserved_tokens',1)]:self.assertEqual(candidate.terminal_state({},messages,dict(ledger,**{key:val}),'ses_fixture'),'UNCERTAIN_NO_REPLAY')
        self.assertEqual(candidate.terminal_state({},[],ledger,'ses_fixture'),'SUBMISSION_UNCERTAIN_NO_REPLAY')
        for field in ['providerID','modelID','sessionID','agent']:
            bad=copy.deepcopy(messages);bad[0]['info'][field]='wrong'
            with self.subTest(field=field),self.assertRaises(ValueError):candidate.terminal_state({},bad,ledger,'ses_fixture')
        self.assertEqual(candidate.terminal_state({},messages,ledger,'ses_fixture'),'QUIESCENT_NOT_ASSESSED')
        messages[0]['parts']=[{'type':'tool','state':{'status':'running'}}]
        self.assertEqual(candidate.terminal_state({},messages,ledger,'ses_fixture'),'UNCERTAIN_NO_REPLAY')
    def test_unknown_sdk_tools_are_denied_and_missing_approved_tool_fails(self):
        self.assertEqual(candidate.permissions(['read','secret_tool'],{'read'}),{'read':True,'secret_tool':False})
        with self.assertRaises(ValueError):candidate.permissions(['read'],{'read','bash'})
    def test_repeat_start_never_contacts_model_even_with_partial_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'run';run.mkdir();record={'fingerprint':'fixture'}
            w.write(run/'candidate-start.json',{'fingerprint':'fixture','controller_sha256':candidate.digest(Path(candidate.__file__))})
            bound=(w,None,None,None,None,{'run_id':'fixture'},root,run,record,{})
            with patch.object(candidate,'bind',return_value=bound) as bind:
                result=candidate.start(root/'gui.json')
            self.assertEqual(result['status'],'EXISTING_CANDIDATE_NOT_REPLAYED');self.assertFalse(result['submission_present']);self.assertEqual(bind.call_count,1)
    def test_start_writes_intent_before_any_prompt_and_never_replays_failed_create(self):
        for fail_create in [True,False]:
            with self.subTest(fail_create=fail_create),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);(root/'gui.json').write_text('{}');run=root/'run';docs=run/'workspace/docs';docs.mkdir(parents=True);(root/'inference').mkdir()
                (docs/'OFFLINE_AGENT_PROMPT.md').write_text('UNCHANGED FROZEN ENGLISH TASK');(docs/'COORDINATOR.md').write_text('EXISTING SCOPE CLARIFICATION')
                ledger=dict(self.ledger(),requests=3,generated_tokens=1330);w.write(root/'inference/ledger.json',ledger);w.write(root/'policy.json',{'tools':{'read':'pin','playwright_browser_snapshot':'pin'}})
                receipt=root/'ready.json';w.write(receipt,{'created_unix':time.time()})
                gate={'receipt':{'path':str(receipt),'sha256':w.digest(receipt)}};record={'fingerprint':'fixture','identity':{'run_id':'fixture','source_sha':'base','package_sha256':'archive','train_sha256':'train','seed':1,'toolchain_sha256':'toolchain'},'budget':{'max_agent_turns':100},'execution_wall_seconds':None}
                calls=[]
                def api(root,value,method,path,data=None):
                    calls.append(path)
                    if path=='/session/status':return {}
                    if path=='/experimental/tool/ids':return ['read','unapproved']
                    self.assertTrue((run/'candidate-start.json').exists())
                    if path=='/session':
                        if fail_create:raise OSError('synthetic uncertain create')
                        return {'id':'ses_fixture'}
                    self.assertTrue((run/'candidate-submission.json').exists());self.assertIn('UNCHANGED FROZEN ENGLISH TASK',data['parts'][0]['text']);self.assertFalse(data['tools']['unapproved']);return None
                visible=SimpleNamespace(api=api,attachment=lambda root:[{'fixture':'actual attach'}]);transport=SimpleNamespace(coding_gate=lambda *a:(gate,'gatehash'))
                bound=(w,None,visible,None,transport,{'run_id':'fixture'},root,run,record,{'model':{'id':'kolibri-1'}})
                with patch.object(candidate,'bind',return_value=bound):
                    if fail_create:
                        with self.assertRaises(OSError):candidate.start(root/'gui.json')
                    else:self.assertEqual(candidate.start(root/'gui.json')['status'],'CANDIDATE_RUNNING')
                    before=list(calls);self.assertEqual(candidate.start(root/'gui.json')['status'],'EXISTING_CANDIDATE_NOT_REPLAYED');self.assertEqual(calls,before)

    def test_finish_requires_verified_teardown_before_freeze_and_resumes_after_stop(self):
        for failure in [False,True]:
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);run=root/'run';run.mkdir();(root/'inference').mkdir();ledger=self.ledger();w.write(root/'inference/ledger.json',ledger)
                profile={'fixture':'original launch'};w.write(root/'session-prepared.json',{'identity':{'profile':profile}});w.write(run/'candidate-start.json',{'started':time.time()});w.write(run/'candidate-submission.json',{'session_id':'ses_fixture'})
                observation=root/'observation.json';w.write(observation,{'fixture':'quiescent'});before={'status':'QUIESCENT_NOT_ASSESSED','observation':str(observation),'observation_sha256':w.digest(observation)}
                stopped=[]
                def stop(path):
                    if failure:raise RuntimeError('unverified teardown')
                    stopped.append(True)
                session=SimpleNamespace(control_inputs=lambda p:(profile,root),stop_session=stop)
                gui=SimpleNamespace(state=lambda v:{'ActiveState':'inactive' if stopped else 'active'})
                bound=(w,gui,None,session,None,{},root,run,{'fingerprint':'fixture'},{});frozen={'candidate_tree_sha256':'tree'}
                def freeze(*args):self.assertTrue(stopped);return frozen
                # No hidden scoring implied even when visible checks fail.
                with patch.object(candidate,'bind',return_value=bound),patch.object(candidate,'status',return_value=before),patch.object(candidate,'stopped',side_effect=lambda *a:stop(None)),patch.object(candidate,'capture_messages',return_value={'messages':[]}),patch.object(candidate,'recoverable_freeze',side_effect=freeze) as frozen_call,patch.object(w,'verify_candidate',return_value={'status':'FAILED'}):
                    if failure:
                        with self.assertRaises(RuntimeError):candidate.finish(root/'gui.json',root/'profile.json')
                        self.assertFalse(frozen_call.called);self.assertFalse((run/'candidate-result.json').exists())
                        # A retry after cleanup uses the preserved intent without a
                        # new API observation, prompt or model request.
                        failure=False;stopped.append(True)
                        with patch.object(candidate,'status',side_effect=AssertionError('no live API after stopped finish')):result=candidate.finish(root/'gui.json',root/'profile.json')
                    else:result=candidate.finish(root/'gui.json',root/'profile.json')
                    self.assertEqual(result['status'],'CANDIDATE_ASSESSED_NOT_HELDOUT_PASS');self.assertEqual(result['visible']['status'],'FAILED')

    def test_real_sealed_freeze_tar_before_receipt_crash_recovers_without_source_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);workspace=run/'workspace';(workspace/'melusense').mkdir(parents=True);(workspace/'tests').mkdir();(workspace/'build').mkdir()
            (workspace/'melusense/api.py').write_text('synthetic candidate only');(workspace/'AGENTS.md').write_text('frozen rules');(workspace/'build/hpi-train-visible.jsonl').write_text('{}')
            w.write(run/'candidate-start.json',{'fixture':True})
            record={'fingerprint':'fixture','frozen':{'AGENTS.md':w.digest(workspace/'AGENTS.md')},'identity':{'train_sha256':w.digest(workspace/'build/hpi-train-visible.jsonl'),'launcher_sha256':w.digest(Path(w.__file__)),'inner_sha256':w.digest(w.INNER)}}
            original=w.write
            def crash(path,value):
                if path.name=='frozen-candidate.json':raise InterruptedError('after sealed tar publication')
                return original(path,value)
            with patch.object(w,'write',side_effect=crash),self.assertRaises(InterruptedError):w.freeze_candidate(run,record)
            archive=run/'frozen-candidate.tar';before=(archive.read_bytes(),archive.stat().st_mtime_ns)
            result=candidate.recoverable_freeze(w,run,record)
            self.assertEqual(result,w.freeze_candidate(run,record));self.assertEqual(before,(archive.read_bytes(),archive.stat().st_mtime_ns))
            self.assertEqual(candidate.recoverable_freeze(w,run,record),result)
            (workspace/'melusense/api.py').write_text('changed after freeze')
            with self.assertRaises(w.Blocked):candidate.recoverable_freeze(w,run,record)

    def test_real_stop_then_unloaded_unit_uses_retained_verified_cleanup(self):
        import native_session as session
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);value={'run_id':'fixture'};profile=root/'profile.json'
            w.write(root/'session-started.json',{'unit_state':{'InvocationID':'original'}})
            w.write(root/'session-finished.json',{'backend_stop_verified':True,'child_exit_codes':[0,-15],'status':'STOPPED'})
            w.write(root/'toolchain.json',{'channels':{}})
            active={'ActiveState':'active','LoadState':'loaded','InvocationID':'original','ExecStart':str(root/'native_session.py')}
            inactive={'ActiveState':'inactive','LoadState':'loaded'};unloaded={'ActiveState':'inactive','LoadState':'not-found'}
            gui=SimpleNamespace(state=lambda v:inactive)
            with patch.object(session,'control_inputs',return_value=(value,root)),patch.object(session,'state',side_effect=[active,active,inactive]),patch.object(session.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as actual_stop:
                candidate.stopped(w,gui,session,root,value,profile)
                self.assertEqual(actual_stop.call_count,1)
            with patch.object(session,'state',return_value=unloaded),patch.object(session,'stop_session',side_effect=AssertionError('must reuse cleanup')):
                candidate.stopped(w,gui,session,root,value,profile)
                (root/'session-finished.json').write_bytes(w.encoded({'backend_stop_verified':False,'child_exit_codes':[0,0]}))
                with self.assertRaises(w.Blocked):candidate.stopped(w,gui,session,root,value,profile)

    def test_paginated_transcript_and_missing_invalid_worker_report_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);calls=[];db=run/'workspace/build/.kilo-ui/data/kilo/kilo.db';db.parent.mkdir(parents=True)
            connection=sqlite3.connect(db);connection.execute('create table message(id text,session_id text,time_created integer)');connection.executemany('insert into message values(?,?,?)',[('msg_2','ses_fixture',2),('msg_1','ses_fixture',1),('secret','other-session',3)]);connection.commit();connection.close()
            def api(root,value,method,path):
                calls.append(path);identifier=path.split('/message/')[1].split('?')[0];return {'info':{'id':identifier,'sessionID':'ses_fixture'}}
            result=candidate.capture_messages(w,SimpleNamespace(api=api),run,{},run,'ses_fixture')
            self.assertEqual(len(result['messages']),2);self.assertTrue(all('/message/msg' in p for p in calls));self.assertFalse(any('secret' in p for p in calls))
            self.assertEqual(candidate.capture_worker_report(w,run)['status'],'MISSING_C07_NOT_ESTABLISHED')
            build=run/'workspace/build';build.mkdir(parents=True,exist_ok=True);report=build/'worker-report.json';report.write_text('invalid')
            self.assertEqual(candidate.capture_worker_report(w,run)['status'],'INVALID_JSON_C07_NOT_ESTABLISHED')
            report.write_text('{"run_id":"fixture"}');captured=candidate.capture_worker_report(w,run)
            self.assertEqual(captured['status'],'PRESENT_UNREVIEWED');self.assertFalse(captured['independent_C07_acceptance']);self.assertEqual(w.digest(report),captured['sha256'])

    def test_wrong_mode_refuses_before_import_or_candidate_submission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'gui.json';w.write(p,{'root':str(root),'mode':'INSPECTION_NO_INFERENCE'})
            with self.assertRaises(ValueError):candidate.bind(p)
            self.assertFalse((root/'candidate-start.json').exists())

if __name__=='__main__':unittest.main()
