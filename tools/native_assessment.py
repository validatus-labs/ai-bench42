#!/usr/bin/env python3
"""Correct only the isolated visible-assessment import path; never change candidate.

native_assessment.py
|-- bind     exact original prepared worker + frozen archive + prior result
|-- manifest identical read-only/offline namespace; add /workspace import root
`-- assess   unchanged supplied/candidate tests, private logs, immutable reuse

No inference socket, new model request, candidate edits or hidden evaluation.
The historical import-failure assessment remains unchanged.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

BOOTSTRAP='import sys,runpy;sys.path.insert(0,"/workspace");runpy.run_path("/opt/modelbench/worker_inner.py",run_name="__main__")'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assess(configuration,controller,controller_sha256,review_path,output):
    if digest(controller)!=controller_sha256:raise ValueError('Original controller pin changed')
    spec=importlib.util.spec_from_file_location('native_candidate_assessment_original',controller);original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    w,gui,visible,session,transport,value,root,run,record,config=original.bind(configuration,online=False)
    review=original.private(review_path)
    w.require(review.get('decision')=='ISOLATED_ASSESSMENT_IMPORT_FIX_ACCEPTED' and review.get('independent_reviewer') and review.get('findings')==[] and review.get('adapter_sha256')==digest(Path(__file__)) and review.get('fingerprint')==record['fingerprint'] and review.get('scope')=='READ_ONLY_VISIBLE_TESTS_IMPORT_ROOT_ONLY','Exact independent assessment-only review required')
    w.require(gui.state(value).get('ActiveState') in {'inactive','failed'} and session.state({'run_id':value['run_id']}).get('ActiveState') in {'inactive','failed'},'Candidate backend/coordinator remains active')
    frozen=w.freeze_candidate(run,record);prior=original.private(run/'candidate-result.json');ledger=original.private(root/'inference/ledger.json')
    w.require(ledger['reserved_tokens']==0 and ledger['uncertain'] is False,'Unsettled model accounting')
    folder=w.safe(output);w.require(folder.is_relative_to(run) and 'workspace' not in folder.relative_to(run).parts,'Assessment evidence must stay outside candidate')
    folder.mkdir(mode=0o700,exist_ok=True)
    identity={'adapter_sha256':digest(Path(__file__)),'original_controller_sha256':controller_sha256,'fingerprint':record['fingerprint'],'archive_sha256':frozen['archive_sha256'],'candidate_tree_sha256':frozen['candidate_tree_sha256'],'prior_result_sha256':digest(run/'candidate-result.json'),'review_sha256':digest(review_path),'ledger':ledger,'bootstrap':BOOTSTRAP}
    receipt=folder/'receipt.json'
    if receipt.exists():
        result=original.private(receipt);w.require(result['identity']==identity,'Assessment inputs changed')
        for item in result['evidence'].values():w.require(digest(folder/item['path'])==item['sha256'],'Assessment evidence changed')
        w.require(w.freeze_candidate(run,record)==frozen,'Frozen source changed')
        return dict(result,reused=True)
    w.require(not (folder/'intent.json').exists(),'Partial assessment retained; inspect before a new output')
    original.atomic_json(w,folder/'intent.json',identity)
    argv=w.command(run,record,config,'visible');old_manifest=Path(argv[argv.index('--manifest')+1]);manifest=original.private(old_manifest)
    manifest['argv']=['/usr/bin/python3','-B','-c',BOOTSTRAP,'visible']
    # Preserve every existing mount, namespace, uid, limit and environment byte.
    original_manifest=original.private(old_manifest);comparison=dict(manifest);comparison['argv']=original_manifest['argv'];w.require(comparison==original_manifest,'Unexpected assessment namespace change')
    w.require(not any(row.get('writable') for row in manifest['mounts']) and not any(row['target'] in {'/run/inference.sock','/run/browser.sock'} for row in manifest['mounts']),'Assessment must have no writable mounts or inference/browser channels')
    original.atomic_json(w,folder/'namespace.json',manifest);argv[argv.index('--manifest')+1]=str(folder/'namespace.json');argv[argv.index('--sha256')+1]=digest(folder/'namespace.json')
    started=time.monotonic();code=w.execute(argv,config,300,folder/'result.json',stderr_destination=folder/'tests.log')
    raw=original.private(folder/'result.json');w.require(raw.get('schema_version')==1 and raw.get('status') in {'PASS','FAILED'} and (code==0)==(raw['status']=='PASS'),'Assessment status/exit mismatch')
    w.require(w.freeze_candidate(run,record)==frozen and original.private(root/'inference/ledger.json')==ledger,'Assessment changed candidate/accounting')
    result={'schema_version':1,'status':raw['status'],'scope':'Corrected isolated visible assessment only; no hidden/Gold/C07 acceptance implied','identity':identity,'assessment':raw,'exit_code':code,'elapsed_seconds':time.monotonic()-started,'evidence':{name:{'path':name,'sha256':digest(folder/name)} for name in ['namespace.json','result.json','tests.log']},'reused':False}
    original.atomic_json(w,receipt,result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--configuration',type=Path,required=True);parser.add_argument('--controller',type=Path,required=True);parser.add_argument('--controller-sha256',required=True);parser.add_argument('--review',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    try:
        result=assess(args.configuration,args.controller,args.controller_sha256,args.review,args.output)
        print(json.dumps({'status':result['status'],'reused':result['reused'],'assessment':result['assessment'],'scope':result['scope']}));return 0 if result['status']=='PASS' else 1
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
