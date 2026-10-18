"""Safety, convergence and real stdio transport tests; no browser/model installation."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('installer',Path(__file__).with_name('install-playwright-mcp.py'))
mod=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(mod)


class InstallerTests(unittest.TestCase):
    def tree(self,base):
        return {str(p.relative_to(base)):(p.lstat().st_mode,p.lstat().st_mtime_ns,p.read_bytes() if p.is_file() else None)
                for p in base.rglob('*')}

    def test_profile_rejects_unknown_and_boolean_version(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'config').mkdir();p=root/'config/playwright-mcp.json'
            for extra in ({'extra':True},{'version':True},{'browser':'/tmp/chrome'}):
                p.write_text(json.dumps(dict(mod.load_profile(),**extra)))
                with self.assertRaises(ValueError):mod.load_profile(root)

    def test_install_repeat_retains_bytes_modes_and_mtimes(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod,'identity'),patch.object(mod,'inventory',return_value={'fixture':'pinned'}),contextlib.redirect_stdout(io.StringIO()) as output:
            p=dict(mod.load_profile(),runtime=str(Path(d)/'tool'))
            mod.install(p);before=self.tree(Path(d)/'tool');output.truncate(0);output.seek(0)
            mod.install(p)
            self.assertEqual(json.loads(output.getvalue())['status'],'UNCHANGED')
            self.assertEqual(self.tree(Path(d)/'tool'),before)

    def test_unmanaged_target_refused_without_rewrite_or_lock(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod,'identity'),patch.object(mod,'inventory',return_value={}):
            base=Path(d)/'tool';base.mkdir(mode=0o700);(base/'unmanaged').write_text('retain')
            before=self.tree(base)
            with self.assertRaises(RuntimeError):mod.install(dict(mod.load_profile(),runtime=str(base)))
            self.assertEqual(self.tree(base),before);self.assertFalse((Path(d)/'playwright-tool-install.lock').exists())

    def test_changed_dependency_seal_or_managed_file_refused(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod,'identity'),patch.object(mod,'inventory',return_value={'seal':'a'}) as inventory,contextlib.redirect_stdout(io.StringIO()):
            base=Path(d)/'tool';profile=dict(mod.load_profile(),runtime=str(base));mod.install(profile);before=self.tree(base)
            inventory.return_value={'seal':'b'}
            with self.assertRaises(RuntimeError):mod.install(profile)
            self.assertEqual(before,self.tree(base))
            inventory.return_value={'seal':'a'};(base/'playwright-mcp').write_text('changed');changed=self.tree(base)
            with self.assertRaises(RuntimeError):mod.install(profile)
            self.assertEqual(changed,self.tree(base))

    def test_staging_failure_keeps_candidate_without_target(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod,'identity'),patch.object(mod,'inventory',side_effect=[{'seal':1},{'seal':2}]):
            base=Path(d)/'tool'
            with self.assertRaisesRegex(RuntimeError,'candidate retained'):mod.install(dict(mod.load_profile(),runtime=str(base)))
            self.assertFalse(base.exists());self.assertEqual(len(list(Path(d).glob('.playwright-tool-stage-*'))),1)

    def test_atomic_publish_refuses_even_empty_concurrent_directory(self):
        with tempfile.TemporaryDirectory() as d:
            a=Path(d)/'a';b=Path(d)/'b';a.mkdir();b.mkdir();(a/'new').write_text('data')
            with self.assertRaises(FileExistsError):mod.publish(a,b)
            self.assertTrue((a/'new').is_file());self.assertEqual(list(b.iterdir()),[])

    def test_module_tree_seal_detects_bytes_and_external_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'modules';base.mkdir();p=base/'test.js';p.write_text('a');first=mod.seal_modules(base)
            p.write_text('b');self.assertNotEqual(mod.seal_modules(base),first)
            (base/'external').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):mod.seal_modules(base)

    def test_launcher_syntax_sandbox_environment_and_override_refusal(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d)/'tool';files=mod.desired(dict(mod.load_profile(),runtime=str(base)),{});data=files['playwright-mcp'][0]
            subprocess.run(['/bin/bash','-n'],input=data,check=True)
            p=Path(d)/'launcher';p.write_bytes(data)
            result=subprocess.run(['/bin/bash',str(p),'--no-sandbox'],capture_output=True)
            self.assertEqual(result.returncode,2);self.assertFalse(base.exists())
            self.assertIn(b'/usr/bin/env -i',data);self.assertIn(b'--isolated --sandbox',data)
            self.assertNotIn(b'--cdp-endpoint',data)

    def protocol(self,folder,fail=False):
        code='''import sys,json
for line in sys.stdin:
 d=json.loads(line)
 if 'id' not in d:continue
 if d['method']=='initialize':r={'serverInfo':{'name':'fixture'}}
 elif d['method']=='tools/list':r={'tools':[{'name':'browser_snapshot'}]}
 else:r={'isError':False,'content':[{'type':'text','text':'observed'}]}
 print(json.dumps({'jsonrpc':'2.0','id':d['id'],'result':r}),flush=True)
'''
        if fail:code="import time\ntime.sleep(10)\n"
        path=folder/'fake.py';path.write_text(code);real=subprocess.Popen
        def spawn(*args,**kwargs):return real([sys.executable,'-B','-u',str(path)],**kwargs)
        return patch.object(mod.subprocess,'Popen',side_effect=spawn)

    def test_real_stdio_handshake_tool_call_and_owned_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            with self.protocol(folder):
                mcp=mod.Mcp(Path('/unused'),folder,dict(os.environ))
                try:
                    info,tools=mcp.initialize();self.assertEqual(info['serverInfo']['name'],'fixture')
                    self.assertEqual(tools[0]['name'],'browser_snapshot')
                    self.assertEqual(mod.text(mcp.call('browser_snapshot',{})),'observed')
                finally:mcp.close()
                self.assertIsNotNone(mcp.child.poll())

    def test_protocol_timeout_cleans_only_owned_child(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)
            with self.protocol(folder,True),patch.object(mod,'RPC_TIMEOUT',0.02):
                mcp=mod.Mcp(Path('/unused'),folder,dict(os.environ))
                with self.assertRaisesRegex(RuntimeError,'timeout'):mcp.initialize()
                mcp.close();self.assertIsNotNone(mcp.child.poll())

    def legacy(self,profile,base):
        mod.install(profile)
        launcher=(base/'playwright-mcp').read_bytes().replace(('TMPDIR='+profile['temporary_root']).encode(),('TMPDIR='+str(base/'tmp')).encode())
        manifest=json.loads((base/'manifest.json').read_text());manifest['profile'].pop('temporary_root')
        manifest['files']['playwright-mcp']['sha256']=mod.sha(launcher)
        raw=mod.encoded(manifest);(base/'manifest.json').write_bytes(raw);(base/'playwright-mcp').write_bytes(launcher)
        return mod.sha(raw)

    def test_only_known_rejected_pilot_repair_and_unchanged_repeat(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod,'identity'),patch.object(mod,'inventory',return_value={}),contextlib.redirect_stdout(io.StringIO()) as output:
            base=Path(d)/'tool';profile=dict(mod.load_profile(),runtime=str(base))
            legacy_sha=self.legacy(profile,base)
            with patch.object(mod,'REJECTED_MANIFEST_SHA256',legacy_sha):
                output.truncate(0);output.seek(0);mod.install(profile)
                self.assertEqual(json.loads(output.getvalue())['status'],'REPAIRED_REJECTED_PILOT')
                run=next((base/'runs').glob('repair-*'));self.assertTrue((run/'before-playwright-mcp').is_file())
                self.assertEqual(json.loads((run/'receipt.json').read_text())['status'],'REPAIRED_REJECTED_PILOT')
                before=self.tree(base);output.truncate(0);output.seek(0);mod.install(profile)
                self.assertEqual(json.loads(output.getvalue())['status'],'UNCHANGED');self.assertEqual(before,self.tree(base))

    def test_failed_known_pilot_repair_restores_previous_files(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod,'identity'),patch.object(mod,'inventory',return_value={}),contextlib.redirect_stdout(io.StringIO()):
            base=Path(d)/'tool';profile=dict(mod.load_profile(),runtime=str(base));legacy_sha=self.legacy(profile,base)
            before={n:(base/n).read_bytes() for n in ('playwright-mcp','manifest.json','kilo.json')};real=mod.replace_owned
            def broken(path,data,mode):
                if path.name=='manifest.json' and data!=before['manifest.json']:raise OSError('injected manifest replacement failure')
                return real(path,data,mode)
            with patch.object(mod,'REJECTED_MANIFEST_SHA256',legacy_sha),patch.object(mod,'replace_owned',side_effect=broken):
                with self.assertRaises(OSError):mod.install(profile)
            self.assertEqual(before,{n:(base/n).read_bytes() for n in before})
            receipt=json.loads(next((base/'runs').glob('repair-*/receipt.json')).read_text());self.assertTrue(receipt['previous_files_restored'])

    def test_error_tool_response_is_retained_before_raising(self):
        with tempfile.TemporaryDirectory() as d:
            mcp=object.__new__(mod.Mcp);mcp.folder=Path(d);mcp.number=7
            response={'isError':True,'content':[{'type':'text','text':'controlled fixture error'}]}
            with patch.object(mcp,'request',return_value=response):
                with self.assertRaisesRegex(RuntimeError,'private response retained'):mcp.call('browser_navigate',{})
            self.assertEqual(json.loads((Path(d)/'tool-7-browser_navigate.json').read_text()),response)

    def test_failed_browser_check_retains_failed_receipt_and_index(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod,'identity'),patch.object(mod,'inventory',return_value={}),contextlib.redirect_stdout(io.StringIO()):
            base=Path(d)/'tool';profile=dict(mod.load_profile(),runtime=str(base));mod.install(profile)
            with patch.object(mod,'browser_probe',side_effect=RuntimeError('injected browser failure')):
                with self.assertRaisesRegex(RuntimeError,'browser failure'):mod.verify(profile)
            run=next((base/'runs').iterdir());receipt=json.loads((run/'receipt.json').read_text())
            self.assertEqual(receipt['status'],'FAILED');self.assertTrue((run/'index.json').is_file())

    def test_successful_verify_retains_existing_managed_files(self):
        with tempfile.TemporaryDirectory() as d,patch.object(mod,'identity'),patch.object(mod,'inventory',return_value={}),contextlib.redirect_stdout(io.StringIO()):
            base=Path(d)/'tool';profile=dict(mod.load_profile(),runtime=str(base));mod.install(profile)
            before={name:(base/name).read_bytes() for name in ('playwright-mcp','kilo.json','manifest.json')}
            with patch.object(mod,'browser_probe',return_value={'status':'fixture'}):mod.verify(profile)
            self.assertEqual(before,{name:(base/name).read_bytes() for name in before})


if __name__=='__main__':unittest.main()
