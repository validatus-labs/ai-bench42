"""Correlate actual-model-shaped tool parts with raw MCP output; no inference."""
import copy
from pathlib import Path
import sys
import tempfile
import json
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_visible as visible
import worker as w


class VisibleTests(unittest.TestCase):
    def fixture(self):
        intent={'url':'data:text/html,%3Cp%3Emarker%3C%2Fp%3E','marker':'marker'}
        calls=[('browser_navigate',{'url':intent['url']},'Page marker'),('browser_snapshot',{},'paragraph: marker'),('browser_tabs',{'action':'close'},'No open tabs')]
        parts=[];traces=[]
        for i,(name,args,text) in enumerate(calls):
            parts.append({'type':'tool','callID':'call-'+str(i),'tool':'playwright_'+name,'state':{'status':'completed','input':args,'output':text}})
            traces.append({'request':{'method':'tools/call','params':{'name':name,'arguments':args}},'response':{'result':{'content':[{'type':'text','text':text}]}}})
        return [{'info':{'sessionID':'own-session','role':'assistant','modelID':'kolibri-1','providerID':'001','agent':'modelbench'},'parts':parts}],intent,traces

    def test_three_completed_calls_match_exact_actual_mcp_arguments_and_text(self):
        messages,intent,traces=self.fixture();self.assertEqual(len(visible.correlated(messages,intent,traces,'own-session')),3)

    def test_selects_model_connection_after_coordinator_closed_its_own_tab(self):
        messages,intent,traces=self.fixture();other=copy.deepcopy(traces);other[0]['request']['params']['arguments']['url']='data:text/html,coordinator'
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,rows in [('mcp-coordinator',other),('mcp-model',traces)]:
                folder=root/'browser'/name;folder.mkdir(parents=True,mode=0o700);p=folder/'trace.jsonl';p.write_text(''.join(json.dumps(row)+'\n' for row in rows));p.chmod(0o600)
            selected=visible.model_trace(root,intent)
            self.assertEqual(len(visible.correlated(messages,intent,selected,'own-session')),3)
            duplicate=root/'browser/mcp-duplicate';duplicate.mkdir();p=duplicate/'trace.jsonl';p.write_text(''.join(json.dumps(row)+'\n' for row in traces));p.chmod(0o600)
            with self.assertRaisesRegex(w.Blocked,'Exactly one MCP connection'):visible.model_trace(root,intent)

    def test_vscode_environment_alone_does_not_prove_extension_attachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);proc=root/'proc';child=proc/'10';child.mkdir(parents=True)
            (child/'cmdline').write_bytes((str(root/'native_gui.py')+'\0attach\0').encode());(child/'environ').write_bytes(b'KILO_CLIENT=vscode\0');(child/'status').write_text('PPid: 20\n')
            parent=proc/'20';parent.mkdir();(parent/'status').write_text('PPid: 1\n');(parent/'cmdline').write_bytes(b'ordinary-shell\0')
            exe=root/'.vscode-server/server/node';exe.parent.mkdir(parents=True);exe.write_text('synthetic public extension host');(parent/'exe').symlink_to(exe)
            with self.assertRaisesRegex(w.Blocked,'actual VS Code attachment'):visible.attachment(root,proc)
            (parent/'cmdline').write_bytes(b'node\0--type=extensionHost\0')
            result=visible.attachment(root,proc)
            self.assertEqual(result[0]['attach_pid'],10);self.assertEqual(result[0]['extension_host']['pid'],20)

    def test_proof_waits_for_idle_after_abort_and_never_resubmits_prompt(self):
        for busy in [True,False]:
            with self.subTest(busy=busy),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);folder=root/'qualification';folder.mkdir(mode=0o700);(root/'inference').mkdir()
                messages,intent,traces=self.fixture();w.write(folder/'intent.json',intent);w.write(folder/'submission.json',{'session_id':'own-session'})
                ledger={'requests':3,'tool_calls':3,'uncertain':False,'generated_tokens':100};w.write(root/'inference/ledger.json',ledger)
                path=root/'gui.json';w.write(path,{'fixture':True});calls=[]
                def api(root,value,method,path,data=None):
                    calls.append((method,path))
                    if path.endswith('/message'):return messages
                    if path=='/session/status':return {'own-session':{'type':'busy'}} if busy else {}
                    if path.endswith('/abort'):return None
                    raise AssertionError('Unexpected call, never resubmit')
                with patch.object(visible,'inputs',return_value=({},root,{}, {'fingerprint':'f'*64})),patch.object(visible,'api',side_effect=api),patch.object(visible,'model_trace',return_value=traces):result=visible.poll(path)
                self.assertEqual((folder/'proof.json').exists(),not busy)
                self.assertEqual(result['status'],'QUALIFICATION_QUIESCENCE_PENDING_NOT_READY' if busy else 'MODEL_TO_MCP_SUBPROOF_NOT_FULL_C00')
                self.assertFalse(any('prompt' in path for method,path in calls))

    def test_missing_wrong_failed_extra_or_coordinator_only_calls_refused(self):
        for mutation in ['missing','wrong-url','failed','wrong-output','no-marker','open-tab','duplicate-trace','coordinator-only','extra-tool','other-model','other-session']:
            m,i,t=self.fixture()
            if mutation=='missing':m[0]['parts'].pop()
            elif mutation=='wrong-url':m[0]['parts'][0]['state']['input']={'url':'file:///private'}
            elif mutation=='failed':m[0]['parts'][1]['state']['status']='error'
            elif mutation=='wrong-output':t[1]['response']['result']['content'][0]['text']='different'
            elif mutation=='no-marker':i['marker']='absent'
            elif mutation=='open-tab':m[0]['parts'][2]['state']['output']='Tabs open';t[2]['response']['result']['content'][0]['text']='Tabs open'
            elif mutation=='duplicate-trace':t.append(copy.deepcopy(t[0]))
            elif mutation=='coordinator-only':m=[]
            elif mutation=='other-model':m[0]['info']['modelID']='hosted'
            elif mutation=='other-session':m[0]['info']['sessionID']='different'
            else:m[0]['parts'].append({'type':'tool','tool':'bash','state':{'status':'completed'}})
            with self.subTest(mutation=mutation),self.assertRaises(w.Blocked):visible.correlated(m,i,t,'own-session')


if __name__=='__main__':unittest.main()
