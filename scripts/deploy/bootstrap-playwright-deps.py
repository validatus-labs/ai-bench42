#!/usr/bin/env python3
"""Acquire the exact existing Node MCP lock without downloading another browser.

bootstrap-playwright-deps.py
|-- [J01] validate_lock()  approved package/registry/integrity identities
|-- [J02] inspect()       exact existing lock, versions and installed tree
`-- [J03] install()       private staging -> npm ci -> seal -> atomic rename

Run on Spark as validatus: python3 -B scripts/deploy/bootstrap-playwright-deps.py install
No global npm, browser download, client edit, update or deletion. Failed stages stay.
VS Code: Ctrl+Shift+O for functions; Ctrl+F for [J01]...[J03].
"""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
LOCK_SHA='a80775921958f6a8be8fb02acf4395cb63863ee21f29558df03fb2797e525f4d'
MODULE_SHA='874d211e605bcc860d9f855b7c66566eeaadd8e7c0bd5988e868ebf55df97e47'


def helper():
    spec=importlib.util.spec_from_file_location('playwright_installer',ROOT/'scripts/deploy/install-playwright-mcp.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def validate_lock(h):
    lock=ROOT/'config/playwright-package-lock.json';package=ROOT/'config/playwright-package.json'
    if h.file_sha(lock)!=LOCK_SHA:raise RuntimeError('Approved npm lock differs')
    data=json.loads(lock.read_text());manifest=json.loads(package.read_text())
    if manifest.get('dependencies')!=data['packages']['']['dependencies']:raise RuntimeError('npm manifest/lock differ')
    for name,entry in data['packages'].items():
        if name and (not entry.get('resolved','').startswith('https://registry.npmjs.org/')
                     or not entry.get('integrity','').startswith('sha512-')):
            raise RuntimeError('Unexpected npm source/integrity')
    return package,lock


def inspect(h,profile):
    base=Path(profile['module_root']).parent;h.safe_path(base)
    package,lock=validate_lock(h)
    if not base.exists():return {'status':'MISSING','path':str(base)}
    if (base/'package-lock.json').read_bytes()!=lock.read_bytes() or (base/'package.json').read_bytes()!=package.read_bytes():
        raise RuntimeError('Existing npm files differ; preserve and stop')
    for name,version in profile['packages'].items():
        if json.loads((base/'node_modules'/name/'package.json').read_text())['version']!=version:
            raise RuntimeError('Existing npm version drift')
    seal=h.seal_modules(base/'node_modules')
    if seal['sha256']!=MODULE_SHA:raise RuntimeError('Existing npm tree differs from qualified bytes')
    return {'status':'UNCHANGED','path':str(base),'seal':seal}


def install(h,profile):
    before=inspect(h,profile)
    if before['status']!='MISSING':return before
    node=subprocess.check_output([profile['node'],'--version'],text=True).strip()
    if int(node.lstrip('v').split('.')[0])<profile['minimum_node_major']:raise RuntimeError('Native Node22+ required')
    base=Path(profile['module_root']).parent;base.parent.mkdir(parents=True,exist_ok=True)
    with (base.parent/'playwright-bootstrap.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=inspect(h,profile)
        if before['status']!='MISSING':return before
        stage=Path(tempfile.mkdtemp(prefix='playwright-stage-',dir=base.parent));stage.chmod(0o700)
        package,dependency_lock=validate_lock(h)
        (stage/'package.json').write_bytes(package.read_bytes());(stage/'package-lock.json').write_bytes(dependency_lock.read_bytes())
        temporary=h.safe_path(Path(profile['temporary_root']));temporary.mkdir(parents=True,mode=0o700,exist_ok=True)
        env={'HOME':'/home/validatus','PATH':'/usr/bin:/bin','LANG':'C.UTF-8','TMPDIR':str(temporary),
             'npm_config_cache':str(stage/'cache'),'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD':'1'}
        previous=os.umask(0o022)
        try:
            with (stage/'npm.log').open('xb') as log:
                subprocess.run(['/usr/bin/npm','ci','--ignore-scripts','--no-audit','--no-fund'],cwd=stage,env=env,
                               stdout=log,stderr=subprocess.STDOUT,timeout=600,check=True)
        finally:os.umask(previous)
        if h.seal_modules(stage/'node_modules')['sha256']!=MODULE_SHA:
            raise RuntimeError('Fresh npm bytes differ; staging retained, nothing published')
        if (stage/'package-lock.json').read_bytes()!=dependency_lock.read_bytes():raise RuntimeError('npm changed lock')
        if base.exists() or base.is_symlink():raise RuntimeError('npm destination appeared; stage retained')
        os.rename(stage,base)
        return inspect(h,profile)|{'status':'INSTALLED','new_browser_downloads':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['inspect','install'])
    args=parser.parse_args();h=helper();profile=h.load_profile();h.identity(profile)
    print(json.dumps(install(h,profile) if args.action=='install' else inspect(h,profile),indent=2))


if __name__=='__main__':main()
