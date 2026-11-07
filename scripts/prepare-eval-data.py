#!/usr/bin/env python3
"""Prepare complete offline lm-eval data from exact upstream commits; no inference.

prepare-eval-data.py
|-- --revision-lock    three explicit Hugging Face dataset commit SHAs
|-- existing output    verify all pinned bytes, preserve unchanged bundle
`-- new output        materialize datasets + upstream task templates + manifest

Run with the pinned lm_eval API environment. Partial attempts are retained;
use a new destination after diagnosing failure. No mail or model weights involved.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sys
from modelbench import common as c,adapters

DATASETS={'ifeval':'google/IFEval','mmlu_pro':'TIGER-Lab/MMLU-Pro','bbh':'SaylorTwift/bbh'}


def prepare(destination,lock):
    c.require(importlib.metadata.version('lm_eval')=='0.4.13','Use the pinned lm_eval0.4.13 API environment')
    c.require(set(lock)=={'schema_version','datasets'} and lock['schema_version']==1,'Invalid dataset revision lock')
    c.require(set(lock['datasets'])==set(DATASETS),'Pin all three dataset sources')
    for name,repo in DATASETS.items():
        row=lock['datasets'][name];c.require(row['repo']==repo and re.fullmatch('[a-f0-9]{40}',row['revision']),'Pin exact upstream dataset commits')
    destination=c.safe(destination)
    identity=c.fingerprint({'lock':lock,'lm_eval':'0.4.13','builder_sha256':c.digest(Path(__file__))})
    if destination.exists():
        record=c.read(destination/'preparation.json');c.require(record['identity']==identity and record['status']=='PREPARED','Different/partial offline preparation; preserve and use new output')
        adapters.pinned_dataset(record['data_manifest'],roots=[str(destination/'tasks'),str(destination/'hf-home'),str(destination/'data')])
        return dict(record,action='UNCHANGED')
    c.private_directory(destination)
    record={'schema_version':1,'identity':identity,'status':'PREPARING','upstream':lock,'lm_eval_version':'0.4.13','counts':{}}
    c.save(destination/'preparation.json',record)
    os.environ['HF_HOME']=str(destination/'hf-home')
    os.environ['HF_DATASETS_CACHE']=str(destination/'hf-home/datasets')
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN']='1'
    from datasets import load_dataset,get_dataset_config_names
    import yaml
    from yaml.nodes import MappingNode,ScalarNode
    class KeepFunctions(yaml.SafeLoader):pass
    def function(loader,node):return Tagged(loader.construct_scalar(node))
    class Tagged(str):pass
    KeepFunctions.add_constructor('!function',function)
    class Dumper(yaml.SafeDumper):pass
    Dumper.add_representer(Tagged,lambda dumper,value:dumper.represent_scalar('!function',str(value)))
    upstream=Path(importlib.metadata.distribution('lm_eval').locate_file('lm_eval/tasks'))
    tasks=destination/'tasks';tasks.mkdir(mode=0o700)
    hf=destination/'hf-home';hf.mkdir(mode=0o700)
    data=destination/'data';data.mkdir(mode=0o700)
    cache=destination/'download-cache';cache.mkdir(mode=0o700)
    def export(name,subset=None):
        spec=lock['datasets'][name]
        loaded=load_dataset(spec['repo'],subset,revision=spec['revision'],cache_dir=str(cache),token=False)
        result={}
        for split,ds in loaded.items():
            target=data/(name+('-'+subset if subset else '')+'-'+split+'.jsonl')
            ds.to_json(str(target),force_ascii=False);target.chmod(0o600)
            result[split]=str(target);record['counts'][name+('/'+subset if subset else '')+'/'+split]=len(ds)
        return result
    for name in DATASETS:
        relative='bbh/cot_fewshot' if name=='bbh' else name
        target=tasks/name
        shutil.copytree(upstream/relative,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        if name!='bbh':
            files=export(name)
            anchor=target/('ifeval.yaml' if name=='ifeval' else '_default_template_yaml')
            item=yaml.load(anchor.read_text(),Loader=KeepFunctions)
            item['dataset_path']='json';item['dataset_name']=None;item['dataset_kwargs']={'data_files':files}
            anchor.write_text(yaml.dump(item,Dumper=Dumper,sort_keys=False))
        else:
            subsets=get_dataset_config_names(DATASETS[name],revision=lock['datasets'][name]['revision'],token=False)
            selected=[]
            for file in sorted(target.glob('*.yaml')):
                if file.name.startswith('_'):continue
                item=yaml.load(file.read_text(),Loader=KeepFunctions);subset=item['dataset_name'];c.require(subset in subsets,'BBH subset absent')
                item['dataset_path']='json';item['dataset_name']=None;item['dataset_kwargs']={'data_files':export(name,subset)}
                file.write_text(yaml.dump(item,Dumper=Dumper,sort_keys=False));selected.append(item['task'])
            c.require(len(selected)==27,'Expected all27 BBH tasks')
    # Prepare the sentence-tokenizer data required by official IFEval scoring.
    import nltk
    nltk_root=data/'nltk';nltk_root.mkdir(mode=0o700)
    c.require(nltk.download('punkt_tab',download_dir=str(nltk_root),quiet=True,raise_on_error=True),'IFEval sentence tokenizer unavailable')
    os.environ['NLTK_DATA']=str(nltk_root);nltk.data.path.insert(0,str(nltk_root))
    c.require(nltk.sent_tokenize('First sentence. Second sentence.')==['First sentence.','Second sentence.'],'Sentence-tokenizer smoke failed')
    record['nltk_data']=str(nltk_root)
    # Load every task offline before sealing generated Arrow caches as well.
    os.environ['HF_HUB_OFFLINE']='1';os.environ['HF_DATASETS_OFFLINE']='1'
    from lm_eval.tasks import TaskManager,get_task_dict
    manager=TaskManager(include_path=str(tasks))
    loaded_tasks=get_task_dict(['ifeval','mmlu_pro','bbh'],task_manager=manager)
    record['task_resolution']={str(name):type(task).__name__ for name,task in loaded_tasks.items()}
    # Source templates are retained separately from locally patched data locators.
    record['adaptation']='Only dataset_path/name/kwargs changed to sealed local JSONL; prompts/scoring/fewshots unchanged'
    # Hub snapshots contain owned links to blob files. Materialize only files
    # resolving within this newly created bundle, then seal regular bytes.
    for p in sorted(hf.rglob('*')):
        if p.is_symlink():
            resolved=p.resolve();c.require(resolved.is_relative_to(destination) and resolved.is_file(),'HF snapshot link escapes prepared bundle')
            temporary=p.with_name(p.name+'.materialized');shutil.copyfile(resolved,temporary);p.unlink();temporary.replace(p)
    files=[]
    for root in [tasks,hf,data]:
        for p in sorted(root.rglob('*')):
            c.require(not p.is_symlink(),'Unexpected symlink in data bundle')
            if p.is_file():
                p.chmod(0o600);files.append({'path':str(p),'sha256':c.digest(p),'revision':'lm-eval0.4.13+dataset-lock-'+c.fingerprint(lock)})
    # HF_HOME contains no credentials; a small provenance file also seals its scope.
    c.save(hf/'offline.json',{'network_downloads':False,'datasets':lock['datasets']})
    files.append({'path':str(hf/'offline.json'),'sha256':c.digest(hf/'offline.json'),'revision':c.fingerprint(lock)})
    manifest=destination/'data-manifest.json';c.save(manifest,{'schema_version':1,'files':files,'upstream':lock})
    record.update(status='PREPARED',data_manifest={'path':str(manifest),'sha256':c.digest(manifest)},include_path=str(tasks),hf_home=str(hf))
    c.save(destination/'preparation.json',record)
    return dict(record,action='CREATED')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--revision-lock',required=True,type=Path);a=p.parse_args()
    try:
        c.require(os.getuid()!=0,'Run as normal coordinator');print(json.dumps(prepare(a.output,c.read(a.revision_lock)),indent=2));return 0
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,ImportError) as exc:
        print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2
if __name__=='__main__':sys.exit(main())
