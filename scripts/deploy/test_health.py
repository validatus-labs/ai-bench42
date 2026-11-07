"""Offline safety/regression checks for the self-contained health bootstrap."""
import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).with_name('dgx-spark-health-bootstrap.sh')
PAYLOAD=SOURCE.read_text().split("<<'PYTHON'\n",1)[1].rsplit('\nPYTHON',1)[0]
health=types.ModuleType('health_bootstrap')
with patch.object(sys,'argv',['python',str(SOURCE)]):
    exec(compile(PAYLOAD,str(SOURCE), 'exec'),health.__dict__)
CONFIG={'owner':health.OWNER,'interval':'60s','model_unit':health.MODEL,'model_python':'','vllm_url':'http://127.0.0.1:8000','port':9817}


def report():
    return {'owner':health.OWNER,'timestamp':1000,'boot_id':'boot-a',
            'config_sha256':health.sha(health.encoded(CONFIG)),'duration_seconds':0.1,
            'collected_at':'test','checks':[{'check_id':key,'status':0,'value':1,'detail':'fixture'} for key in health.IDS]}


class HealthTests(unittest.TestCase):
    def test_absent_model_does_not_block_standalone_health_installation(self):
        result=types.SimpleNamespace(returncode=1,stdout='LoadState=not-found\nActiveState=inactive\n',stderr='')
        with patch.object(health,'command',return_value=result):
            self.assertEqual(health.live_unit()['LoadState'],'not-found')
        result=types.SimpleNamespace(returncode=1,stdout='',stderr='system bus unavailable')
        with patch.object(health,'command',return_value=result),self.assertRaises(RuntimeError):
            health.live_unit()

    def test_strict_inputs(self):
        for interval in ('0s','1s','10000h','60s\nExecStart=bad','-1s','1.5m'):
            with self.assertRaises(ValueError):health.interval_seconds(interval)
        self.assertEqual(health.interval_seconds('2m'),120)
        for key,value in [('unknown',True),('port',True),('vllm_url','http://remote:8000'),('model_python','/tmp/python')]:
            with self.assertRaises(ValueError):health.validate_config(dict(CONFIG,**{key:value}))

    def test_stale_boot_future_and_missing_are_not_green(self):
        r=report()
        body,stale=health.exposition(r,CONFIG,1001,'boot-a')
        self.assertFalse(stale);self.assertEqual(body.count('} 0'),16)
        for ts,boot in [(2000,'boot-a'),(999,'boot-a'),(1001,'boot-b')]:
            body,stale=health.exposition(r,CONFIG,ts,boot)
            self.assertTrue(stale);self.assertEqual(body.count('} -1'),16)
            self.assertNotIn('dgx_health_observation{',body)
        with tempfile.TemporaryDirectory() as d,patch.object(health,'STATE',Path(d)):
            with self.assertRaises(FileNotFoundError):health.read_report(CONFIG)
            (Path(d)/'report.json').write_text(json.dumps(dict(r,config_sha256='changed')))
            with self.assertRaises(RuntimeError):health.read_report(CONFIG)

    def test_missing_metric_and_nan_refused(self):
        for body in ('# unavailable','vllm:num_requests_waiting{} NaN','vllm:num_requests_waiting{} +Inf'):
            with self.assertRaises(ValueError):health.metric(body,'vllm:num_requests_waiting')
        self.assertEqual(health.metric('vllm:num_requests_waiting{model="a"} 2\nvllm:num_requests_waiting{model="b"} 3','vllm:num_requests_waiting'),5)

    def test_all_sixteen_checks_and_unsupported_gpu_unknown(self):
        with patch.object(health,'checked',side_effect=RuntimeError('unavailable')),patch.object(health,'get',side_effect=RuntimeError('unavailable')),patch.object(health,'journal_events',side_effect=PermissionError('denied')),patch.object(health,'live_unit',return_value={'ActiveState':'inactive','MainPID':'0'}):
            result=health.collect(CONFIG)
        by_id={r['check_id']:r for r in result['checks']}
        self.assertEqual(tuple(by_id),health.IDS)
        for name in ('gpu.power_telemetry','gpu.temperature','gpu.nvml_available','gpu.xid_error','kernel.oom_events','cuda.torch_cpu_only','vllm.queue'):
            self.assertEqual(by_id[name]['status'],-1)
        self.assertEqual(by_id['vllm.service']['status'],3)
        self.assertNotIn('denied',json.dumps(result))

    def test_journal_truncated_access_denied_and_positive_events(self):
        def result(out='',err='',code=0):return types.SimpleNamespace(stdout=out,stderr=err,returncode=code)
        for r in [result(err='not seeing messages'),result(code=1),result(out='{}\n'*2001)]:
            with patch.object(health,'command',return_value=r),self.assertRaises(RuntimeError):health.journal_events()
        text='\n'.join(json.dumps({'MESSAGE':v}) for v in ['NVRM: Xid (PCI:00): 13','Out of memory: Killed process','normal'])
        with patch.object(health,'command',return_value=result(out=text)) as command:
            self.assertEqual(health.journal_events(),{'xid':1,'oom':1})
            self.assertIn('-k',command.call_args.args[0])
            self.assertNotIn('--kernel',command.call_args.args[0])

    def test_cuda_probe_never_executes_model_python(self):
        with patch.object(health,'command',side_effect=AssertionError('must not execute')),self.assertRaises(RuntimeError):
            health.torch_observation('',{'MainPID':'123','ActiveState':'active'})
        with patch.object(health,'command',side_effect=AssertionError('must not execute')),patch.object(Path,'read_bytes',return_value=b'/different/python\0vllm'),self.assertRaises(RuntimeError):
            health.torch_observation('/configured/python',{'MainPID':'123','ActiveState':'active'})

    def test_unmanaged_preflight_leaves_other_paths_absent(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); units=base/'units';units.mkdir();block=units/health.TIMER;block.write_text('unmanaged')
            with patch.multiple(health,PREFIX=base/'prefix',STATE=base/'state',CONFIG=base/'config',UNIT_DIR=units,SCRIPT=SOURCE),patch.object(health,'install_host_required'),patch.object(health,'live_unit',return_value={'MainPID':'0'}),patch.object(health,'unit_state',return_value={'LoadState':'not-found'}):
                with self.assertRaisesRegex(RuntimeError,'unmanaged target'):health.install()
            self.assertFalse((base/'prefix').exists());self.assertFalse((base/'state').exists());self.assertFalse((base/'config').exists())
            self.assertEqual(block.read_text(),'unmanaged')

    def test_symlinks_and_registry_drift_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'file';p.write_text('original');link=p.with_name('link');link.symlink_to(p)
            with self.assertRaises(RuntimeError):health.safe_path(link)
            registry={'owner':health.OWNER,'files':{str(p):{'sha256':health.sha(b'expected'),'mode':0o644}}}
            with self.assertRaises(RuntimeError):health.verify_registry(registry,[p])

    def test_http_reads_snapshot_only_and_routes(self):
        config=dict(CONFIG)
        server=health.HTTPServer(('127.0.0.1',0),health.handler_for(config))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        with patch.object(health,'read_report',return_value=report()),patch.object(health,'exposition',return_value=('dgx_health_snapshot_stale 0\n',False)),patch.object(health,'collect',side_effect=AssertionError('scrape cannot probe')):
            thread.start()
            try:
                client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                for path,code in [('/metrics',200),('/healthz',200),('/other',404)]:
                    client.request('GET',path);response=client.getresponse();self.assertEqual(response.status,code);response.read()
                client.close()
                with patch.object(health,'read_report',side_effect=FileNotFoundError):
                    client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                    client.request('GET','/metrics');response=client.getresponse();self.assertEqual(response.status,503);response.read();client.close()
            finally:server.shutdown();thread.join(3);server.server_close()

    def test_units_scoped_exporter_unprivileged_and_no_import_side_effects(self):
        files=health.desired_files(SOURCE.read_bytes(),CONFIG)
        self.assertEqual(len(files),5)
        text=files[health.UNIT_DIR/health.EXPORTER][0].decode()
        self.assertIn('DynamicUser=yes',text);self.assertIn('CapabilityBoundingSet=',text)
        self.assertNotIn('vllm serve',str(files))
        self.assertEqual(files[health.UNIT_DIR/health.TIMER][0].decode().count('OnUnitInactiveSec=60s'),1)

    def test_atomic_snapshot_replace_and_mode(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'report.json';health.atomic(p,b'old',0o600);health.atomic(p,b'new',0o644)
            self.assertEqual(p.read_bytes(),b'new');self.assertEqual(p.stat().st_mode&0o777,0o644)
            self.assertEqual(len(list(Path(d).iterdir())),1)

    def test_install_reinstall_and_failed_install_recovery(self):
        real_stat=Path.stat
        def as_root(path,*args,**kwargs):
            fields=list(real_stat(path,*args,**kwargs));fields[4]=0
            return os.stat_result(fields)
        for fail in (False,True):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as d:
                base=Path(d);units=base/'units';units.mkdir();state=base/'state';prefix=base/'prefix'
                active=set()
                def unit(name):
                    exists=(units/name).exists()
                    return {'LoadState':'loaded' if exists else 'not-found','ActiveState':'active' if name in active else 'inactive',
                            'UnitFileState':'enabled' if name in active else '', 'FragmentPath':str(units/name) if exists else '', 'DropInPaths':'','MainPID':'99' if name in active else '0'}
                def command(args,timeout=20):
                    if args[1:3]==['start',health.SERVICE]:(state/'report.json').write_text('fixture')
                    if args[1:3]==['enable','--now']:active.update(args[3:])
                    return ''
                with patch.multiple(health,PREFIX=prefix,STATE=state,CONFIG=base/'config',UNIT_DIR=units,SCRIPT=SOURCE),patch.object(Path,'stat',as_root),patch.object(health,'install_host_required'),patch.object(health,'live_unit',return_value={'MainPID':'0'}),patch.object(health,'unit_state',side_effect=unit),patch.object(health,'checked',side_effect=command) as commands,patch.object(health.socket,'socket'),patch.object(health,'ensure_local_ready',side_effect=RuntimeError('injected readiness failure') if fail else None),contextlib.redirect_stdout(io.StringIO()) as output:
                    if fail:
                        with self.assertRaisesRegex(RuntimeError,'readiness'):health.install()
                        self.assertFalse((prefix/'installed.json').exists())
                        self.assertFalse((prefix/'bootstrap.sh').exists())
                        self.assertFalse((base/'config').exists())
                        rollback=list((state/'private').glob('install-*/rollback.json'))
                        self.assertEqual(len(rollback),1)
                        self.assertFalse(any(p.exists() for p in (units/n for n in health.UNITS)))
                    else:
                        health.install()
                        before=(prefix/'installed.json').read_bytes()
                        commands.reset_mock();output.truncate(0);output.seek(0)
                        health.install()
                        self.assertEqual(json.loads(output.getvalue())['status'],'UNCHANGED')
                        self.assertEqual((prefix/'installed.json').read_bytes(),before)
                        self.assertFalse(any(call.args[0][1] in ('restart','start','daemon-reload') for call in commands.call_args_list))

    def test_rollback_refuses_external_edits_before_stopping_units(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'target';p.write_bytes(b'external')
            with patch.object(health,'checked') as checked,self.assertRaisesRegex(RuntimeError,'divergent'):
                health.rollback({p:(b'old',0o644)},{},{p:(b'candidate',0o644)},Path(d))
            checked.assert_not_called()


if __name__=='__main__':unittest.main()
