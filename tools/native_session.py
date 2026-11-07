#!/usr/bin/env python3
"""Prepare a pinned, visible native worker from a validated private JSON profile.

native_session.py
|-- inspect       validate existing source/runtime/data pins; no installation
|-- prepare       immutable assignment + model config + two scoped channels
|-- reuse         verify receipts and bytes; never overwrite or replay
`-- lifecycle     explicit owned coordinator service (separate from model server)

No model request, host policy change, download or model restart in preparation.
The only supported model is the existing local Kolibri-1 at 262144 context.
"""
import argparse
import contextlib
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import worker as w
import inference_transport as transport
import native_inspection
import native_browser
import native_gui
import native_controls

SOURCES=('worker.py','worker_inner.py','native_namespace.py','native_gui.py','native_gui_inner.py',
         'native_browser.py','browser_inner.py','browser_route.cjs','public_snapshots.py',
         'inference_transport.py','preflight.py','native_inspection.py','native_controls.py','native_visible.py','native_session.py')
BROWSER={'playwright_browser_navigate','playwright_browser_snapshot','playwright_browser_tabs'}
FIELDS={'schema_version','runtime_root','run_id','seed','source_sha','assignment','assignment_receipt',
        'train_bundle','rights_record','approve_worker_disclosure','rootfs','extension','python',
        'browser_profile','wire_schema','model','artifacts','qualification','limits'}


def artifact(path):return {'path':str(path),'sha256':w.digest(path)}


def profile(path):
    value=w.read(w.private(path))
    w.require(os.getuid()!=0 and sys.version_info>=(3,12),'Use the normal coordinator and Python3.12')
    w.require(set(value)==FIELDS and value['schema_version']==1,'Native session profile fields')
    w.require(isinstance(value['run_id'],str) and re.fullmatch('[a-z0-9-]{1,60}',value['run_id']),'Native session Run-ID')
    w.require(type(value['seed']) is int and value['seed'] in {1,2,3},'Common seed must be 1,2 or3')
    w.require(re.fullmatch('[a-f0-9]{40}',value['source_sha']) and value['approve_worker_disclosure'] is True,'Approved source and TRAIN disclosure required')
    base=w.safe(value['runtime_root']);root=base/'build'/value['run_id']
    for name in ['assignment','assignment_receipt','train_bundle','rights_record','python','browser_profile','wire_schema','qualification']:
        w.checked_artifact(value[name])
    w.require(Path(value['python']['path']).resolve()==Path(sys.executable).resolve(),'Pinned Python differs')
    provenance=w.read(value['assignment_receipt']['path'])
    w.require(provenance['identity']['source_sha']==value['source_sha'] and provenance['identity']['archive_sha256']==value['assignment']['sha256'],'Assignment provenance differs')
    for name in ['rootfs','extension']:
        row=value[name];w.require(set(row)=={'path','tree_sha256'} and w.tree(row['path'])==w.pin(row['tree_sha256']),name+' tree changed')
    model=value['model']
    w.require(model.get('id')=='kolibri-1' and model.get('context_tokens')==262144 and model.get('local_inference_only') is True and model.get('revision'),'Existing local Kolibri identity required')
    for name in ['tokenizer_sha256','backend_identity_sha256']:w.pin(model.get(name))
    w.require(set(value['artifacts'])=={'kilo','brave','node','mcp_schema','dependency_lock'},'Session artifact identities')
    for row in value['artifacts'].values():w.checked_artifact(row)
    schema=w.read(value['wire_schema']['path']);tools=schema['tools'];pins={t['name']:transport.sha(transport.encoded(transport.schema(t['parameters']))) for t in tools}
    w.require(schema['pins']==pins and BROWSER|{'bash','read','write','edit'}<=set(pins)<=transport.ALLOWED_TOOLS,'Actual pinned Kilo/MCP schemas required')
    for name in ['address_space_mib','file_size_mib','open_files','processes']:
        w.require(type(value['limits'].get(name)) is int and value['limits'][name]>0,'Session resource limits')
    return value,root,pins


def argv(root,value,which):
    python=value['python']['path']
    if which=='inference':return [python,'-B',str(root/'inference_transport.py'),'host','--policy',str(root/'policy.json'),'--directory',str(root/'inference')]
    return [python,'-B',str(root/'native_browser.py'),'--profile',str(root/'browser-profile.json')]


def channel(root,value,which):
    arguments=argv(root,value,which)
    return {'socket':str(root/which/('inference.sock' if which=='inference' else 'browser.sock')),
            'peer_uid':os.getuid(),'peer_executable_sha256':value['python']['sha256'],
            'peer_cmdline_sha256':w.sha(b'\x00'.join(a.encode() for a in arguments)+b'\x00')}


def provider(pins):
    permission={'*':'deny',**{n:'allow' for n in pins},'external_directory':{'*':'deny'}}
    return {'enabled_providers':['001'],'model':'001/kolibri-1','small_model':'001/kolibri-1',
        'autoupdate':False,'share':'disabled','snapshot':False,'privacy_mode':True,'remote_control':False,'web_search':False,
        'compaction':{'auto':False,'prune':False},'default_agent':'modelbench',
        'provider':{'001':{'name':'Isolated Kolibri-1 FP8 V5','npm':'@ai-sdk/openai-compatible',
            'options':{'baseURL':'http://127.0.0.1:18080/v1','apiKey':'local-placeholder-not-secret','timeout':2147483647},
            'models':{'kolibri-1':{'name':'Kolibri-1 FP8 V5','limit':{'context':262144,'output':32768},'tool_call':True,'reasoning':True}}}},
        'permission':permission,'mcp':{'kilo-playwright':{'enabled':False},'playwright':{'type':'local','enabled':True,'timeout':120000,'command':['/usr/bin/python3','-B','/opt/modelbench/worker_inner.py','mcp']}},
        'agent':{'title':{'disable':True},'summary':{'disable':True},'compaction':{'disable':True},
            'modelbench':{'mode':'primary','model':'001/kolibri-1','temperature':.2,'top_p':1,'steps':100,'permission':permission,
                'prompt':'Follow the supplied frozen assignment and coordinator run manifest. Use only provider001/kolibri-1 and the approved local tools. Qualification is browser-only until the coordinator readiness gate. No installations, model/server changes, hosted providers, private reference, TEST/EVAL or other model runs.'}}}


def prepared(path):
    value,root,pins=profile(path);origin=Path(__file__).parent
    identity={'profile':value,'sources':{name:w.digest(origin/name) for name in SOURCES},'builder':w.digest(Path(__file__))}
    receipt_path=root/'session-prepared.json'
    if root.exists():
        receipt=w.read(w.private(receipt_path));w.require(receipt['identity']==identity,'Session inputs changed; use a new Run-ID')
        for name,digest in receipt['sealed'].items():w.require(w.digest(root/name)==digest,'Prepared session source changed: '+name)
        w.require(w.tree(root/'extension')==receipt['extension_tree_sha256'],'Prepared extension changed')
        record=w.read(root/value['run_id']/'run.json');w.verify_frozen(root/value['run_id'],record)
        w.require(w.digest(root/value['run_id']/'workspace/build/hpi-train-visible.jsonl')==value['train_bundle']['sha256'],'TRAIN changed')
        return dict(receipt,reused=True)
    root.mkdir(parents=True,mode=0o700);w.write(root/'prepare-intent.json',identity)
    for name in SOURCES:shutil.copyfile(origin/name,root/name)
    for name in ['inference','browser']:(root/name).mkdir(mode=0o700)
    browser=w.read(value['browser_profile']['path']);browser.update(root=str(root/'browser'),mode='TRIAL',python=value['python'],constructor=artifact(root/'native_namespace.py'))
    browser['sources']={name:artifact(root/name) for name in ['native_browser.py','browser_inner.py','browser_route.cjs','public_snapshots.py','worker.py','native_namespace.py']}
    for name in ['brave_resources','mcp_modules']:
        w.require(native_browser.asset_tree(browser[name]['path'])==browser[name]['tree_sha256'],'Sealed browser assets changed')
    w.write(root/'browser-profile.json',browser);w.write(root/'modelbench.json',provider(pins))
    assignment=w.read(value['assignment_receipt']['path']);agent_path=root/value['run_id']/'workspace/AGENTS.md'
    artifacts=dict(value['artifacts'],browser_policy=artifact(root/'browser-profile.json'),agent_instructions={'path':str(agent_path),'sha256':assignment['identity']['files']['AGENTS.md']})
    config={'schema_version':1,'policy':w.POLICY,'native_namespace':{'constructor':artifact(root/'native_namespace.py'),'gui_inner':artifact(root/'native_gui_inner.py'),'python':value['python'],'uid':os.getuid(),'gid':os.getgid()},
        'rootfs':value['rootfs'],'model':value['model'],'artifacts':artifacts,'qualification':value['qualification'],'limits':value['limits'],
        'agent':{'transport':'native-visible','gui_root':str(root),'environment':{},'config_files':[dict(artifact(root/'modelbench.json'),destination='/home/worker/.config/kilo/modelbench.json')]},
        'channels':{name:channel(root,value,name) for name in ['inference','browser']}}
    w.write(root/'toolchain.json',config)
    # Run the copied implementation so its launcher pin/constructor paths agree.
    import importlib.util
    spec=importlib.util.spec_from_file_location('prepared_native_worker',root/'worker.py');worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
    result=worker.prepare(SimpleNamespace(run_id=value['run_id'],source_sha=value['source_sha'],package=Path(value['assignment']['path']),package_sha256=value['assignment']['sha256'],toolchain=root/'toolchain.json',
        rights_record=Path(value['rights_record']['path']),approve_worker_disclosure=True,train_bundle=Path(value['train_bundle']['path']),train_sha256=value['train_bundle']['sha256'],seed=value['seed'],model='kolibri-1',runs=root,elapsed_only=True))
    run=root/value['run_id'];record=w.read(run/'run.json');worker.validate_config(root/'toolchain.json')
    policy={'run_id':value['run_id'],'mode':'GATED_TRIAL','seed':value['seed'],**{k:record['budget'][k] for k in ['max_output_tokens_per_turn','max_agent_turns','max_tool_calls','max_total_generated_tokens']},
        'wall_seconds':None,'tools':pins,'qualification_turns':3,'qualification_output_tokens':2048,
        'execution':{'record':artifact(run/'run.json'),'toolchain':artifact(root/'toolchain.json'),'preflight':artifact(root/'preflight.py'),'model_identity_sha256':value['model']['backend_identity_sha256']}}
    transport.check_policy(policy);w.write(root/'policy.json',policy)
    extension_tree=native_inspection.derive_extension(Path(value['extension']['path']),root/'extension',root,value['extension']['tree_sha256'])
    settings={'schema_version':1,'mode':'GATED_NATIVE_TRIAL','root':str(root),'run_id':value['run_id'],'run_directory':value['run_id'],
        'coordinator_unit':'ai-bench42-session-'+value['run_id']+'.service','toolchain':artifact(root/'toolchain.json'),'record':artifact(run/'run.json'),'inference_policy':artifact(root/'policy.json'),
        'rootfs_tree_sha256':value['rootfs']['tree_sha256'],'sources':{name:artifact(root/name) for name in SOURCES if name.endswith('.py')},'extension_tree_sha256':extension_tree}
    w.write(root/'gui.json',settings)
    sealed={name:w.digest(root/name) for name in (*SOURCES,'browser-profile.json','modelbench.json','toolchain.json','policy.json','gui.json',str(Path(value['run_id'])/'run.json'))}
    receipt={'status':'PREPARED_NOT_READY','identity':identity,'sealed':sealed,'extension_tree_sha256':extension_tree,'reused':False}
    w.write(receipt_path,receipt);return receipt


def unit(value):return 'ai-bench42-session-'+value['run_id']+'.service'


def state(value):
    result=subprocess.run(['systemctl','--user','show',unit(value),'-p','LoadState','-p','ActiveState','-p','MainPID','-p','InvocationID','-p','ExecStart','-p','Restart','-p','KillMode','-p','RuntimeMaxUSec','-p','MemoryMax','-p','MemorySwapMax','-p','TasksMax'],capture_output=True,text=True,timeout=5)
    w.require(result.returncode in (0,4),'Session service state unavailable')
    return dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)


def running(root,actual):
    receipt=w.read(root/'session-started.json')
    w.require(receipt['unit_state']==actual and actual.get('ActiveState')=='active','Stopped/changed session retained; no automatic restart')
    w.require(receipt['prepared_sha256']==w.digest(root/'session-prepared.json') and receipt['runtime_sha256']==w.digest(root/'session-runtime.json'),'Session receipt changed')
    return receipt


def model_idle():
    connection=http.client.HTTPConnection('127.0.0.1',8000,timeout=5)
    try:
        connection.request('GET','/metrics');reply=connection.getresponse();raw=reply.read(2*1024*1024+1)
        w.require(reply.status==200 and len(raw)<=2*1024*1024,'Bounded model metrics unavailable')
        gauges={name:[] for name in ['vllm:num_requests_running','vllm:num_requests_waiting']}
        for line in raw.decode('utf-8').splitlines():
            for name in gauges:
                match=re.fullmatch(re.escape(name)+r'(?:\{[^\n]*\})?\s+([0-9]+(?:\.[0-9]+)?)',line)
                if match:gauges[name].append(float(match[1]))
        w.require(all(values and all(v==0 for v in values) for values in gauges.values()),'Model is busy or request gauges unavailable; no launch')
        return gauges
    finally:connection.close()


def control_inputs(path):
    # Stopping/diagnosing an owned invocation must still work after an APT or
    # extension update changes historical input pins. Never start through this.
    value=w.read(w.private(path))
    w.require(isinstance(value.get('run_id'),str) and re.fullmatch('[a-z0-9-]{1,60}',value['run_id']),'Invalid control Run-ID')
    root=w.safe(Path(value['runtime_root'])/'build'/value['run_id'])
    intent=w.read(w.private(root/'session-intent.json'))
    w.require(intent.get('profile_sha256')==w.digest(path) and intent.get('unit')==unit(value),'Control profile differs from owned launch')
    return value,root


def stop_backend(root,settings):
    actual=native_gui.state(settings)
    if actual.get('ActiveState') in {'inactive','failed'}:return True
    intent=w.read(w.private(root/'backend-intent.json'))
    w.require(intent['configuration_sha256']==w.digest(root/'gui.json') and intent['unit']==native_gui.unit(settings),'Backend stop intent differs')
    expected=actual.get('InvocationID')
    w.require(expected and str(root/'native_gui.py') in actual.get('ExecStart','') and str(root/'gui.json') in actual.get('ExecStart',''),'Refusing to stop an unidentified backend')
    receipt=root/'backend-receipt.json'
    if receipt.exists():w.require(w.read(receipt)['unit_state']['InvocationID']==expected,'Backend invocation changed')
    try:subprocess.run(['systemctl','--user','stop',native_gui.unit(settings)],capture_output=True,timeout=20,check=True)
    except (OSError,subprocess.SubprocessError):pass
    current=native_gui.state(settings)
    if current.get('ActiveState') in {'inactive','failed'}:return True
    # Stop only the exact owned invocation. Its separate cgroup may require a
    # forced kill if a frozen/browser task ignores graceful termination.
    w.require(current.get('InvocationID')==expected,'Backend replaced during stop')
    subprocess.run(['systemctl','--user','kill','--kill-whom=all','--signal=KILL',native_gui.unit(settings)],capture_output=True,timeout=5,check=True)
    subprocess.run(['systemctl','--user','stop',native_gui.unit(settings)],capture_output=True,timeout=10,check=True)
    w.require(native_gui.state(settings).get('ActiveState') in {'inactive','failed'},'Backend stop remains unverified')
    return True


def start(path):
    prepared(path);value,root,_=profile(path)
    with w.locked(root):
        actual=state(value)
        if (root/'session-started.json').exists():running(root,actual);return {'status':'RUNNING_REUSED_NOT_READY','reused':True}
        w.require(not (root/'session-intent.json').exists() and actual.get('LoadState')=='not-found','Uncertain/previous session retained; no automatic replay')
        w.write(root/'session-intent.json',{'profile_sha256':w.digest(path),'prepared_sha256':w.digest(root/'session-prepared.json'),'unit':unit(value),'created_unix':time.time()})
        command=['systemd-run','--user','--unit='+unit(value),'--property=Restart=no','--property=KillMode=control-group','--property=TimeoutStopSec=90','--property=RuntimeMaxSec=infinity',
                 '--property=MemoryMax=5G','--property=MemorySwapMax=0','--property=TasksMax=384','--property=CPUQuota=300%','--property=UMask=0077',
                 value['python']['path'],'-B',str(root/'native_session.py'),'serve','--profile',str(path)]
        result=subprocess.run(command,capture_output=True,text=True,timeout=10)
        w.require(result.returncode==0,'Owned session launch failed; preserve intent')
        # Release preparation lock before the daemon starts the GUI backend.
    deadline=time.monotonic()+75
    while time.monotonic()<deadline:
        actual=state(value)
        w.require(actual.get('ActiveState') not in {'inactive','failed'},'Session startup failed; inspect retained logs')
        if (root/'session-runtime.json').exists():
            w.require(actual.get('ActiveState')=='active' and actual.get('Restart')=='no' and actual.get('KillMode')=='control-group' and actual.get('RuntimeMaxUSec')=='infinity','Unexpected session service policy')
            with w.locked(root):w.write(root/'session-started.json',{'unit_state':actual,'prepared_sha256':w.digest(root/'session-prepared.json'),'runtime_sha256':w.digest(root/'session-runtime.json')})
            return {'status':'AWAITING_VISIBLE_ATTACHMENT_NOT_READY','reused':False,'root':str(root)}
        time.sleep(.2)
    raise w.Blocked('Session startup outcome uncertain; no retry')


def serve(path):
    # Only an existing explicit start intent authorizes this owned daemon. No
    # downloads, model request, readiness promotion or candidate submission.
    prepared(path);value,root,_=profile(path);intent=w.read(root/'session-intent.json')
    w.require(intent['profile_sha256']==w.digest(path) and intent['prepared_sha256']==w.digest(root/'session-prepared.json'),'Session launch inputs changed')
    w.require(not (root/'session-runtime.json').exists() and not (root/'session-finished.json').exists(),'Session already ran; no replay')
    lock=w.safe(Path(value['runtime_root'])/'tools/benchmark/benchmark.lock');lock.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    children=[];logs=[];lease=None;gui_attempted=False;backend_stop_verified=True;status='STOPPED';reason='Explicit stop'
    def stop(*args):raise KeyboardInterrupt
    previous=signal.signal(signal.SIGTERM,stop)
    try:
        lease=lock.open('a')
        os.fchmod(lease.fileno(),0o600)
        try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise w.Blocked('Another benchmark owns the exclusive model lease') from None
        w.require(transport.sha(transport.encoded(transport.model_runtime_identity()))==value['model']['backend_identity_sha256'],'Live model identity changed; no launch')
        idle=model_idle()
        for name in ['inference','browser']:
            log=(root/(name+'-service.log')).open('xb');os.chmod(log.name,0o600);logs.append(log)
            children.append(subprocess.Popen(argv(root,value,name),stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True))
        deadline=time.monotonic()+40
        cfg=w.read(root/'toolchain.json')
        while True:
            w.require(all(p.poll() is None for p in children),'Scoped channel startup failed')
            if all(Path(c['socket']).is_socket() for c in cfg['channels'].values()):break
            w.require(time.monotonic()<deadline,'Scoped channel startup timeout');time.sleep(.1)
        peers={name:w.peer(c) for name,c in cfg['channels'].items()}
        native_controls.run(root/'browser-profile.json',root/'browser-controls')
        settings=w.read(root/'gui.json');gui_attempted=True;native_gui.ensure(root/'gui.json',settings,root)
        w.write(root/'session-runtime.json',{'status':'CHANNELS_AND_BACKEND_ONLY_NOT_READY','created_unix':time.time(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'pid':os.getpid(),'peers':peers,'backend_unit':native_gui.unit(settings),'backend_invocation':native_gui.state(settings)['InvocationID'],'model_identity_sha256':value['model']['backend_identity_sha256'],'admission_request_gauges':idle})
        while True:
            w.require(all(p.poll() is None for p in children),'Scoped channel exited; session cannot continue')
            current=native_gui.state(settings)
            w.require(current.get('ActiveState')=='active' and current.get('InvocationID')==w.read(root/'session-runtime.json')['backend_invocation'],'GUI backend exited/changed; no replay')
            time.sleep(1)
    except KeyboardInterrupt:pass
    except BaseException as exc:status='FAILED';reason=type(exc).__name__+': '+str(exc);raise
    finally:
        signal.signal(signal.SIGTERM,previous)
        if gui_attempted:
            try:backend_stop_verified=stop_backend(root,settings)
            except Exception as exc:backend_stop_verified=False;status='FAILED';reason='Backend teardown unverified: '+str(exc)
        for child in children:
            if child.poll() is None:
                with contextlib.suppress(ProcessLookupError):os.killpg(child.pid,signal.SIGTERM)
        for child in children:
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):os.killpg(child.pid,signal.SIGKILL)
                child.wait()
        for log in logs:log.close()
        try:w.write(root/'session-finished.json',{'status':status,'reason':reason,'finished_unix':time.time(),'child_exit_codes':[p.returncode for p in children],'backend_stop_verified':backend_stop_verified})
        finally:
            if lease is not None:lease.close()
        w.require(backend_stop_verified,'Owned backend teardown failed; retained as FAILED, never successful stop')


def stop_session(path):
    value,root=control_inputs(path);actual=state(value)
    w.require((root/'session-started.json').exists(),'No verified owned session to stop')
    receipt=w.read(root/'session-started.json')
    w.require(receipt['unit_state'].get('InvocationID')==actual.get('InvocationID') and str(root/'native_session.py') in actual.get('ExecStart',''),'Service identity changed; refusing stop')
    result=subprocess.run(['systemctl','--user','stop',unit(value)],capture_output=True,text=True,timeout=100)
    w.require(result.returncode==0 and state(value).get('ActiveState') in {'inactive','failed'},'Session stop not verified')
    finished=w.read(w.private(root/'session-finished.json'))
    w.require(finished.get('backend_stop_verified') is True and all(code is not None for code in finished['child_exit_codes']),'Owned process cleanup unverified')
    return {'status':'STOPPED_PRESERVED','retained_result':finished['status'],'model_service_changed':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['inspect','prepare','start','status','stop','serve']);p.add_argument('--profile',type=Path,required=True);a=p.parse_args()
    try:
        if a.action=='inspect':value,root,pins=profile(a.profile);print(json.dumps({'status':'INPUT_PINS_VALID_NOT_READY','destination':str(root),'tools':sorted(pins)}))
        elif a.action=='prepare':r=prepared(a.profile);print(json.dumps({'status':r['status'],'reused':r['reused']}))
        elif a.action=='start':print(json.dumps(start(a.profile)))
        elif a.action=='stop':print(json.dumps(stop_session(a.profile)))
        elif a.action=='status':
            value,root=control_inputs(a.profile);print(json.dumps({'service':state(value),'root':str(root),'ready_receipt_present':(root/'inference/ready.json').exists(),'candidate_started':(root/value['run_id']/'candidate-start.json').exists()}))
        else:serve(a.profile)
        return 0
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
