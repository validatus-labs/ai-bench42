"""Native boundary planning/filter regressions; live namespace probes are separate."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import native_namespace as native
import worker


class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.fs=self.root/'rootfs';self.fs.mkdir()
        for name in ['proc','dev','tmp','run','home','root','workspace','opt/modelbench']:(self.fs/name).mkdir(parents=True,exist_ok=True)
        self.value={'schema_version':1,'uid':os.getuid() or 1001,'gid':os.getgid() or 1001,'rootfs':str(self.fs),
                    'mounts':[],'environment':{'HOME':'/home/worker'},'argv':['/usr/bin/python3','-c','pass'],'cwd':'/workspace'}

    def check(self):
        path=self.root/'manifest.json';path.write_text(json.dumps(self.value));path.chmod(0o600)
        return native.validate(path,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_coordinator_report_archive_is_rejected(self):
        for name in ['docs/reports','docs/reports/kolibri.md','docs/reports/evidence/run.md']:
            with self.assertRaisesRegex(worker.Blocked,'outcome-free assignment'):worker.assignment_path(name)
        worker.assignment_path('docs/CONTRACT.md')

    def test_valid_private_plan(self):self.assertEqual(self.check(),self.value)

    def test_root_identity_rejected(self):
        self.value['uid']=0
        with self.assertRaisesRegex(ValueError,'Non-root'):self.check()

    def test_credentials_rejected(self):
        self.value['environment']['API_KEY']='synthetic'
        with self.assertRaisesRegex(ValueError,'credential'):self.check()

    def test_host_root_bind_rejected(self):
        self.value['mounts']=[{'source':'/','target':'/workspace','writable':False}]
        with self.assertRaisesRegex(ValueError,'Invalid mount'):self.check()

    def test_escape_target_rejected(self):
        self.value['mounts']=[{'source':str(self.root),'target':'/etc','writable':False}]
        with self.assertRaisesRegex(ValueError,'outside managed'):self.check()

    def test_symlink_source_rejected(self):
        (self.root/'link').symlink_to(self.fs)
        self.value['mounts']=[{'source':str(self.root/'link'),'target':'/workspace','writable':False}]
        with self.assertRaisesRegex(ValueError,'symlink'):self.check()

    def test_modified_manifest_rejected(self):
        self.check();path=self.root/'manifest.json'
        with self.assertRaisesRegex(ValueError,'hash'):native.validate(path,'0'*64)

    def run_filter(self,machine,syscall,flags=0,arch=None):
        arch=arch or {'aarch64':0xc00000b7,'x86_64':0xc000003e}[machine]
        data={0:syscall,4:arch,16:flags};code=native.filter_instructions(machine);pc=0;a=0
        for _ in range(64):
            op,jt,jf,k=code[pc];pc+=1
            if op==0x20:a=data[k]
            elif op==0x15:pc+=jt if a==k else jf
            elif op==0x45:pc+=jt if a&k else jf
            elif op==0x06:return k
            else:self.fail('Unknown instruction')
        self.fail('Filter did not terminate')

    def test_both_architectures_deny_nested_namespaces_and_allow_normal_threads(self):
        for machine,unshare,setns,clone in [('aarch64',97,268,220),('x86_64',272,308,56)]:
            for syscall in [unshare,setns]:self.assertEqual(self.run_filter(machine,syscall),0x50001)
            self.assertEqual(self.run_filter(machine,435),0x50026)
            self.assertEqual(self.run_filter(machine,clone,0x10000000),0x50001)
            self.assertEqual(self.run_filter(machine,clone,0x3d0f00),0x7fff0000)
            self.assertEqual(self.run_filter(machine,1),0x7fff0000)

    def test_unexpected_architecture_is_killed(self):
        self.assertEqual(self.run_filter('aarch64',1,arch=0x40000003),0x80000000)
        self.assertEqual(self.run_filter('x86_64',0x40000000|272),0x50001)

    def test_native_plan_repeat_preserves_manifest_and_has_no_bwrap(self):
        run=self.root/'run';run.mkdir();ws=run/'workspace';ws.mkdir()
        for name in ['melusense','tests','build']:(ws/name).mkdir()
        source=ROOT/'tools/native_namespace.py';python=Path(sys.executable).resolve()
        config={'native_namespace':{'uid':self.value['uid'],'gid':self.value['gid'],
                'constructor':{'path':str(source),'sha256':worker.digest(source)},'python':{'path':str(python),'sha256':worker.digest(python)}},
                'rootfs':{'path':str(self.fs)},'agent':{'environment':{},'config_files':[]},'channels':{}}
        record={'identity':{'run_id':'synthetic','seed':1},'frozen':{'tests/fixed.py':'synthetic'}}
        first=worker.native_command(run,record,config,'probe');manifest=Path(first[first.index('--manifest')+1]);before=(manifest.read_bytes(),manifest.stat().st_mtime_ns)
        self.assertEqual(first,worker.native_command(run,record,config,'probe'))
        self.assertEqual(before,(manifest.read_bytes(),manifest.stat().st_mtime_ns))
        self.assertNotIn('bwrap',' '.join(first));self.assertEqual(first[:2],['sudo','-n'])
        value=json.loads(manifest.read_text());self.assertTrue(any(x['target']=='/workspace/tests/fixed.py' and not x['writable'] for x in value['mounts']))
        self.assertTrue(any(x['target']=='/workspace/build/hpi-train-visible.jsonl' and not x['writable'] for x in value['mounts']))


if __name__=='__main__':unittest.main()
