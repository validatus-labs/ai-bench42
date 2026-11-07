#!/usr/bin/env python3
"""Once-only visible native candidate, preserving the sealed C00 worker.

native_candidate.py
|-- start   exact READY + actual VS Code attach -> one frozen English assignment
|-- status  inspect that same session/ledger; never replay a prompt
|-- finish  require idle/accounted session -> stop own backend -> freeze/visible tests
`-- watch   persistent coordinator observation; elapsed time, no total wall deadline

No CLI worker, installation, model restart, reset, hidden evaluation or self-PASS.
Coordinator evidence stays outside the candidate workspace. A partial submission
is retained as uncertain. Repeating start only reports its existing identity.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time
import tarfile
import tempfile
import sqlite3
from urllib.parse import quote


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private(path):
    p=Path(path)
    if any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('Coordinator symlink refused')
    s=p.stat()
    if not p.is_file() or s.st_uid!=os.getuid() or s.st_nlink!=1 or s.st_mode&0o077 or s.st_size>8*1024*1024:raise ValueError('Private bounded coordinator input required')
    return json.loads(p.read_bytes())


def bind(path,online=True):
    value=private(path);root=Path(value['root'])
    if root!=Path(path).parent or value.get('mode')!='GATED_NATIVE_TRIAL':raise ValueError('Complete native visible worker required')
    prepared=private(root/'session-prepared.json');names=[]
    for name,sha in prepared['sealed'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or digest(root/name)!=sha:raise ValueError('Sealed source changed')
        if name.endswith('.py') and '/' not in name:names.append(Path(name).stem)
    def origins():
        for name in names:
            if name in sys.modules and Path(getattr(sys.modules[name],'__file__','')).resolve().parent!=root.resolve():raise ValueError('Mixed sealed worker module')
    origins();sys.path.insert(0,str(root))
    w=importlib.import_module('worker');gui=importlib.import_module('native_gui');visible=importlib.import_module('native_visible');session=importlib.import_module('native_session');transport=importlib.import_module('inference_transport')
    run=gui.run_directory(value,root);run,record,config=w.load_run(run,w.checked_artifact(value['toolchain']))
    w.require(config['agent']['transport']=='native-visible','No CLI fallback')
    if online:
        gui.inputs(path);session.running(root,session.state({'run_id':value['run_id']}))
        w.require(gui.state(value)==private(root/'backend-receipt.json')['unit_state'],'Backend changed')
        w.require(transport.sha(transport.encoded(transport.model_runtime_identity()))==config['model']['backend_identity_sha256'],'Model identity changed')
    origins();return w,gui,visible,session,transport,value,root,run,record,config


def permissions(ids,approved):
    browser={'playwright_browser_navigate','playwright_browser_snapshot','playwright_browser_tabs'}
    if not isinstance(ids,list) or not all(isinstance(n,str) for n in ids) or not (set(approved)-browser)<=set(ids):raise ValueError('Approved actual tool identifiers missing')
    # Kilo's SDK identifier endpoint excludes MCP tools; those exact three
    # schemas were independently verified and pinned by the C00 gate.
    result={name:name in approved for name in ids};result.update({name:True for name in set(approved)&browser});return result


def manifest(record,config,gate,receipt):
    return {'run_id':record['identity']['run_id'],'fingerprint':record['fingerprint'],'source_sha':record['identity']['source_sha'],
            'package_sha256':record['identity']['package_sha256'],'train_sha256':record['identity']['train_sha256'],'seed':record['identity']['seed'],
            'model':config['model'],'budget':record['budget'],'execution_wall_seconds':record['execution_wall_seconds'],
            'readiness_receipt_sha256':gate['receipt']['sha256'],'readiness_created_unix':receipt['created_unix'],
            'toolchain_sha256':record['identity']['toolchain_sha256'],
            'coordinator_attestation':'Independent current C00 accepted. Actual model-issued data-page navigate/snapshot/close already completed in this worker. Do not repeat qualification. Candidate development C01-C07 is now authorized. This inline manifest is immutable coordinator input, not a worker-editable file. No hidden evaluation acceptance is implied.'}


def start(path):
    w,gui,visible,session,transport,value,root,run,record,config=bind(path,online=False)
    with w.locked(run):
        launch=run/'candidate-start.json'
        if launch.exists():
            old=private(launch);w.require(old['fingerprint']==record['fingerprint'] and old['controller_sha256']==digest(Path(__file__)),'Existing candidate identity changed')
            return {'status':'EXISTING_CANDIDATE_NOT_REPLAYED','run_id':value['run_id'],'submission_present':(run/'candidate-submission.json').exists()}
        w,gui,visible,session,transport,value,root,run,record,config=bind(path)
        checked=transport.coding_gate(root/'inference',private(root/'policy.json'));w.require(checked is not None,'Independent READY required')
        gate,gate_hash=checked;receipt=private(gate['receipt']['path']);attachment=visible.attachment(root)
        ledger=private(root/'inference/ledger.json');w.require(ledger['requests']==3 and ledger['tool_calls']==3 and ledger['reserved_tokens']==0 and not ledger['uncertain'],'Clean preserved qualification accounting required')
        statuses=visible.api(root,value,'GET','/session/status');w.require(isinstance(statuses,dict) and all(s.get('type')=='idle' for s in statuses.values()),'Existing session is busy')
        policy=private(root/'policy.json');ids=visible.api(root,value,'GET','/experimental/tool/ids');allowed=permissions(ids,set(policy['tools']))
        frozen=run/'workspace/docs/OFFLINE_AGENT_PROMPT.md';clarification=run/'workspace/docs/COORDINATOR.md'
        prompt=frozen.read_text()+'\n\n'+clarification.read_text()+'\n\n# Immutable coordinator run manifest\n'+json.dumps(manifest(record,config,gate,receipt),sort_keys=True,indent=2)
        intent={'fingerprint':record['fingerprint'],'controller_sha256':digest(Path(__file__)),'configuration_sha256':digest(path),'started':time.time(),'readiness_gate_sha256':gate_hash,'attachment':attachment,'initial_ledger':ledger,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
        # Intent precedes even session creation. A crash never authorizes replay.
        w.write(launch,intent);w.write(run/'candidate-prompt.json',{'text':prompt})
        created=visible.api(root,value,'POST','/session',{'title':'AI-Bench42 — Kolibri Phase4 — seed '+str(record['identity']['seed']),'agent':'modelbench','model':{'providerID':'001','id':'kolibri-1'}})
        sid=created['id'];w.require(isinstance(sid,str) and sid.startswith('ses_'),'Unexpected session identity')
        w.write(run/'candidate-submission.json',{'fingerprint':record['fingerprint'],'session_id':sid,'tools':allowed,'created_unix':time.time()})
        visible.api(root,value,'POST','/session/'+sid+'/prompt_async',{'agent':'modelbench','model':{'providerID':'001','modelID':'kolibri-1'},'tools':allowed,'parts':[{'type':'text','text':prompt}]})
        w.write(run/'candidate-submitted.json',{'state':'PROMPT_ACCEPTED_NOT_RESULT','session_id':sid,'created_unix':time.time()})
        return {'status':'CANDIDATE_RUNNING','session_id':sid,'run_id':value['run_id']}


def terminal_state(status,messages,ledger,sid):
    if not isinstance(status,dict):raise ValueError('Actual session state required')
    if sid in status and status[sid].get('type')!='idle':return 'RUNNING'
    if ledger['uncertain'] or ledger['reserved_tokens']!=0:return 'UNCERTAIN_NO_REPLAY'
    assistants=[m for m in messages if m.get('info',{}).get('role')=='assistant']
    if not assistants or ledger['requests']<=3:return 'SUBMISSION_UNCERTAIN_NO_REPLAY'
    last=assistants[-1]['info']
    if any(last.get(k)!=v for k,v in {'sessionID':sid,'providerID':'001','modelID':'kolibri-1','agent':'modelbench'}.items()):raise ValueError('Candidate response belongs to another model/session')
    if not last.get('time',{}).get('completed'):return 'UNCERTAIN_NO_REPLAY'
    if any(p.get('type')=='tool' and p.get('state',{}).get('status') not in {'completed','error'} for m in messages for p in m.get('parts',[])):return 'UNCERTAIN_NO_REPLAY'
    return 'QUIESCENT_NOT_ASSESSED'


def status(path):
    w,gui,visible,session,transport,value,root,run,record,config=bind(path,online=False)
    launch=private(run/'candidate-start.json');w.require(launch['fingerprint']==record['fingerprint'] and launch['controller_sha256']==digest(Path(__file__)),'Candidate controller identity changed')
    result=run/'candidate-result.json'
    if result.exists():
        previous=private(result);frozen=w.freeze_candidate(run,record);w.require(previous['candidate_tree_sha256']==frozen['candidate_tree_sha256'],'Completed candidate changed')
        if previous.get('worker_report',{}).get('path'):
            row=previous['worker_report'];w.require(digest(run/row['path'])==row['sha256'],'Worker report evidence changed')
        for row in previous.get('transcript',{}).get('messages',[]):w.require(digest(run/row['path'])==row['sha256'],'Transcript evidence changed')
        for key in ['stdout','stderr']:
            row=previous['visible'][key];w.require(digest(run/row['path'])==row['sha256'],'Assessment evidence changed')
        return dict(previous,reused=True)
    w.require((run/'candidate-submitted.json').exists(),'Partial submission retained; never replay')
    sid=private(run/'candidate-submission.json')['session_id'];messages=visible.api(root,value,'GET','/session/'+sid+'/message?limit=1&directory=%2Fworkspace');actual=visible.api(root,value,'GET','/session/status');ledger=private(root/'inference/ledger.json')
    state=terminal_state(actual,messages,ledger,sid)
    if state=='SUBMISSION_UNCERTAIN_NO_REPLAY' and ledger['requests']==3 and time.time()-launch['started']<60:state='STARTING_NO_REPLAY'
    observation={'state':state,'session_id':sid,'session_status':actual,'ledger':ledger,'messages':messages}
    data=w.encoded(observation);w.require(len(data)<=8*1024*1024,'Candidate evidence bound exceeded')
    folder=run/'candidate-observations';folder.mkdir(mode=0o700,exist_ok=True);file=folder/(w.sha(data)+'.json')
    if not file.exists():w.write(file,observation)
    return {'status':state,'session_id':sid,'requests':ledger['requests'],'generated_tokens':ledger['generated_tokens'],'tool_calls':ledger['tool_calls'],'elapsed_seconds':time.time()-launch['started'],'observation':str(file),'observation_sha256':digest(file)}


def capture_messages(w,visible,root,value,run,sid):
    # The pinned Kilo API returns opaque pagination cursors in headers stripped
    # by its sealed UI relay. Read ONLY this session's IDs from its existing
    # local DB, then fetch each message through the bounded supported API.
    database=w.safe(run/'workspace/build/.kilo-ui/data/kilo/kilo.db')
    w.require(database.is_file() and database.stat().st_size<=256*1024*1024,'Bounded existing session DB required')
    connection=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True,timeout=1)
    try:
        connection.execute('PRAGMA query_only=ON');connection.execute('PRAGMA trusted_schema=OFF')
        connection.set_progress_handler(lambda:1,100000)
        ids=[row[0] for row in connection.execute('SELECT id FROM message WHERE session_id=? ORDER BY time_created DESC,id DESC LIMIT 513',(sid,))]
    finally:connection.close()
    w.require(0<len(ids)<=512 and len(ids)==len(set(ids)),'Message inventory count/identity invalid')
    folder=run/'candidate-transcript';folder.mkdir(mode=0o700,exist_ok=True);rows=[];total=0
    for identifier in ids:
        w.require(isinstance(identifier,str) and identifier.startswith('msg_') and len(identifier)<=128,'Invalid message identifier')
        item=visible.api(root,value,'GET','/session/'+sid+'/message/'+quote(identifier,safe='')+'?directory=%2Fworkspace')
        w.require(item.get('info',{}).get('id')==identifier and item['info'].get('sessionID')==sid,'Captured message belongs to another session')
        raw=w.encoded(item);total+=len(raw);w.require(total<=64*1024*1024,'Transcript evidence storage bound exceeded; retained')
        file=folder/(w.sha(raw)+'.json');atomic_json(w,file,item)
        rows.append({'id':identifier,'path':str(file.relative_to(run)),'sha256':w.digest(file)})
    return {'messages':rows,'captured_bytes':total,'order':'newest first','inventory_source':'read-only existing own-session message IDs; per-message API content'}


def capture_worker_report(w,run):
    source=run/'workspace/build/worker-report.json'
    if not source.exists():return {'status':'MISSING_C07_NOT_ESTABLISHED'}
    w.safe(source);w.require(source.is_file() and source.stat().st_size<=8*1024*1024,'Invalid worker report file')
    raw=source.read_bytes();checksum=w.sha(raw);target=run/('worker-report-'+checksum+'.json')
    if not target.exists():
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
    w.require(target.read_bytes()==raw,'Worker report capture changed')
    try:parsed=json.loads(raw);valid=isinstance(parsed,dict)
    except (ValueError,UnicodeDecodeError):valid=False
    return {'status':'PRESENT_UNREVIEWED' if valid else 'INVALID_JSON_C07_NOT_ESTABLISHED','path':str(target.relative_to(run)),'sha256':checksum,'independent_C07_acceptance':False}


def atomic_json(w,path,value):
    data=w.encoded(value)
    if path.exists():w.require(path.read_bytes()==data,'Conflicting coordinator publication retained');return
    fd,name=tempfile.mkstemp(prefix='.native-publish-',dir=path.parent)
    with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())
    w.publish(Path(name),path)


def stopped(w,gui,session,root,value,profile):
    actual=session.state({'run_id':value['run_id']})
    if actual.get('ActiveState') not in {'inactive','failed'} or actual.get('LoadState') not in {'not-found','loaded'}:
        session.stop_session(profile)
    else:
        # A completed transient unit may have been unloaded. Reuse its exact
        # retained cleanup evidence instead of requiring the disappeared unit.
        finished=private(root/'session-finished.json')
        w.require(finished.get('backend_stop_verified') is True and len(finished.get('child_exit_codes',[]))==2 and all(type(code) is int for code in finished['child_exit_codes']),'Retained cleanup is incomplete')
    w.require(gui.state(value).get('ActiveState') in {'inactive','failed'},'Owned backend remains active')
    for channel in private(root/'toolchain.json')['channels'].values():
        try:w.peer(channel)
        except OSError:continue
        raise w.Blocked('A stopped inference/browser channel still accepts connections')


def recoverable_freeze(w,run,record):
    w.verify_frozen(run,record);files=w.candidate_inventory(run/'workspace')
    w.require((run/'candidate-start.json').is_file(),'Candidate was not started')
    w.require(len(files)<=10000,'Candidate file count exceeds freeze bound')
    identity={'fingerprint':record['fingerprint'],'files':files};intent=run/'native-freeze-intent.json'
    atomic_json(w,intent,identity)
    archive=run/'frozen-candidate.tar';receipt=run/'frozen-candidate.json'
    if receipt.exists():return w.freeze_candidate(run,record)
    if not archive.exists():
        fd,temporary_name=tempfile.mkstemp(prefix='.native-freeze-',dir=run);staged=Path(temporary_name)
        with os.fdopen(fd,'wb') as out:
            with tarfile.open(fileobj=out,mode='w') as tar:
                total=0
                for name,checksum in files.items():
                    path=w.safe(run/'workspace'/name);w.require(w.digest(path)==checksum,'Candidate changed during freeze')
                    member=tar.gettarinfo(str(path),arcname=name);total+=member.size;w.require(total<=128*1024*1024,'Candidate freeze size bound')
                    member.uid=member.gid=member.mtime=0;member.uname=member.gname='';member.mode=0o600
                    with path.open('rb') as stream:tar.addfile(member,stream)
            out.flush();os.fsync(out.fileno())
        w.publish(staged,archive)
    # Recover a complete tar published before its receipt. Reject partial,
    # duplicate, linked, foreign or changed content, without deleting anything.
    seen={};total=0
    with tarfile.open(archive,'r:') as tar:
        for member in tar:
            w.require(member.isfile() and member.name in files and member.name not in seen,'Unexpected archive member')
            total+=member.size;w.require(total<=128*1024*1024,'Archive size bound')
            with tar.extractfile(member) as stream:seen[member.name]=hashlib.file_digest(stream,'sha256').hexdigest()
    w.require(seen==files and w.candidate_inventory(run/'workspace')==files,'Freeze content differs from candidate')
    w.verify_frozen(run,record)
    result={'schema_version':1,'fingerprint':record['fingerprint'],'files':files,'candidate_tree_sha256':w.sha(w.encoded(files)),'archive_sha256':w.digest(archive)}
    atomic_json(w,receipt,result);return w.freeze_candidate(run,record)


def finish(path,profile):
    w,gui,visible,session,transport,value,root,run,record,config=bind(path,online=False)
    if (run/'candidate-result.json').exists():return status(path)
    control_value,control_root=session.control_inputs(profile)
    w.require(control_root==root and control_value==private(root/'session-prepared.json')['identity']['profile'],'Stop profile belongs to another session')
    with w.locked(run):
        intent=run/'candidate-finish-intent.json'
        if intent.exists():
            saved=private(intent);before=saved['observation'];ledger=saved['ledger']
            w.require(saved['controller_sha256']==digest(Path(__file__)) and saved['fingerprint']==record['fingerprint'],'Partial finish identity changed')
            w.require(digest(before['observation'])==before['observation_sha256'],'Retained finish observation changed')
            if gui.state(value).get('ActiveState') not in {'inactive','failed'}:
                current=status(path);w.require(current['status']=='QUIESCENT_NOT_ASSESSED' and current['observation_sha256']==before['observation_sha256'],'Candidate changed during partial finish')
        else:
            before=status(path);w.require(before['status']=='QUIESCENT_NOT_ASSESSED','Candidate remains active/uncertain; no freeze')
            ledger=private(root/'inference/ledger.json')
            sid=private(run/'candidate-submission.json')['session_id'];transcript=capture_messages(w,visible,root,value,run,sid)
            atomic_json(w,intent,{'fingerprint':record['fingerprint'],'controller_sha256':digest(Path(__file__)),'observation':before,'ledger':ledger,'transcript':transcript})
        w.require(private(root/'inference/ledger.json')==ledger,'Usage changed before freeze; retain outcome')
        # Stop the original coordinator gracefully; it retains its benchmark
        # lease through verified backend/channel teardown. No server is restarted.
        stopped(w,gui,session,root,value,profile)
        w.require(private(root/'inference/ledger.json')==ledger,'Usage changed during freeze; retain outcome')
        frozen=recoverable_freeze(w,run,record);assessment=w.verify_candidate(run,record,config)
        result={'status':'CANDIDATE_ASSESSED_NOT_HELDOUT_PASS','fingerprint':record['fingerprint'],'candidate_tree_sha256':frozen['candidate_tree_sha256'],'visible':assessment,'worker_report':capture_worker_report(w,run),'transcript':private(intent)['transcript'],'ledger':ledger,'elapsed_seconds':time.time()-private(run/'candidate-start.json')['started'],'finished_unix':time.time()}
        atomic_json(w,run/'candidate-result.json',result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter);parser.add_argument('action',choices=['start','status','finish','watch']);parser.add_argument('--configuration',type=Path,required=True);parser.add_argument('--session-profile',type=Path);args=parser.parse_args()
    try:
        if args.action in {'finish','watch'} and args.session_profile is None:raise ValueError('--session-profile is required for verified owned teardown')
        if args.action=='watch':
            while True:
                result=status(args.configuration)
                if result['status']=='QUIESCENT_NOT_ASSESSED':result=finish(args.configuration,args.session_profile);break
                if result['status'] not in {'RUNNING','STARTING_NO_REPLAY'}:break
                time.sleep(30)
        else:result=finish(args.configuration,args.session_profile) if args.action=='finish' else {'start':start,'status':status}[args.action](args.configuration)
        print(json.dumps(result));return 0
    except (OSError,ValueError,RuntimeError,KeyError,tarfile.TarError,sqlite3.Error) as exc:print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
