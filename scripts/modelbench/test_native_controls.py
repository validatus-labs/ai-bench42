"""Actual local MCP rejection and immutable control-evidence reuse; no browser/model."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_controls as controls
import native_browser as browser
import worker as w


class ControlTests(unittest.TestCase):
    def test_sandbox_checks_actual_renderer_role_not_all_browser_processes(self):
        import copy
        def process(role,seccomp,caps='0'):
            return {'process_type':role,'no_sandbox':False,'caps':{'NoNewPrivs':'1','Seccomp':str(seccomp),'CapEff':caps}}
        observed={'browser':process('browser',0),'zygote':process('zygote',0,'200000'),'renderer':process('renderer',2)}
        self.assertEqual(controls.sandbox_processes(observed),1)
        for label in ['no-renderer','renderer-no-filter','renderer-caps','no-new-privs','disabled-sandbox']:
            value=copy.deepcopy(observed)
            if label=='no-renderer':del value['renderer']
            elif label=='renderer-no-filter':value['renderer']['caps']['Seccomp']='0'
            elif label=='renderer-caps':value['renderer']['caps']['CapEff']='1'
            elif label=='no-new-privs':value['browser']['caps']['NoNewPrivs']='0'
            else:value['browser']['no_sandbox']=True
            with self.subTest(label=label),self.assertRaises(w.Blocked):controls.sandbox_processes(value)

    def test_forbidden_first_frame_rejected_before_any_browser_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);server=browser.Server(str(root/'browser.sock'),browser.MCP)
            server.root=root;server.snapshots=type('Snapshots',(),{'rows':{'https://docs.python.org/3/':{}}})();server.profile={}
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with patch.object(browser.subprocess,'Popen') as child:
                    for url in ['http://127.0.0.1:8000/','http://[::1]/','file:///etc/shadow','https://denied.invalid/',
                                'https://alice:dummy@docs.python.org/3/'  # trufflehog:ignore -- synthetic denial-test credential
                                ]:
                        client=controls.Client(root/'browser.sock')
                        try:reply=client.exchange('tools/call',{'name':'browser_navigate','arguments':{'url':url}})
                        finally:client.close()
                        self.assertEqual(reply['error']['code'],-32600)
                    child.assert_not_called()
                events=[json.loads(s) for s in (root/'events.jsonl').read_text().splitlines()]
                self.assertEqual(len(events),5);self.assertTrue(all(e['kind']=='mcp-denied' for e in events))
            finally:server.shutdown();server.server_close();thread.join(timeout=3)

    def test_control_receipt_reuse_verifies_inputs_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'profile.json';w.write(profile,{'root':str(root/'channel')})
            out=root/'controls';out.mkdir(mode=0o700);w.write(out/'raw.json',{'fixture':'not a browser observation'})
            receipt={'identity':{'profile_sha256':w.digest(profile),'implementation_sha256':w.digest(Path(controls.__file__))},'evidence':[{'path':'raw.json','sha256':w.digest(out/'raw.json')}],'reused':False}
            w.write(out/'receipt.json',receipt)
            with patch.object(controls,'Client',side_effect=AssertionError('No replay')):
                self.assertTrue(controls.run(profile,out)['reused'])
                (out/'raw.json').write_text('drift')
                with self.assertRaisesRegex(w.Blocked,'evidence changed'):controls.run(profile,out)
            self.assertEqual((out/'raw.json').read_text(),'drift')

    def test_partial_controls_never_silently_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'profile.json';w.write(profile,{'root':str(root/'channel')})
            out=root/'partial';out.mkdir();w.write(out/'intent.json',{'incomplete':True})
            with patch.object(controls,'Client',side_effect=AssertionError('No replay')):
                with self.assertRaises((OSError,w.Blocked)):controls.run(profile,out)
            self.assertTrue((out/'intent.json').exists())


if __name__=='__main__':unittest.main()
