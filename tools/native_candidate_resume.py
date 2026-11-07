#!/usr/bin/env python3
"""Reviewed observation/finish adapter for an already submitted native candidate.

native_candidate_resume.py
|-- bind    exact original controller + current capture helper + independent review
|-- status  original once-only candidate identity, no new model request
`-- watch/finish  replace only transcript capture; preserve source/session/budget

Never exposes start, resets a ledger, changes a sealed worker or edits an old
controller. Both source versions and this narrow adapter remain separately pinned.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time


def private(path):
    p=Path(path)
    if any(x.is_symlink() for x in (p,*p.parents)):raise ValueError('Coordinator symlink denied')
    s=p.stat()
    if not p.is_file() or s.st_uid!=os.getuid() or s.st_nlink!=1 or s.st_mode&0o077 or s.st_size>1024*1024:raise ValueError('Private bounded coordinator input required')
    return json.loads(p.read_bytes())


def pin(item):
    p=Path(item['path'])
    if not p.is_absolute() or any(x.is_symlink() for x in (p,*p.parents)) or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Pinned adapter input changed')
    return p


def load(path):
    profile=private(path)
    fields={'schema_version','run_id','fingerprint','original','updated','configuration','session_profile','review','adapter_sha256'}
    if set(profile) not in (fields,fields|{'previous_registration'}) or profile['schema_version']!=1:raise ValueError('Exact adapter profile required')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=profile['adapter_sha256']:raise ValueError('Adapter changed')
    for key in ['original','updated','configuration','session_profile','review']:pin(profile[key])
    review=private(profile['review']['path'])
    expected={'decision':'COORDINATOR_CAPTURE_PATCH_ACCEPTED','run_id':profile['run_id'],'fingerprint':profile['fingerprint'],'original_sha256':profile['original']['sha256'],'updated_sha256':profile['updated']['sha256'],'adapter_sha256':profile['adapter_sha256'],'scope':'OBSERVE_AND_FINISH_ONLY'}
    if 'previous_registration' in profile:
        pin(profile['previous_registration'])
        expected.update(previous_registration_sha256=profile['previous_registration']['sha256'],session_profile_sha256=profile['session_profile']['sha256'])
    if not review.get('independent_reviewer') or review.get('findings')!=[] or any(review.get(k)!=v for k,v in expected.items()):raise ValueError('Exact independent capture-only review required')
    modules=[]
    for key in ['original','updated']:
        spec=importlib.util.spec_from_file_location('native_candidate_'+key,pin(profile[key]));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);modules.append(module)
    original,updated=modules
    # Only the external transcript capture is patched. The original controller
    # continues enforcing its original launch/source identity and finish guards.
    original.capture_messages=updated.capture_messages
    w,gui,visible,session,transport,value,root,run,record,config=original.bind(pin(profile['configuration']),online=False)
    if record['fingerprint']!=profile['fingerprint'] or value['run_id']!=profile['run_id'] or not (run/'candidate-start.json').exists():raise ValueError('Only the exact already started candidate is supported')
    launch=private(run/'candidate-start.json')
    if launch['controller_sha256']!=profile['original']['sha256'] or launch['fingerprint']!=profile['fingerprint']:raise ValueError('Original candidate identity differs')
    actual_profile=private(pin(profile['session_profile']))
    prepared=private(root/'session-prepared.json')
    if actual_profile!=prepared['identity']['profile'] or actual_profile['run_id']!=value['run_id'] or actual_profile['seed']!=record['identity']['seed']:raise ValueError('Session cleanup profile belongs to another candidate')
    registration={'profile_path':str(Path(path).absolute()),'profile_sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'independent_review':profile['review'],'scope':'OBSERVE_AND_FINISH_ONLY'}
    destination=run/'coordinator-capture-adapter.json'
    if 'previous_registration' in profile:
        if pin(profile['previous_registration'])!=destination:raise ValueError('Only exact prior capture registration may be superseded')
        predecessor=private(destination);old_profile=private(predecessor['profile_path'])
        if hashlib.sha256(Path(predecessor['profile_path']).read_bytes()).hexdigest()!=predecessor['profile_sha256'] or old_profile['run_id']!=profile['run_id'] or old_profile['fingerprint']!=profile['fingerprint'] or old_profile['original']!=profile['original'] or old_profile['configuration']!=profile['configuration']:raise ValueError('Prior capture identity changed')
        registration['supersedes']=profile['previous_registration']
        folder=run/'coordinator-capture-adapters';folder.mkdir(mode=0o700,exist_ok=True)
        destination=folder/(registration['profile_sha256']+'.json')
    original.atomic_json(w,destination,registration)
    return profile,original


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['status','finish','watch']);parser.add_argument('--profile',type=Path,required=True);args=parser.parse_args()
    try:
        profile,original=load(args.profile);configuration=pin(profile['configuration']);session_profile=pin(profile['session_profile'])
        if args.action=='finish':result=original.finish(configuration,session_profile)
        else:
            while True:
                result=original.status(configuration)
                if args.action=='status':break
                if result['status']=='QUIESCENT_NOT_ASSESSED':result=original.finish(configuration,session_profile);break
                if result['status'] not in {'RUNNING','STARTING_NO_REPLAY'}:break
                time.sleep(30)
        print(json.dumps(result));return 0
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
