#!/usr/bin/env python3
"""Externally reviewed C00 promotion for a sealed, already observed native worker.

native_readiness.py
|-- inspect   validate sealed native sources/current peers + preserved live proof
|-- evidence  map 21 checks to raw controls, source policy and explicit limits
`-- promote   require independent review of that exact index, then READY only

Runs outside the worker image. It never edits the prepared worker, replays its
canary, installs software, starts coding or manufactures an independent review.
Native toolchain.qualification pins its visible proof collector; this separate
coordinator adapter and review are additionally bound in the readiness evidence.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import sys
import time


def private_json(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):raise ValueError('Coordinator symlink refused')
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077 or info.st_size>8*1024*1024:raise ValueError('Private bounded coordinator file required')
    return json.loads(path.read_bytes())


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_map():
    return {
      'kilo_identity_and_config':('observed/pinned',['toolchain','run','backend','live'],'Exact installed/configuration hashes and attached extension host.'),
      'browser_node_mcp_identity':('observed/pinned',['toolchain','browser_broker','browser_processes'],'Existing binary/npm seals and actual MCP responses.'),
      'mcp_schema_parity':('observed/pinned',['toolchain','policy','mcp_trace'],'All three actual MCP schemas normalized against the ten common wire pins.'),
      'headless':('sealed executed configuration',['browser_inner','browser_broker','backend'],'Fixed inner argv contains headless; not a separate current process-command capture.'),
      'browser_sandbox':('observed/pinned',['browser_processes','browser_inner'],'Actual renderer Seccomp2/NNP1/CapEff0; main and zygote recorded separately.'),
      'fresh_profile':('isolated construction',['browser_inner','browser_broker','live'],'Separate private namespace/scratch per MCP connection and fixed --isolated argv.'),
      'service_workers_blocked':('effective configuration',['effective_config','browser_inner'],'No successful service-worker registration experiment claimed.'),
      'downloads_uploads_denied':('effective configuration/tool surface',['effective_config','browser_broker','mcp_trace'],'acceptDownloads=false, no upload/evaluation/file-output tool exposed.'),
      'task_scoped_read_only_research':('closed-world construction',['snapshots','browser_route','browser_broker'],'Exact finite pinned offline URL catalog; GET only; no live network fallback.'),
      'public_https_allowed':('observed offline URL/DOM',['controls_trace','controls'],'Pinned RFC source served under its HTTPS URL; not a new internet fetch.'),
      'private_ipv4_denied':('observed/policy',['controls_trace','live'],'Namespace probes, MCP rejection and local-page denied fetch.'),
      'private_ipv6_denied':('observed/policy',['controls_trace','live'],'Namespace probe, MCP rejection and local-page denied fetch.'),
      'dns_rebinding_denied':('closed-world construction + denials',['snapshots','browser_route','live','controls_trace'],'No DNS/network path exists; no live adversarial rebinding exercise claimed.'),
      'redirect_to_private_denied':('closed-world construction + URL denial',['snapshots','browser_route','controls_trace'],'Only validated200snapshot bodies are fulfilled; query denial is not an exercised HTTP redirect.'),
      'authenticated_pages_denied':('observed/policy',['controls_trace','snapshots','browser_broker'],'Userinfo rejected; public immutable snapshots only.'),
      'inference_transport_scoped':('observed/pinned',['inference','inference_events','toolchain','live'],'Fixed loopback backend through private UDS; exact model/method/path/schema checks.'),
      'local_backend_identity':('live read-only observation',['live','toolchain'],'Exact unit/PID/start/boot/API identity, no model-server writes.'),
      'budgets_enforced':('observed/pinned',['policy','proof','inference_events','live'],'Three bounded qualification requests charged to shared ledger; fourth denied before generation.'),
      'model_issued_mcp_marker':('observed model/tool correlation',['proof','model_messages','mcp_trace'],'Exact model/provider/session, ordered args/output and actual DOM marker.'),
      'browser_page_closed':('observed',['proof','model_messages','mcp_trace'],'Actual model-issued close returned No open tabs.'),
      'browser_host_files_denied':('observed/pinned',['controls_trace','live','browser_broker'],'file URL rejected; private browser root excludes worker/home/TRAIN.'),
    }


def verify_events(events,ledger):
    if len(events)!=4 or any(row.get('route')!='/v1/chat/completions' or row.get('method')!='POST' or row.get('execution_stage')!='qualification' or row.get('effective_output_tokens')!=2048 for row in events):raise ValueError('Exact qualification routes/bounds required')
    success=events[:3];denied=events[3]
    if [r.get('request_number') for r in success]!=[1,2,3]:raise ValueError('Model request numbering differs')
    tools={'playwright_browser_navigate','playwright_browser_snapshot','playwright_browser_tabs'}
    if any(r.get('status')!=200 or r.get('upstream_started') is not True or r.get('completed') is not True or r.get('phase')!='completed' or r.get('tool_calls')!=1 or set(r.get('tools',[]))!=tools or type(r.get('usage',{}).get('completion_tokens')) is not int or not 0<r['usage']['completion_tokens']<=2048 for r in success):raise ValueError('Incomplete or misbound model request accounting')
    if sum(r['usage']['completion_tokens'] for r in success)!=ledger['generated_tokens']:raise ValueError('Model transport usage differs from ledger')
    if denied.get('status')!=403 or denied.get('upstream_started') is not False or denied.get('completed') is not False or denied.get('reason')!='Qualification complete; C01 readiness required' or 'request_number' in denied:raise ValueError('Expected unallocated pre-readiness denial missing')


def verify_module_origins(root,names):
    for name in names:
        if name in sys.modules and Path(getattr(sys.modules[name],'__file__','')).resolve().parent!=root.resolve():raise ValueError('Mixed sealed project module: '+name)


def load(path):
    value=private_json(path);root=Path(value['root'])
    if root!=Path(path).parent or value.get('mode')!='GATED_NATIVE_TRIAL':raise ValueError('Exact complete native configuration required')
    prepared=private_json(root/'session-prepared.json')
    for name,sha in prepared['sealed'].items():
        if '..' in Path(name).parts or Path(name).is_absolute() or digest(root/name)!=sha:raise ValueError('Prepared source changed')
    # Import the exact already-audited worker implementation. Its launcher pins
    # must not be silently replaced by a newer coordinator checkout.
    project_modules=[Path(name).stem for name in prepared['sealed'] if name.endswith('.py') and '/' not in name]
    verify_module_origins(root,project_modules)
    sys.path.insert(0,str(root))
    w=importlib.import_module('worker');gui=importlib.import_module('native_gui');visible=importlib.import_module('native_visible');transport=importlib.import_module('inference_transport');preflight=importlib.import_module('preflight')
    value,root,config,record=gui.inputs(path);run=gui.run_directory(value,root)
    w.require(config['agent']['transport']=='native-visible','Legacy CLI qualification is not supported here')
    w.require(w.checked_artifact(config['qualification'])==Path(prepared['identity']['profile']['qualification']['path']),'Visible proof collector identity differs')
    w.require(not (run/'candidate-start.json').exists(),'Readiness cannot relabel a started candidate')
    w.verify_frozen(run,record)
    w.require(w.candidate_inventory(run/'workspace')==record['candidate_initial'],'Candidate changed before C01')
    identity=transport.model_runtime_identity();w.require(transport.sha(transport.encoded(identity))==config['model']['backend_identity_sha256'],'Live model identity changed')
    session=importlib.import_module('native_session');session.running(root,session.state({'run_id':value['run_id']}))
    w.require(gui.state(value)==private_json(root/'backend-receipt.json')['unit_state'],'Backend invocation/policy changed')
    attachment=visible.attachment(root)
    desktop=private_json(root/'qualification/desktop-window.json')
    w.require(len(desktop.get('windows',[]))==1 and root.name+'/'+value['run_id']+'/workspace' in desktop['windows'][0],'Independent dedicated desktop-window evidence required')
    peers={name:w.peer(channel) for name,channel in config['channels'].items()}
    ledger=private_json(root/'inference/ledger.json');proof=private_json(root/'qualification/proof.json')
    w.require(proof['fingerprint']==record['fingerprint'] and proof['status']=='MODEL_TO_MCP_SUBPROOF_NOT_FULL_C00','Matching current model proof required')
    for row in proof['evidence']:w.require(digest(root/'qualification'/row['path'])==row['sha256'],'Model proof evidence changed')
    w.require(ledger==private_json(root/'qualification/ledger.json') and ledger['requests']==3 and ledger['tool_calls']==3 and not ledger['uncertain'] and ledger['reserved_tokens']==0,'Canary ledger changed or remains uncertain')
    sid=proof['session_id'];status=visible.api(root,value,'GET','/session/status')
    w.require(isinstance(status,dict) and (sid not in status or status[sid].get('type')=='idle'),'Synthetic session is not idle')
    visible.correlated(private_json(root/'qualification/messages.json'),private_json(root/'qualification/intent.json'),private_json(root/'qualification/mcp-trace.json'),sid)
    worker=private_json(root/'backend-ready.json')['qualification']
    expected={'host_marker_denied','host_home_denied','pid_namespace','net_namespace','direct_ipv4_denied','direct_ipv6_denied','frozen_readonly','candidate_writable','train_readonly','no_git','no_inherited_secrets','namespace_set','capabilities_dropped'}
    w.require(worker['status']=='PASS' and set(worker['checks'])==expected and all(worker['checks'].values()),'Persistent worker boundary incomplete')
    controls=private_json(root/'browser-controls/receipt.json')
    w.require(controls['status']=='COORDINATOR_CONTROLS_OBSERVED_NOT_MODEL_QUALIFICATION','Actual coordinator browser controls missing')
    for row in controls['evidence']:w.require(digest(root/'browser-controls'/row['path'])==row['sha256'],'Browser controls changed')
    boundary=private_json(root/'browser-controls/boundary.json');w.require(boundary['status']=='PASS' and len(boundary['checks'])==9 and all(boundary['checks'].values()),'Browser boundary incomplete')
    controls_module=importlib.import_module('native_controls');controls_module.sandbox_processes(private_json(root/'browser-controls/processes.json'))
    effective=private_json(root/'browser-controls/effective-config.json')
    w.require(effective['browser']['contextOptions']=={'acceptDownloads':False,'serviceWorkers':'block'} and effective['browser']['launchOptions']['args']==['--disable-setuid-sandbox'],'Effective browser controls differ')
    traces=private_json(root/'browser-controls/transcript.json');denials={r['check']:r for r in traces if 'check' in r}
    w.require(set(denials)=={'private_ipv4','private_ipv6','host_file','dns','origin_confusion','redirect_query','authenticated','public_snapshot_and_local_page_fetch_controls'},'Required actual control traces missing')
    for name,row in denials.items():
        if name!='public_snapshot_and_local_page_fetch_controls':w.require(len(row['trace'])==1 and row['trace'][0]['response'].get('error',{}).get('code')==-32600,'Browser policy denial missing: '+name)
    actual_text=json.dumps(denials['public_snapshot_and_local_page_fetch_controls'])
    w.require('https://datatracker.ietf.org/doc/html/rfc2045' in actual_text and all(t in actual_text for t in ['ipv4:DENIED','ipv6:DENIED','dns:DENIED','No open tabs']),'Actual public/local controls incomplete')
    browser=private_json(root/'browser-profile.json');snapshots=importlib.import_module('public_snapshots').Snapshots(browser['snapshots']['path'],browser['snapshots']['sha256'])
    w.require(browser['mode']=='TRIAL' and controls['identity']['profile_sha256']==digest(root/'browser-profile.json'),'Controls belong to another browser profile')
    # The sealed fixed inner argv enforces --headless --isolated --sandbox.
    # Network destinations are fulfilled from the finite offline catalog, never
    # resolved/followed live; private network and empty-DNS probes confirm that
    # architectural restriction. A query rejection is not called a live redirect.
    inner=(root/'browser_inner.py').read_text()
    w.require("'--headless','--isolated','--sandbox'" in inner and "'--block-service-workers'" in inner and "'--no-sandbox' in arguments" not in inner,'Fixed browser launch policy differs')
    policy=private_json(root/'policy.json');transport.check_policy(policy)
    w.require(policy['mode']=='GATED_TRIAL' and policy['qualification_turns']==3 and policy['qualification_output_tokens']==2048,'Qualification bounds differ')
    wire=private_json(Path(prepared['identity']['profile']['wire_schema']['path']))
    w.require(wire['pins']==policy['tools'],'Actual Kilo tool-schema pins differ')
    actual_schemas=list((root/'browser').glob('mcp-*/tool-schema.json'));w.require(actual_schemas,'Actual MCP schemas missing')
    for file in actual_schemas:
        tools=private_json(file)['tools']
        w.require({t['name'] for t in tools}=={'browser_navigate','browser_snapshot','browser_tabs'},'Actual MCP tool surface changed')
        for tool in tools:w.require(transport.sha(transport.encoded(transport.schema(tool['inputSchema'])))==policy['tools']['playwright_'+tool['name']],'Actual MCP parameter schema changed')
    events=[json.loads(line) for line in (root/'inference/events.jsonl').read_text().splitlines()]
    verify_events(events,ledger)
    verify_module_origins(root,project_modules)
    return w,preflight,visible,value,root,run,config,record,{'model_identity':identity,'peers':peers,'attachment':attachment,'desktop':desktop,'session_status':status,'ledger':ledger,'worker':worker,'browser_boundary':boundary,'policy':policy,'snapshot_index_sha256':snapshots.index_sha256}


def inspect(path):
    w,preflight,visible,value,root,run,config,record,facts=load(path)
    mapping=check_map();w.require(set(mapping)==preflight.CHECKS,'Native readiness mapping omits contract checks')
    folder=root/('native-readiness-'+digest(Path(__file__))[:16])
    if folder.exists():
        index=private_json(folder/'index.json')
        w.require(index['fingerprint']==record['fingerprint'] and index['peers']==facts['peers'] and index['adapter_sha256']==digest(Path(__file__)) and set(index['checks'])==preflight.CHECKS,'Readiness index identity changed')
        for row in index['evidence'].values():w.require(digest(row['path'])==row['sha256'],'Readiness indexed evidence changed')
        return folder,index
    folder.mkdir(mode=0o700)
    w.write(folder/'live-observation.json',facts)
    paths={'adapter':Path(__file__),'live':folder/'live-observation.json','proof':root/'qualification/proof.json','model_messages':root/'qualification/messages.json','mcp_trace':root/'qualification/mcp-trace.json',
           'controls':root/'browser-controls/receipt.json','controls_trace':root/'browser-controls/transcript.json','browser_processes':root/'browser-controls/processes.json','effective_config':root/'browser-controls/effective-config.json',
           'backend':root/'backend-ready.json','browser_inner':root/'browser_inner.py','browser_route':root/'browser_route.cjs','snapshots':root/'public_snapshots.py','browser_broker':root/'native_browser.py',
           'inference':root/'inference_transport.py','inference_events':root/'inference/events.jsonl','run':run/'run.json','policy':root/'policy.json','toolchain':root/'toolchain.json'}
    capture={name:p.read_text() for name,p in paths.items()}
    w.require(sum(len(text.encode()) for text in capture.values())<4*1024*1024,'Readiness capture budget exceeded')
    index={'schema_version':1,'status':'AWAITING_INDEPENDENT_REVIEW_NOT_READY','fingerprint':record['fingerprint'],'run_id':value['run_id'],'peers':facts['peers'],
           'adapter_sha256':digest(Path(__file__)),'preflight_sha256':digest(root/'preflight.py'),'model':config['model'],'model_runtime_identity_sha256':config['model']['backend_identity_sha256'],
           'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'required_checks':sorted(preflight.CHECKS),'checks':{name:{'basis':row[0],'evidence':row[1],'meaning_and_limit':row[2]} for name,row in mapping.items()},'evidence':{name:{'path':str(p),'sha256':digest(p)} for name,p in paths.items()},
           'captured_evidence':capture,
           'limits':['Headless/isolated launch bound to the exact executed inner source and separate per-connection namespace; not a new process-command observation.',
                     'Offline exact catalog and disconnected namespace prevent DNS rebinding/private redirects by construction; query-denial is not a live redirect/rebinding exercise.',
                     'SW/download blocking is effective configuration evidence; no successful SW-registration attempt or malicious download execution claimed.',
                     'No C01, candidate tests, hidden Gold/reference accuracy or other seeds are implied.']}
    w.write(folder/'index.json',index);return folder,index


def immutable_json(w,path,value):
    if path.exists():
        private_json(path);w.require(path.read_bytes()==w.encoded(value),'Conflicting partial readiness evidence; retained')
        return
    w.write(path,value)


def publish(w,root,folder,run,receipt,wrapper):
    # The inference gate is the last publication. Every preceding receipt is
    # immutable and recoverable after interruption by exact-byte verification.
    immutable_json(w,folder/'ready.json',receipt)
    immutable_json(w,run/'readiness.json',receipt)
    immutable_json(w,root/'inference/ready.json',wrapper)


def resumed_receipt(w,old,identity,expected):
    w.require(old.get('identity')==identity,'Promotion inputs changed; old intent retained')
    receipt=old['receipt'];comparison=dict(expected)
    comparison['created_unix']=receipt.get('created_unix')
    w.require(type(comparison['created_unix']) in (int,float) and w.encoded(comparison)==w.encoded(receipt),'Promotion receipt binding changed; retained')
    return receipt


def promote(path,review_path):
    folder,index=inspect(path);review=private_json(review_path)
    w,preflight,visible,value,root,run,config,record,facts=load(path)
    w.require(Path(review_path).is_absolute() and Path(review_path).is_relative_to(root) and 'workspace' not in Path(review_path).relative_to(root).parts,'Review must remain in this private coordinator run')
    w.require(review.get('schema_version')==1 and review.get('decision')=='C00_ACCEPTED' and review.get('independent_reviewer') and review.get('fingerprint')==record['fingerprint']
              and review.get('evidence_index_sha256')==digest(folder/'index.json') and review.get('findings')==[] and review.get('limitations_acknowledged')==index['limits'],'Exact independent current C00 acceptance required')
    w.require(facts['peers']==index['peers'] and index['adapter_sha256']==digest(Path(__file__)),'Runtime/adapter changed after review')
    gate=root/'inference/ready.json'
    checked={name:{'passed':True,'path':str(folder/'index.json'),'sha256':digest(folder/'index.json')} for name in preflight.CHECKS}
    now=time.time();receipt={'status':'READY','run_id':value['run_id'],'fingerprint':record['fingerprint'],'policy_sha256':w.sha(w.encoded(facts['policy'])),'created_unix':now,
        'preflight_sha256':digest(root/'preflight.py'),'boot_id':index['boot_id'],'model':config['model'],'model_runtime_identity_sha256':config['model']['backend_identity_sha256'],
        'checks':checked,'peers':facts['peers'],'canary':index['evidence']['proof'],'isolation':index['evidence']['backend'],'audit':{'path':str(review_path),'sha256':digest(review_path)}}
    # Gateway policy canonicalization is compact, unlike worker's pretty JSON.
    transport=importlib.import_module('inference_transport');receipt['policy_sha256']=transport.sha(transport.encoded(facts['policy']))
    identity={'index_sha256':digest(folder/'index.json'),'review_sha256':digest(review_path),'fingerprint':record['fingerprint'],'adapter_sha256':digest(Path(__file__))}
    intent=folder/'promotion-intent.json'
    reused=intent.exists()
    if reused:
        receipt=resumed_receipt(w,private_json(intent),identity,receipt)
    else:
        w.require(not gate.exists(),'Gate without promotion intent retained; no assumed success')
        w.write(intent,{'identity':identity,'receipt':receipt})
    preflight.verify_ready(receipt,record,run,config)
    wrapper={'decision':'C01_AUTHORIZED','run_id':value['run_id'],'policy_sha256':receipt['policy_sha256'],'created_unix':receipt['created_unix'],'boot_id':index['boot_id'],'receipt':{'path':str(folder/'ready.json'),'sha256':hashlib.sha256(w.encoded(receipt)).hexdigest()}}
    publish(w,root,folder,run,receipt,wrapper)
    transport.coding_gate(root/'inference',facts['policy'])
    return {'status':'READY_REUSED' if reused else 'READY','receipt':str(folder/'ready.json'),'candidate_started':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['inspect','promote']);parser.add_argument('--configuration',type=Path,required=True);parser.add_argument('--review',type=Path);args=parser.parse_args()
    try:
        if args.action=='inspect':folder,index=inspect(args.configuration);print(json.dumps({'status':index['status'],'index':str(folder/'index.json'),'sha256':digest(folder/'index.json')}))
        else:
            if args.review is None:raise ValueError('--review is required for promotion')
            print(json.dumps(promote(args.configuration,args.review)))
        return 0
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
