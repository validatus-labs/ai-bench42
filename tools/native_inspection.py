#!/usr/bin/env python3
"""Prepare/reuse a sealed, synthetic native Kilo inspection (never a coding run).

native_inspection.py
|-- validated JSON profile  existing rootfs, Python and installed extension pins
|-- prepare once           private synthetic workspace, fixed provider, derived UI
`-- repeat                 verify sealed inputs; no service start or inference

Run as the normal target user: python3 -B tools/native_inspection.py --profile FILE.
Starting the reviewed inspection is a separate native_gui attachment action.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

import worker as w

SOURCES=('worker.py','worker_inner.py','native_namespace.py','native_gui.py','native_gui_inner.py')


def artifact(path):return {'path':str(path),'sha256':w.digest(path)}


def derive_extension(ext,dev,root,expected):
    pkg=w.read(ext/'package.json')
    shutil.copytree(ext,dev,symlinks=True)
    w.require(w.tree(ext)==expected and w.tree(dev)==expected,'Extension changed during copy')
    launcher='#!/usr/bin/env python3\nimport os,sys\nif sys.argv[1:]==["--version"]:os.execv('+repr(str(ext/'bin/kilo'))+',['+repr(str(ext/'bin/kilo'))+',"--version"])\nos.execv("/usr/bin/python3",["python3","-B",'+repr(str(root/'native_gui.py'))+',"attach","--configuration",'+repr(str(root/'gui.json'))+'])\n'
    (dev/'bin/kilo').write_text(launcher);(dev/'bin/kilo').chmod(0o755)
    pkg['main']='./native-activate.cjs';pkg['activationEvents']=sorted(set(pkg.get('activationEvents',[]))|{'onStartupFinished'});(dev/'package.json').write_bytes(w.encoded(pkg))
    (dev/'native-activate.cjs').write_text('const vscode=require("vscode");const base=require("./dist/extension.js");exports.activate=async c=>{const r=await base.activate(c);setTimeout(()=>vscode.commands.executeCommand("workbench.view.extension.kilo-code-ActivityBar"),1500);return r;};exports.deactivate=base.deactivate;\n')
    return w.tree(dev)


def prepare(profile):
    w.require(os.getuid()!=0 and sys.version_info>=(3,12),'Use the normal target user and Python3.12')
    definition=w.read(w.private(profile))
    w.require(set(definition)=={'schema_version','run_id','destination','rootfs','rootfs_tree_sha256','python','extension','extension_tree_sha256'} and definition['schema_version']==1,'Invalid inspection profile')
    w.require(re.fullmatch('[a-z0-9-]{1,60}',definition['run_id']),'Invalid inspection Run-ID')
    root=w.safe(definition['destination']);fs=w.safe(definition['rootfs']);ext=w.safe(definition['extension'])
    python=w.checked_artifact(definition['python'])
    w.require(python.resolve()==Path(sys.executable).resolve(),'Use the pinned interpreter')
    w.require(w.tree(fs)==w.pin(definition['rootfs_tree_sha256']),'Runtime changed')
    w.require(w.tree(ext)==w.pin(definition['extension_tree_sha256']),'Installed extension changed')
    pkg=w.read(ext/'package.json');w.require(pkg['publisher']=='kilocode' and pkg['name']=='kilo-code','Wrong installed extension')
    origin=Path(__file__).parent
    identity={'profile':definition,'sources':{name:w.digest(origin/name) for name in SOURCES},'builder':w.digest(Path(__file__))}
    if root.exists():
        receipt=w.read(w.private(root/'inspection-receipt.json'))
        w.require(receipt['identity']==identity,'Inspection inputs changed; choose a new destination')
        for name,digest in receipt['sealed'].items():w.require(w.digest(root/name)==digest,'Inspection source/configuration changed')
        w.require(w.tree(root/'extension')==receipt['extension_tree_sha256'],'Derived extension changed')
        return dict(receipt,reused=True)
    root.mkdir(parents=True,mode=0o700)
    w.write(root/'prepare-intent.json',identity)
    for name in SOURCES:shutil.copyfile(origin/name,root/name)
    ws=root/'run/workspace';ws.mkdir(parents=True,mode=0o700)
    for name in ['melusense','tests','build']:(ws/name).mkdir(mode=0o700)
    (ws/'AGENTS.md').write_text('Synthetic inspection only. No model request or coding trial is authorized.\n')
    (ws/'README.md').write_text('# Native Kilo inspection\nNo benchmark candidate or TRAIN correspondence is present.\n')
    (ws/'tests/fixed.py').write_text('# frozen synthetic marker\n')
    (ws/'build/hpi-train-visible.jsonl').write_text('{"synthetic_only":true}\n')
    record={'identity':{'run_id':definition['run_id'],'seed':1,'train_sha256':w.digest(ws/'build/hpi-train-visible.jsonl')},'frozen':{'AGENTS.md':w.digest(ws/'AGENTS.md'),'tests/fixed.py':w.digest(ws/'tests/fixed.py')}}
    provider={'enabled_providers':['001'],'model':'001/kolibri-1','small_model':'001/kolibri-1','autoupdate':False,'share':'disabled','snapshot':False,'privacy_mode':True,'remote_control':False,'web_search':False,'compaction':{'auto':False,'prune':False},'default_agent':'modelbench',
        'provider':{'001':{'name':'Native isolated Kolibri (inspection only)','npm':'@ai-sdk/openai-compatible','options':{'baseURL':'http://127.0.0.1:18080/v1','apiKey':'local-placeholder-not-secret','timeout':30000},'models':{'kolibri-1':{'name':'Kolibri-1 FP8 V5','limit':{'context':262144,'output':32768},'tool_call':True,'reasoning':True}}}},
        'permission':{'*':'deny'},'mcp':{'kilo-playwright':{'enabled':False}},'agent':{'modelbench':{'mode':'primary','model':'001/kolibri-1','temperature':.2,'top_p':1,'steps':100,'permission':{'*':'deny'},'prompt':'Inspection only. No model or coding request is authorized; inference channel is absent.'}}}
    w.write(root/'modelbench.json',provider);w.write(root/'record.json',record)
    config={'native_namespace':{'constructor':artifact(root/'native_namespace.py'),'gui_inner':artifact(root/'native_gui_inner.py'),'python':artifact(python),'uid':os.getuid(),'gid':os.getgid()},'rootfs':{'path':str(fs)},'agent':{'environment':{},'config_files':[dict(artifact(root/'modelbench.json'),destination='/home/worker/.config/kilo/modelbench.json')]},'channels':{},'limits':{'address_space_mib':4096,'file_size_mib':64,'open_files':256,'processes':256}}
    w.write(root/'toolchain.json',config)
    dev=root/'extension';derive_extension(ext,dev,root,definition['extension_tree_sha256'])
    settings={'schema_version':1,'mode':'INSPECTION_NO_INFERENCE','root':str(root),'run_id':definition['run_id'],'toolchain':artifact(root/'toolchain.json'),'record':artifact(root/'record.json'),'rootfs_tree_sha256':definition['rootfs_tree_sha256'],'sources':{name:artifact(root/name) for name in SOURCES},'extension_tree_sha256':w.tree(dev)}
    w.write(root/'gui.json',settings)
    sealed={name:w.digest(root/name) for name in (*SOURCES,'modelbench.json','record.json','toolchain.json','gui.json')}
    receipt={'schema_version':1,'status':'PREPARED_INSPECTION_NOT_C00','identity':identity,'sealed':sealed,'extension_tree_sha256':settings['extension_tree_sha256'],'reused':False}
    w.write(root/'inspection-receipt.json',receipt);return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',required=True,type=Path);args=parser.parse_args()
    try:
        result=prepare(args.profile);print(json.dumps({k:result[k] for k in ['status','reused']}));return 0
    except (OSError,ValueError,RuntimeError,KeyError) as exc:print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
