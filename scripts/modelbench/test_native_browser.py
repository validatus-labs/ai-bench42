"""No browser/model access: exact tool policy and explicit separate namespace role."""
import copy,json,os,sys,tempfile,subprocess,time
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_browser as browser
import native_namespace as native
import worker


class BrowserTests(unittest.TestCase):
    catalog={'https://docs.python.org/3.12/library/email.html'}
    def call(self,name,args):browser.allowed_call({'method':'tools/call','params':{'name':name,'arguments':args}},self.catalog)
    def test_only_data_and_exact_catalog(self):
        self.call('browser_navigate',{'url':'data:text/html,<p>synthetic-marker</p>'})
        self.call('browser_navigate',{'url':next(iter(self.catalog))})
        for url in ['http://127.0.0.1:8000','https://docs.python.org/private','https://docs.python.org/3.12/library/email.html?secret=x','file:///etc/passwd','https://[::1]/','http://169.254.169.254/','https://github.com/private','data:text/plain,secret']:
            with self.subTest(url=url),self.assertRaises(worker.Blocked):self.call('browser_navigate',{'url':url})
    def test_no_script_file_upload_download_or_new_tabs(self):
        for name,args in [('browser_run_code',{'code':'arbitrary'}),('browser_snapshot',{'filename':'/private/file'}),('browser_tabs',{'action':'new'}),('browser_tabs',{'action':'close','index':True}),('browser_navigate',{'url':'data:text/html,test','filename':'file'})]:
            with self.subTest(name=name),self.assertRaises(worker.Blocked):self.call(name,args)
        self.call('browser_snapshot',{});self.call('browser_tabs',{'action':'close'})
    def test_json_wire_is_one_complete_line(self):
        value={'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}}
        raw=browser.wire(value);self.assertEqual(raw.count(b'\n'),1);self.assertEqual(browser.json_frame(raw),value)

    def test_virtual_tools_server_never_exposes_worker_roots(self):
        value={'jsonrpc':'2.0','id':0,'method':'initialize','params':{'capabilities':{'roots':{},'experimental':{'unsafe':True}},'protocolVersion':'2025-11-25'}}
        result=browser.forwarded_request(value)
        self.assertEqual(result['params']['capabilities'],{})
        self.assertEqual(result['params']['protocolVersion'],'2025-11-25')
        self.assertIn('roots',value['params']['capabilities'])
        call={'jsonrpc':'2.0','id':1,'method':'tools/list'}
        self.assertEqual(browser.forwarded_request(call),call)

    def test_arbitrary_mcp_methods_and_duplicate_json_refused(self):
        with self.assertRaises(worker.Blocked):browser.allowed_call({'method':'resources/read','params':{'uri':'file:///secret'}},self.catalog)
        with self.assertRaises(worker.Blocked):browser.json_frame(b'{"jsonrpc":"2.0","id":1,"id":2}\n')

    def test_completed_call_cancellation_is_scoped_control_notification(self):
        browser.allowed_call({'jsonrpc':'2.0','method':'notifications/cancelled','params':{'requestId':2,'reason':'completed'}},self.catalog)
        for params in [{'requestId':True},{'requestId':2,'url':'https://private'},{'requestId':2,'reason':'x'*1025},{}]:
            with self.subTest(params=params),self.assertRaises(worker.Blocked):
                browser.allowed_call({'method':'notifications/cancelled','params':params},self.catalog)
        with self.assertRaises(worker.Blocked):browser.allowed_call({'method':'notifications/cancelled','id':1,'params':{'requestId':2}},self.catalog)
    def test_asset_hash_records_suid_mode_without_mutating_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'chrome-sandbox';p.write_text('synthetic');p.chmod(0o4755);first=browser.asset_tree(Path(tmp));self.assertEqual(p.stat().st_mode&0o7777,0o4755)
            p.chmod(0o755);self.assertNotEqual(first,browser.asset_tree(Path(tmp)))
    def test_browser_role_requires_fixed_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fs=root/'rootfs';fs.mkdir()
            for name in ['proc','dev','tmp','run','home','root','workspace','opt/modelbench']:(fs/name).mkdir(parents=True,exist_ok=True)
            p=root/'manifest.json';value={'schema_version':1,'role':'browser','uid':os.getuid(),'gid':os.getgid(),'rootfs':str(fs),'mounts':[],'environment':{},'argv':['/bin/sh'],'cwd':'/workspace'};worker.write(p,value)
            with self.assertRaisesRegex(ValueError,'Fixed browser'):native.validate(p,worker.digest(p))

    def snapshot(self):
        return {'result':{'content':[{'type':'text','text':'- [Snapshot](browser/page-test.yml)'}]}}

    def test_snapshot_inline_reads_only_generated_regular_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'browser').mkdir();p=root/'browser/page-test.yml';p.write_text('- paragraph: marker')
            self.assertIn('paragraph: marker',browser.inline_snapshots(self.snapshot(),root)['result']['content'][0]['text'])
            for link in ['../../private.yml','page-test.yml/../private.yml']:
                value=self.snapshot();value['result']['content'][0]['text']='- [Snapshot](browser/'+link+')'
                self.assertEqual(browser.inline_snapshots(copy.deepcopy(value),root),value)

    def test_snapshot_symlink_hardlink_oversize_and_directory_symlink_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'browser').mkdir();target=root/'private';target.write_text('private')
            p=root/'browser/page-test.yml';p.symlink_to(target)
            with self.assertRaises(OSError):browser.inline_snapshots(self.snapshot(),root)
            p.unlink();os.link(target,p)
            with self.assertRaises(worker.Blocked):browser.inline_snapshots(self.snapshot(),root)
            p.unlink();p.write_bytes(b'x'*(browser.MAX_FRAME//2+1))
            with self.assertRaises(worker.Blocked):browser.inline_snapshots(self.snapshot(),root)
            p.unlink();(root/'browser').rmdir();(root/'browser').symlink_to(root,target_is_directory=True)
            with self.assertRaises(OSError):browser.inline_snapshots(self.snapshot(),root)

    def test_sealed_asset_reuse_preserves_mtimes_and_detects_both_drifts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();(source/'file').write_text('public')
            destination=root/'sealed';expected=browser.asset_tree(source)
            sealed=browser.seal_assets(source,destination,expected)
            before=(sealed/'file').stat().st_mtime_ns
            self.assertEqual(browser.seal_assets(source,destination,expected),sealed)
            self.assertEqual((sealed/'file').stat().st_mtime_ns,before)
            (sealed/'file').write_text('changed')
            with self.assertRaises(worker.Blocked):browser.seal_assets(source,destination,expected)
            (source/'file').write_text('source drift')
            with self.assertRaises(worker.Blocked):browser.seal_assets(source,root/'other',expected)

    def test_blocked_child_input_has_deadline(self):
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)'],stdin=subprocess.PIPE)
        started=time.monotonic()
        try:
            with self.assertRaises(worker.Blocked):browser.send_child(child,b'x'*browser.MAX_FRAME,seconds=.05)
            self.assertLess(time.monotonic()-started,1)
        finally:child.terminate();child.wait(timeout=2);child.stdin.close()
