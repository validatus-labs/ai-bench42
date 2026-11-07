#!/usr/bin/env python3
"""Export an outcome-free, Git-free coding assignment; never a coordinator tree.

assignment.py
|-- source       explicit task/API/tests/budget allowlist, byte-identical to SHA
|-- navigation   declared candidate-only entrypoints and coordinator placeholders
|-- verify       local links, scaffold, expected unimplemented acceptance failures
`-- publish      deterministic archive + hashed receipt; identical inputs reuse

Normal coordinator account, Python3.12+. No network, inference or installation.
"""
import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

import worker as w

COPIED=(
    'AGENTS.md','TASKS.md','pyproject.toml','config/budget.json','config/models.json',
    'docs/CONTRACT.md','docs/EVALUATION.md','docs/HPI_TRAIN.md','docs/OFFLINE_AGENT_PROMPT.md',
    'melusense/__init__.py','melusense/api.py','tests/fixtures.json',
    'tests/test_scaffold.py','tests/test_greenfield.py','tests/test_acceptance.py','tests/test_reserved_ml_mode.py',
    'tools/greenfield.py','tools/verify_scaffold.py',
)
LINK_CHANGES={
    '../scripts/deploy/README.md':'COORDINATOR.md#host-bootstrap',
    '../scripts/deploy/UPDATES-README.md':'COORDINATOR.md#host-updates',
}


def generated():
    return {
        'README.md':'# Melusense — independent coding assignment\n\nStart at [MANIFEST](MANIFEST.md). This package contains the unimplemented\ncommon task, API, tests and budgets. No previous model results or solution\nare included. Wait for the coordinator readiness gate before implementation.\n',
        'MANIFEST.md':'# Candidate navigation\n\n'+''.join('- ['+p+']('+p+')\n' for p in ['AGENTS.md','TASKS.md','STATE.md','docs/OFFLINE_AGENT_PROMPT.md','docs/CONTRACT.md','docs/EVALUATION.md','docs/RUNBOOK.md','docs/HPI_TRAIN.md','config/budget.json','melusense/api.py','tests/test_acceptance.py','tests/test_reserved_ml_mode.py','tools/verify_scaffold.py']),
        'STATE.md':'# Candidate state\n\nImplementation has not started. This is an outcome-free assignment.\nThe coordinator supplies exact run identity, runtime pins and readiness\nevidence separately. No prior implementation or model result is available.\n',
        'docs/COORDINATOR.md':'# Coordinator-only operations\n\n## Write-scope clarification\n\nThe frozen prompt scope notes contain a conflicting sentence restricting all\nwriting to build/. Read it together with the explicit implementation contract\nin AGENTS.md and TASKS.md: implementation changes belong in melusense/, added\ncandidate tests belong in tests/, and progress reports, logs and generated\nresults belong in build/. Supplied tests and every other task file stay\nread-only. This clarification supplies no implementation or prior result;\nthe original prompt remains byte-identical and this delta is recorded.\n\n## Host bootstrap\n\nThe coordinator provisions and independently qualifies existing pinned\ntools outside the worker. Do not install packages or change the host.\n\n## Host updates\n\nHost maintenance is outside the candidate task. No update or restart\nis authorized from the worker.\n\nSee [runbook](RUNBOOK.md) and [task](../TASKS.md).\n',
        'docs/QUICKSTART.md':'# Offline candidate entry\n\nRead [the common task](../TASKS.md), [agent rules](../AGENTS.md) and\n[English prompt](OFFLINE_AGENT_PROMPT.md). The coordinator supplies the\nqualified workspace and TRAIN bundle. No download or Git access is needed.\n',
        'docs/WORKERS.md':'# Worker boundary\n\nUse only the provided workspace, approved local model and pinned browser\ntools. The coordinator owns namespace setup, channel verification, budget\nenforcement and output freezing. See [runbook](RUNBOOK.md).\n',
        'docs/PIPELINE.md':'# Coordinator pipeline\n\nDeployment, measurements, worker readiness and independent evaluation\nare coordinator responsibilities outside this offline candidate package.\nImplement only [C01–C07](../TASKS.md) after verified readiness.\n',
    }


def inputs(source,sha):
    w.require(re.fullmatch('[a-f0-9]{40}',sha),'Exact source SHA required')
    result={}
    for name in (*COPIED,'docs/RUNBOOK.md'):
        path=source/name;w.require(path.is_file() and not path.is_symlink(),'Missing/linked assignment source: '+name)
        data=path.read_bytes();w.require(len(data)<=2*1024*1024,'Assignment source too large')
        committed=subprocess.run(['git','-C',str(source),'show',sha+':'+name],capture_output=True,timeout=10)
        w.require(committed.returncode==0 and committed.stdout==data,'Assignment differs from approved source: '+name)
        result[name]=data
    return result


def payload(original):
    w.require(set(original)==set(COPIED)|{'docs/RUNBOOK.md'},'Unexpected assignment source inventory')
    result=dict(original);runbook=result['docs/RUNBOOK.md'].decode()
    for old,new in LINK_CHANGES.items():
        w.require(runbook.count(']('+old+')')==1,'Unexpected runbook navigation')
        runbook=runbook.replace(']('+old+')',']('+new+')')
    result['docs/RUNBOOK.md']=runbook.encode()
    result.update({name:value.encode() for name,value in generated().items()})
    for name,data in result.items():
        if name.endswith('.md'):
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',data.decode()):
                if '://' in target:continue
                relative=os.path.normpath(str(Path(name).parent/target.split('#')[0]))
                w.require(relative in result,'Broken candidate link '+name+': '+target)
    return result


def archive_bytes(files):
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w',format=tarfile.USTAR_FORMAT) as tar:
        for name,data in sorted(files.items()):
            item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o600;item.mtime=0;item.uid=0;item.gid=0
            tar.addfile(item,io.BytesIO(data))
    return output.getvalue()


def export(source,sha,destination):
    source=w.safe(source);destination=w.safe(destination);original=inputs(source,sha);files=payload(original);raw=archive_bytes(files)
    identity={'source_sha':sha,'source_files':{n:w.sha(d) for n,d in original.items()},'files':{n:w.sha(d) for n,d in files.items()},
              'derived_navigation':sorted(generated()),'runbook_link_changes':LINK_CHANGES,'archive_sha256':w.sha(raw),'exporter_sha256':w.digest(Path(__file__))}
    if destination.exists():
        receipt=w.read(w.private(destination/'receipt.json'))
        w.require(receipt['identity']==identity and w.digest(destination/'assignment.tar')==identity['archive_sha256'],'Assignment changed; choose a new destination')
        for row in receipt['checks']:w.require(w.digest(destination/row['log'])==row['sha256'],'Assignment check evidence changed')
        return dict(receipt,reused=True)
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    stage=Path(tempfile.mkdtemp(prefix='.assignment-',dir=destination.parent));ws=stage/'scaffold';ws.mkdir(mode=0o700)
    for name,data in files.items():
        p=ws/name;p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);p.write_bytes(data);p.chmod(0o600)
    checks=[]
    for name,argv,success in [('scaffold',['tools/verify_scaffold.py'],True),('starter-tests',['-m','unittest','discover','-s','tests','-p','test_scaffold.py','-v'],True),('empty-parser-acceptance',['-m','unittest','discover','-s','tests','-p','test_acceptance.py','-v'],False)]:
        r=subprocess.run([sys.executable,'-B',*argv],cwd=ws,capture_output=True,timeout=60);data=r.stdout+r.stderr
        w.require(len(data)<1024*1024,'Assignment log bound');log=name+'.log';(stage/log).write_bytes(data)
        w.require((r.returncode==0)==success and (success or b'NotImplementedError' in data),'Unexpected initial scaffold result: '+name)
        checks.append({'name':name,'exit_code':r.returncode,'expected_success':success,'log':log,'sha256':w.sha(data)})
    (stage/'assignment.tar').write_bytes(raw);w.write(stage/'receipt.json',{'status':'PREPARED_NOT_READY','identity':identity,'checks':checks,'reused':False})
    w.publish(stage,destination);return w.read(destination/'receipt.json')


if __name__=='__main__':
    import sys
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--source-sha',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    try:
        r=export(a.source,a.source_sha,a.output);print(json.dumps({'status':r['status'],'archive_sha256':r['identity']['archive_sha256'],'reused':r['reused']}))
    except (w.Blocked,OSError,subprocess.SubprocessError) as e:p.exit(2,'BLOCKED: '+str(e)+'\n')
