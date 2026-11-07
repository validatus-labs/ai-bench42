#!/usr/bin/env python3
"""Independent held-out scorer: explicit qualified gates, private data, offline execution.

heldout-adapter.py
|-- gate()     independent review + exact source/reference/Gold/TRAIN pins
|-- extract()  bounded regular-file candidate archive; verify frozen tree hash
`-- evaluate  read-only network-none containers -> aggregate metrics and errors

Missing human Gold/reference/isolation qualification stops before candidate code.
No labels, reference tree, credentials or Docker socket enter candidate containers.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tarfile
from modelbench import common as c,adapters,heldout_core as core


def gate(definition,request):
    c.require(definition['schema_version']==1 and definition['benchmark']=='melusense','Wrong evaluator definition')
    c.require(definition.get('qualification_status')=='QUALIFIED_HELD_OUT','Independent held-out qualification is missing')
    review=c.read(c.pin(definition['qualification_report']))
    c.require(review.get('status')=='PASS' and review.get('independent') is True and review.get('source_sha')==request['source_sha'],'Independent qualification/source differs')
    c.require(review.get('owner') and review.get('auditor') and review['owner']!=review['auditor'],'Separate named owner and auditor required')
    for field in ['owner_approval','rights_review','human_gold_review','thread_split_review','reference_review','worker_isolation_review']:
        c.require(review.get(field) is True,'Missing held-out gate: '+field)
        c.pin(review['evidence'][field])
    for name in ['gold','reference_manifest','train_bundle']:
        path=c.pin(definition[name]);c.require(not path.stat().st_mode&0o077,'Evaluator data must be private')
        c.require(review.get(name+'_sha256')==c.digest(path),'Review/data binding differs: '+name)
    c.require(definition['train_bundle']==request['train_bundle'],'Worker/evaluator TRAIN bundle differs')
    for item in definition['artifacts']:c.pin(item)
    c.require(re.fullmatch('[a-f0-9]{40}',str(review.get('reference_sha'))) and review['reference_sha']!=request['source_sha'],'Independent reference freeze required')
    sandbox=definition['sandbox']
    c.require(re.fullmatch(r'python@sha256:[a-f0-9]{64}',sandbox['image']) and sandbox['platform']=='linux/arm64','Pin native evaluator image')
    c.require(sandbox['memory']=='2g' and sandbox['cpus']=='2' and sandbox['pids_limit']==128,'Retain reviewed resource bounds')
    return review


def extract(spec,folder):
    archive=c.pin(spec);c.require(not folder.exists(),'Retain previous extracted candidate')
    with tarfile.open(archive) as stream:
        members=stream.getmembers();names=[m.name for m in members]
        c.require(len(names)==len(set(names)) and len(names)<=500,'Candidate archive count/duplicates')
        c.require(sum(m.size for m in members)<=64*1024*1024,'Candidate archive too large')
        for m in members:
            p=Path(m.name);c.require(m.isfile() and not p.is_absolute() and '..' not in p.parts and m.size<=2*1024*1024 and not any(x in ('.git','__pycache__','.venv') for x in p.parts),'Unsafe candidate archive')
        c.private_directory(folder)
        for m in members:
            p=folder/m.name;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            with p.open('xb') as out:os.fchmod(out.fileno(),0o600);out.write(stream.extractfile(m).read())
    return core.tree(folder)


def evaluate(definition,request,folder):
    review=gate(definition,request)
    # Validate the entire held-out corpus before starting any candidate container.
    gold=c.pin(definition['gold']);count=sum(1 for _ in core.gold_records(gold));c.require(count>0,'No human-reviewed Gold cases')
    reference_manifest=c.read(c.pin(definition['reference_manifest']));reference=c.safe(Path(definition['reference_manifest']['path']).parent/'export')
    c.require(reference_manifest['commit']==review['reference_sha'] and core.tree(reference)==reference_manifest['files'],'Reference bytes/commit differ')
    candidate=folder/'candidate';files=extract(request['candidate'],candidate)
    c.require(c.fingerprint(files)==request['candidate']['tree_sha256'],'Frozen candidate tree differs')
    config={'sandbox':definition['sandbox']}
    totals={name:{kind:{'tp':0,'fp':0,'fn':0} for kind in ['reply','forward','signature','footer','removal']} for name in ['candidate','reference']}
    errors={'candidate':0,'reference':0};loss={'candidate':0,'reference':0}
    def execute(root,payload):
        code,raw,_=core.container_python(config,root,core.CANDIDATE,json.dumps(payload),timeout=120)
        c.require(code==0,'Parser runtime failure');result=json.loads(raw)
        c.require(result.get('authorized_removals')==[],'Frozen no-removal invariant violated')
        return result
    for record in core.gold_records(gold):
        key='text' if record['source_kind']=='text' else 'eml_base64';payload={k:record[k] for k in ['source_kind','locale',key]}
        for name,root in [('candidate',candidate),('reference',reference)]:
            try:scored=core.score_case(record,execute(root,payload))
            except (OSError,ValueError,RuntimeError,KeyError,TypeError,subprocess.TimeoutExpired):
                errors[name]+=1;scored={kind:{'tp':0,'fp':0,'fn':len(core.positions([s for s in record['candidates'] if s['kind']==kind],record['text_length']))} for kind in ['reply','forward','signature','footer']}
                scored['removal']={'tp':0,'fp':0,'fn':len(core.positions(record['authorized_removals'],record['text_length']))};scored['current_body_loss_characters']=0
            for kind in totals[name]:
                for metric in totals[name][kind]:totals[name][kind][metric]+=scored[kind][metric]
            loss[name]+=scored['current_body_loss_characters']
    train=c.pin(definition['train_bundle']);train_rows=[json.loads(line) for line in train.read_text().splitlines()]
    c.require(len(train_rows)==request['required_train_examples']==12,'Require all12 matching TRAIN examples')
    train_errors=0
    for record in train_rows:
        try:
            result=execute(candidate,{'source_kind':'text','locale':'auto','text':record['text']})
            c.require(result['text']==record['text'],'TRAIN original text changed')
        except (OSError,ValueError,RuntimeError,KeyError,TypeError,subprocess.TimeoutExpired):train_errors+=1
    c.require(core.tree(candidate)==files and core.tree(reference)==reference_manifest['files'],'Candidate/reference changed during scoring')
    metrics={}
    for name,counts in totals.items():
        for kind,row in counts.items():
            tp,fp,fn=row['tp'],row['fp'],row['fn']
            for key,value in row.items():metrics[name+'/'+kind+'/'+key]=adapters.metric(value,'characters')
            # Undefined empty denominators stay absent, never fabricate perfect scores.
            for key,num,den in [('precision',tp,tp+fp),('recall',tp,tp+fn),('f1',2*tp,2*tp+fp+fn)]:
                if den:metrics[name+'/'+kind+'/'+key]=adapters.metric(num/den,'fraction')
        metrics[name+'/runtime_errors']=adapters.metric(errors[name],'cases')
        metrics[name+'/observed_current_body_loss']=adapters.metric(loss[name],'characters')
    result={key:request[key] for key in ['schema_version','request_sha256','adapter_version','data_manifest_sha256','benchmark','model','seed']}
    result.update(status='PASS',scope='qualified-held-out',evaluated_samples=count,metrics=metrics,candidate_tree_sha256=request['candidate']['tree_sha256'],train_examples_checked=12,train_bundle_sha256=c.digest(train),train_runtime_errors=train_errors,loss_unknown_on_error={name:bool(value) for name,value in errors.items()},note='Aggregate-only character-span evaluation; runtime errors retained in denominators; TRAIN integrity checks are not held-out quality')
    for item in definition['artifacts']:c.pin(item)
    gate(definition,request)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--definition',required=True,type=Path);p.add_argument('--request',required=True,type=Path);p.add_argument('--result',required=True,type=Path);a=p.parse_args()
    try:
        definition=c.read(a.definition);request=c.read(a.request);bound=dict(request);checksum=bound.pop('request_sha256')
        c.require(c.fingerprint(bound)==checksum and c.digest(a.definition)==request['definition_sha256'],'Evaluator inputs changed')
        c.require(not a.result.exists(),'Retain previous evaluator result')
        c.save(a.result,evaluate(definition,request,c.safe(a.result).parent));return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,tarfile.TarError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2
if __name__=='__main__':
    sys.exit(main())
