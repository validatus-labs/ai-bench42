#!/usr/bin/env python3
"""Seal an actual private experiment profile; never invent rights or readiness.

configure-experiment.py
|-- --check       validate existing artifacts, runtimes and TRAIN provenance
`-- --write       publish/reuse exact benchmark.json + readiness.json atomically

Normal coordinator only. No installation, inference, coding or hosted requests.
Example: python3 -B scripts/configure-experiment.py --profile /private/profile.json --output /private/config --write
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts/deploy'));sys.path.insert(0,str(ROOT/'tools'))
from modelbench import common as c,pipeline
import greenfield


def pin_existing(value):
    """Fill missing hashes from real files; a supplied different hash is an error."""
    if isinstance(value,dict):
        if value.get('enabled') is False: return copy.deepcopy(value)
        if set(value)=={'path','sha256'} and isinstance(value['path'],str):
            path=c.safe(value['path']);c.require(path.is_file(),'Configured artifact is absent: '+str(path))
            observed=c.digest(path)
            c.require(value['sha256'] in (None,observed),'Configured artifact hash differs: '+str(path))
            return {'path':str(path),'sha256':observed}
        return {key:pin_existing(child) for key,child in value.items()}
    if isinstance(value,list):return [pin_existing(x) for x in value]
    return value


def runtime_check(spec):
    python=c.pin(spec['python']);lock=c.pin(spec['requirements_lock'])
    expected={}
    for line in lock.read_text().splitlines():
        if not line.strip() or line.startswith('#'):continue
        match=re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s@/]+)',line)
        c.require(match,'Expected a full name==version runtime lock')
        key=re.sub(r'[-_.]+','-',match[1]).lower();c.require(key not in expected,'Duplicate runtime-lock distribution');expected[key]=match[2]
    query='import importlib.metadata as m,json;print(json.dumps([[d.metadata["Name"],d.version,bool(json.loads(d.read_text("direct_url.json") or "{}").get("dir_info",{}).get("editable"))] for d in m.distributions()]))'
    env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
    result=subprocess.run([str(python),'-I','-B','-c',query],capture_output=True,text=True,timeout=60,env=env)
    c.require(result.returncode==0 and len(result.stdout)<=1024*1024,'Runtime metadata check failed')
    observed=json.loads(result.stdout);c.require(all(not row[2] for row in observed),'Editable runtime is unsupported')
    actual={re.sub(r'[-_.]+','-',row[0]).lower():row[1] for row in observed}
    c.require(len(actual)==len(observed) and actual==expected,'Actual runtime differs from full distribution lock')
    name=re.sub(r'[-_.]+','-',spec['distribution']).lower();c.require(actual.get(name)==spec['version'],'Benchmark distribution version differs')
    return {'status':'PASS','version':actual[name],'distributions':len(actual),'python_sha256':c.digest(python),'lock_sha256':c.digest(lock)}


def source_contract(config):
    path=c.pin(config['coding']['package']);seeds=None;budget_sha=None
    record=c.read(c.pin(config['coding']['source_record']))
    c.require(record['approved_commit']==config['coding']['source_sha'] and record['archive_sha256']==c.digest(path),'Approved source record/archive/commit differ')
    with tarfile.open(path) as stream:
        names=stream.getnames();c.require(len(names)==len(set(names)),'Duplicate source archive member')
        for member in stream:
            rel=Path(member.name)
            c.require(member.isfile() and not rel.is_absolute() and '..' not in rel.parts and member.size<=2*1024*1024,'Unsafe source archive')
            c.require(member.name in record['files'] and hashlib.sha256(stream.extractfile(member).read()).hexdigest()==record['files'][member.name]['sha256'],'Approved source member differs')
        c.require(set(names)==set(record['files']),'Approved source file set differs')
        member=stream.getmember('config/budget.json');raw=stream.extractfile(member).read();budget=json.loads(raw)
        c.require(config['coding']['seeds']==budget['seeds'],'Coding seeds differ from approved source archive')
        c.require(config['model']['context_tokens']>=budget['context_tokens'],'Model context violates frozen task budget')
        for name in ['AGENTS.md','TASKS.md','docs/OFFLINE_AGENT_PROMPT.md']:
            c.require(name in names,'Approved source lacks required contract: '+name)
        c.require('docs/CONTRACT.md' in names or 'docs/contract.md' in names,'Approved API contract missing')
        budget_sha=hashlib.sha256(raw).hexdigest();seeds=budget['seeds']
    c.require(re.fullmatch('[a-f0-9]{40}',str(config['coding']['source_sha'])),'Pin the exact approved source SHA')
    return {'status':'PASS','package_sha256':c.digest(path),'source_sha':config['coding']['source_sha'],'budget_sha256':budget_sha,'seeds':seeds}


def train_check(config,source_manifest):
    spec=config['coding'];rights=c.pin(spec['rights_record']);bundle=c.pin(spec['train_bundle'])
    approval=c.read(rights);manifest_path=c.pin(source_manifest);manifest=c.read(manifest_path)
    c.require(approval.get('approved') is True and approval.get('worker_disclosure_approved') is True and approval.get('local_models_only') is True,'Missing explicit rights/local-worker disclosure approval')
    c.require(spec['approve_worker_disclosure'] is True,'Disclosure is not selected')
    verified=greenfield.verify_hpi(manifest_path.parent)
    c.require(approval['source_revision']==greenfield.HPI_REF and approval['usage']=='internal-train-only' and approval.get('reviewer') and approval.get('legal_basis'),'Invalid rights review scope/provenance')
    c.require(manifest['rights_record_sha256']==c.digest(rights),'TRAIN source and rights record differ')
    # Compare against the original annotated text, never normalized raw EML.
    expected=[]
    for case in sorted(greenfield.HPI_TRAIN):
        ann=json.loads((manifest_path.parent/(case+'.ann')).read_text(encoding='utf-8-sig'))
        expected.append({'case_id':case,'text':ann['text'],'labels':[{'type':z['type'],'start':z['start'],'end':z['end']} for z in ann['denotations']],'coordinate_basis':'annotated_text_codepoints'})
    raw=b''.join((json.dumps(item,ensure_ascii=False,sort_keys=True)+'\n').encode() for item in expected)
    c.require(hashlib.sha256(raw).hexdigest()==c.digest(bundle),'Worker TRAIN bundle differs from verified annotations')
    c.require(not bundle.stat().st_mode&0o077 and not rights.stat().st_mode&0o077,'TRAIN/rights must be private')
    return {'status':'PASS_OWNER_APPROVED_TRAIN_ONLY','pairs':verified['pairs'],'bundle_sha256':c.digest(bundle),'rights_record_sha256':c.digest(rights),'source_manifest_sha256':c.digest(manifest_path),'coordinate_basis':'ann.text codepoints','held_out_approval':False}


def prepare(profile):
    c.require(set(profile)=={'schema_version','experiment','train_source_manifest','host_evidence'},'Unexpected preparation profile fields')
    c.require(profile['schema_version']==1,'Unsupported preparation profile')
    config=pin_existing(copy.deepcopy(profile['experiment']));pipeline.validate(config)
    checks={};blockers=[]
    def check(name,function):
        try:checks[name]=function()
        except (OSError,ValueError,RuntimeError,KeyError,TypeError,tarfile.TarError) as exc:
            checks[name]={'status':'BLOCKED','reason':str(exc)};blockers.append(name+': '+str(exc))
    if config['coding'].get('enabled',True):
        check('source',lambda:source_contract(config))
        check('train',lambda:train_check(config,pin_existing(profile['train_source_manifest'])))
    else:
        checks['source']={'status':'NOT_REQUESTED','reason':'Coding explicitly disabled'}
        checks['train']={'status':'NOT_REQUESTED','reason':'No TRAIN data read or worker disclosure in this experiment'}
    for name in ['aiperf','lm_eval']:
        spec=config['benchmarks'][name]
        if spec['enabled']:
            check(name+'_runtime',lambda spec=spec:runtime_check(spec['runtime']))
            def dataset(spec=spec,name=name):
                from modelbench import adapters
                roots=[spec['tokenizer']]+([spec['hf_home'],spec['include_path']] if name=='lm_eval' else [])
                data=adapters.pinned_dataset(spec['data_manifest'],roots=roots)
                return {'status':'PASS','files':len(data['files']),'manifest_sha256':spec['data_manifest']['sha256']}
            check(name+'_data',dataset)
    for name in ['bfcl','swe_bench']:
        spec=config['benchmarks'][name]
        if not spec['enabled']:continue
        def adapter(spec=spec):
            entry=spec['adapter'];c.require(isinstance(entry,dict),'No pinned scoring adapter')
            for key in ['executable','definition','data_manifest']:c.pin(entry[key])
            definition=c.read(c.pin(entry['definition']));c.require(definition['schema_version']==1,'Invalid scorer definition')
            from modelbench import adapters
            adapters.pinned_dataset(entry['data_manifest'])
            runtime_check(definition['runtime'])
            for artifact in definition['artifacts']:c.pin(artifact)
            qualification=c.read(c.pin(definition['qualification_report']))
            c.require(qualification.get('status')=='PASS' and qualification.get('benchmark')==name,'Missing matching scorer qualification report')
            c.require(definition.get('qualification_status')=='QUALIFIED','Scorer is wired but target/backend qualification remains blocked')
            return {'status':'PASS','version':entry['version']}
        check(name+'_adapter',adapter)
    check('host_evidence',lambda:{'status':'PINNED_HISTORY_NOT_WORKER_READINESS','files':len([c.pin(x) for x in pin_existing(profile['host_evidence'])])})
    phase4=[]
    if config['coding'].get('enabled',True):
        if config['coding'].get('enabled') is not False:phase4.append('Phase4 execution must remain explicitly disabled until independent readiness approval')
        worker_cfg=config['coding'].get('toolchain')
        if not isinstance(worker_cfg,dict) or not worker_cfg.get('path'):phase4.append('Qualified isolated worker/channel/visible-session configuration is not supplied')
        else:
            try:
                import worker
                worker.validate_config(c.pin(worker_cfg))
            except (OSError,ValueError,RuntimeError,KeyError) as exc:phase4.append('Worker toolchain: '+str(exc))
        evaluator=config['coding'].get('evaluator')
        if not isinstance(evaluator,dict):phase4.append('Independent held-out evaluator/Gold/reference qualification is not supplied')
        else:
            try:
                definition=c.read(c.pin(evaluator['definition']))
                c.require(definition.get('qualification_status')=='QUALIFIED_HELD_OUT','Independent held-out evaluator/Gold/reference review is not qualified')
                qualification=c.read(c.pin(definition['qualification_report']))
                c.require(qualification.get('status')=='PASS' and qualification.get('independent') is True and qualification.get('source_sha')==config['coding']['source_sha'],'Independent evaluator qualification does not match source')
                for gate in ['owner_approval','rights_review','human_gold_review','thread_split_review','reference_review','worker_isolation_review']:
                    c.require(qualification.get(gate) is True,'Missing independent gate: '+gate)
            except (OSError,ValueError,RuntimeError,KeyError) as exc:phase4.append(str(exc))
    missing=pipeline.blockers(config)
    readiness={'schema_version':1,'status':'READY_FOR_REVIEW' if not blockers and not phase4 and not missing else 'BLOCKED',
               'configuration_sha256':c.fingerprint(config),'checks':checks,'technical_blockers':blockers,
               'phase4_blockers':phase4,'plan_missing_inputs':missing,'phase4_started':False,
               'scope':'Configuration and exact local bytes only; no benchmark or coding execution'}
    return config,readiness


def publish(folder,config,readiness):
    paths={folder/'benchmark.json':c.encoded(config),folder/'readiness.json':c.encoded(readiness)}
    for path,raw in paths.items():
        if path.exists():c.require(path.read_bytes()==raw,'Prepared configuration differs; select a new output directory')
    c.private_directory(folder)
    for path,raw in paths.items():
        if not path.exists():c.atomic_bytes(path,raw)
    return {'status':readiness['status'],'output':str(folder),'configuration_sha256':readiness['configuration_sha256'],'technical_blockers':readiness['technical_blockers'],'phase4_blockers':readiness['phase4_blockers']}


def main():
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--profile',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--check',action='store_true');mode.add_argument('--write',action='store_true')
    args=parser.parse_args()
    try:
        c.require(os.getuid()!=0,'Run as normal coordinator')
        config,readiness=prepare(c.read(args.profile))
        result=publish(c.safe(args.output),config,readiness) if args.write else readiness
        print(json.dumps(result,indent=2));return 0 if readiness['status']=='READY_FOR_REVIEW' else 2
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
