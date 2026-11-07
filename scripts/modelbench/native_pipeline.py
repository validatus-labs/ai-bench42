"""Pinned native-visible pipeline continuation; never call the legacy CLI worker.

A prepared per-seed session and its independent C00 gate remain mandatory.
Controller start is once-only; repeats inspect the same candidate. No preflight,
model generation, installation or readiness approval is fabricated here.
"""
import json
import contextlib
from pathlib import Path
import subprocess
import sys
import os

from . import common as c


def validate_reference(config,seed):
    cfg=config['coding'];native=cfg['native'];spec=native['sessions'].get(str(seed))
    c.require(spec is not None,'No independently prepared native session for seed '+str(seed))
    c.require({'run_id','configuration','profile'}<=set(spec)<= {'run_id','configuration','profile','resume_adapter'},'Unknown native session fields')
    for item in [native['controller'],spec['configuration'],spec['profile']]:c.pin(item)
    gui=c.read(c.pin(spec['configuration']));profile=c.read(c.pin(spec['profile']));record=c.read(c.pin(gui['record']));toolchain=c.read(c.pin(gui['toolchain']))
    identity=record['identity'];model=config['model']
    c.require(gui['mode']=='GATED_NATIVE_TRIAL' and gui['run_id']==spec['run_id']==profile['run_id']==identity['run_id'],'Native session identity mismatch')
    root=c.safe(gui['root'])
    c.require(root==c.safe(profile['runtime_root'])/'build'/profile['run_id'] and gui['run_directory']==profile['run_id'],'Native session runtime path differs')
    prepared=c.safe(root/'session-prepared.json');st=prepared.stat()
    c.require(st.st_uid==os.getuid() and st.st_nlink==1 and not st.st_mode&0o077,'Private prepared native receipt required')
    c.require(c.read(prepared)['identity']['profile']==profile,'Pinned profile differs from actual prepared native worker')
    c.require(profile['seed']==identity['seed']==seed and identity['source_sha']==cfg['source_sha'] and identity['package_sha256']==cfg['package']['sha256'] and identity['train_sha256']==cfg['train_bundle']['sha256'] and identity['rights_record_sha256']==cfg['rights_record']['sha256'],'Native assignment/TRAIN provenance mismatch')
    c.require(profile['approve_worker_disclosure'] is True and cfg['approve_worker_disclosure'] is True,'TRAIN worker disclosure missing')
    c.require(toolchain['agent']['transport']=='native-visible' and all(toolchain['model'][k]==model[k] for k in ['id','revision','context_tokens']),'Native model/transport differs')
    c.require((record['execution_wall_seconds'] is None)==cfg.get('elapsed_only',True),'Native elapsed timing differs')
    reference={'schema_version':1,'run_id':spec['run_id'],'seed':seed,'controller':native['controller'],'configuration':spec['configuration'],'profile':spec['profile'],'worker_run':str(Path(gui['root'])/gui['run_directory']),'record':gui['record']}
    if spec.get('resume_adapter') is not None:
        adapter=spec['resume_adapter'];c.pin(adapter['controller']);configuration=c.read(c.pin(adapter['profile']))
        c.require(configuration['original']==native['controller'] and configuration['configuration']==spec['configuration'] and configuration['session_profile']==spec['profile'] and configuration['run_id']==spec['run_id'] and configuration['fingerprint']==record['fingerprint'],'Capture-only adapter belongs to another candidate')
        reference.update(capture_adapter=adapter['controller'],capture_profile=adapter['profile'])
    return reference


@contextlib.contextmanager
def workload_lease(config,target,phase):
    # The native session holds this exact lock through worker/channel teardown.
    # Ordinary inference adapters may never run concurrently with that worker.
    if phase.startswith('coding-') and config.get('coding',{}).get('native') is not None:
        validate_reference(config,int(phase.rsplit('-',1)[1]))
        yield;return
    runtime=Path(target['runtime'])
    native=config.get('coding',{}).get('native')
    if native is not None:
        # The adopted host registry may live in a different runtime directory
        # from the independently sealed worker. Use its actual pinned owner.
        roots=set()
        for seed in native['sessions']:
            reference=validate_reference(config,int(seed))
            roots.add(c.safe(c.read(c.pin(reference['profile']))['runtime_root']))
        c.require(len(roots)==1,'Native sessions disagree on the shared workload runtime')
        runtime=roots.pop()
    lock=c.private_directory(runtime/'tools/benchmark')/'benchmark.lock'
    with contextlib.ExitStack() as stack:
        try:stack.enter_context(c.locked(lock))
        except BlockingIOError:raise c.Blocked('Another native/model workload owns the exclusive benchmark lease') from None
        yield


def invoke(reference,action,folder):
    if action!='start' and 'capture_adapter' in reference:
        argv=[sys.executable,'-B',str(c.pin(reference['capture_adapter'])),action,'--profile',str(c.pin(reference['capture_profile']))]
    else:
        argv=[sys.executable,'-B',str(c.pin(reference['controller'])),action,'--configuration',str(c.pin(reference['configuration']))]
        if action=='finish':argv+=['--session-profile',str(c.pin(reference['profile']))]
    result=c.execute(argv,folder,600 if action=='finish' else 120)
    c.require(result['exit_code']==0,'Native controller refused '+action+'; preserve evidence, no replay')
    raw=(folder/'output.log').read_bytes()
    return json.loads(raw)


def development_review(run,frozen,observed):
    file=c.safe(run/'independent-development-review.json')
    if not file.exists():return {'status':'DEVELOPMENT_REVIEW_REQUIRED','visible':observed['visible'],'review':None,'external_evidence':[]}
    st=file.stat();c.require(not file.is_symlink() and st.st_uid==os.getuid() and st.st_nlink==1 and not st.st_mode&0o077,'Private independent development review required')
    review=c.read(file)
    c.require(review.get('schema_version')==1 and review.get('independent_reviewer') and review.get('fingerprint')==observed['fingerprint'] and review.get('candidate_tree_sha256')==frozen['candidate_tree_sha256'] and review.get('archive_sha256')==frozen['archive_sha256'] and review.get('worker_report_sha256')==observed['worker_report'].get('sha256'),'Independent candidate review identity differs')
    visible=observed['visible'];evidence=[{'path':str(file),'sha256':c.digest(file)}]
    if review.get('corrected_assessment'):
        item=review['corrected_assessment'];path=c.pin(item)
        c.require(path.is_relative_to(run) and 'workspace' not in path.relative_to(run).parts,'Corrected assessment must stay outside candidate')
        result=c.read(path);identity=result['identity']
        c.require(identity['fingerprint']==observed['fingerprint'] and identity['candidate_tree_sha256']==frozen['candidate_tree_sha256'] and identity['archive_sha256']==frozen['archive_sha256'] and identity['adapter_sha256']==c.digest(Path(__file__).resolve().parents[2]/'tools/native_assessment.py'),'Corrected assessment source/candidate differs')
        c.require(set(result['evidence'])=={'namespace.json','result.json','tests.log'},'Corrected assessment evidence set differs')
        for name,row in result['evidence'].items():
            c.require(row['path']==name,'Corrected assessment evidence path differs');child={'path':str(path.parent/name),'sha256':row['sha256']};c.pin(child);evidence.append(child)
        c.require(c.read(path.parent/'result.json')==result['assessment'] and result['status']==result['assessment']['status'] and (result['exit_code']==0)==(result['status']=='PASS'),'Corrected assessment result mismatch')
        visible=result['assessment'];evidence.append(item)
    decision=review.get('decision')
    if decision=='CANDIDATE_DEVELOPMENT_ACCEPTED':
        c.require(review.get('findings')==[] and review.get('worker_train_cases_verified')==12 and review.get('c01_c07_complete') is True and visible['status']=='PASS' and observed['worker_report']['status']=='PRESENT_UNREVIEWED','Incomplete candidate development acceptance')
        state='PASS'
    else:
        c.require(decision=='CHANGES_REQUIRED' and isinstance(review.get('findings'),list) and review['findings'],'Unrecognized independent development review')
        state='FAILED'
    return {'status':state,'visible':visible,'review':review,'external_evidence':evidence}


def coding(config,folder,seed):
    reference=validate_reference(config,seed);c.save(folder/'native-reference.json',reference)
    c.mark_effect('Once-only native controller start; repeated start cannot replay a prompt')
    started=invoke(reference,'start',folder/'native-start')
    c.require(started['status'] in {'CANDIDATE_RUNNING','EXISTING_CANDIDATE_NOT_REPLAYED'},'Unexpected native start state')
    observed=invoke(reference,'status',folder/'native-status')
    if observed['status']=='QUIESCENT_NOT_ASSESSED':observed=invoke(reference,'finish',folder/'native-finish')
    if observed['status']!='CANDIDATE_ASSESSED_NOT_HELDOUT_PASS':
        return {'status':'AWAITING_NATIVE_CANDIDATE','seed':seed,'native_reference':reference,'actual_status':observed,'scope':'Same persistent visible candidate; repeat resumes observation, never replay generation'}
    run=Path(reference['worker_run']);freeze=c.read(run/'frozen-candidate.json');reviewed=development_review(run,freeze,observed);visible=reviewed['visible'];report=observed['worker_report']
    # A measured model failure is a terminal outcome, not permission to replay
    # the candidate or prevent the other independent seeds from being measured.
    return {'status':'CANDIDATE_REJECTED' if reviewed['status']=='FAILED' else reviewed['status'],
            'candidate_verdict':reviewed['status'],'seed':seed,
            'scope':'Native candidate development and independently invoked visible tests only; C07 report content and hidden/Gold remain independently unqualified',
            'worker_run':str(run),'candidate_tree_sha256':freeze['candidate_tree_sha256'],'archive_sha256':freeze['archive_sha256'],'archive':str(run/'frozen-candidate.tar'),
            'suites':visible.get('suites',[]),'worker_report':report,'development_review':reviewed['review'],'usage':observed['ledger'],'native_reference':reference,
            'external_evidence':reviewed['external_evidence']+[{'path':str(run/'candidate-result.json'),'sha256':c.digest(run/'candidate-result.json')},{'path':str(run/'frozen-candidate.json'),'sha256':c.digest(run/'frozen-candidate.json')}],
            'metrics':{'coding_seconds':{'value':observed['elapsed_seconds'],'unit':'s'}}}
