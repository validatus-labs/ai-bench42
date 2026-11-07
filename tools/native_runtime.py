#!/usr/bin/env python3
"""Seal a minimal native worker runtime from existing verified public binaries.

native_runtime.py
|-- inspect pins   exact installed Python/Node/Kilo; never copy a user home
|-- build once     stdlib, selected shell tools, ELF dependencies, synthetic /etc
`-- repeat         verify complete inventory; changed input never overwrites

No package installation, model access, source solution or agent-session import.
This builds the execution substrate only, never a C00/READY certificate.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import sysconfig

import worker

ROOT=Path(__file__).resolve().parents[1]
COMMANDS=['bash','dash','cat','ls','mkdir','cp','mv','rm','find','sed','awk','head','tail','sort','uniq','wc','printf','tee','chmod','timeout','uname','env','pwd','date','sha256sum']
FONTCONFIG='<fontconfig><dir>/usr/share/fonts</dir><cachedir>/tmp/fontconfig</cachedir><alias><family>sans-serif</family><prefer><family>DejaVu Sans</family></prefer></alias><alias><family>serif</family><prefer><family>DejaVu Serif</family></prefer></alias><alias><family>monospace</family><prefer><family>DejaVu Sans Mono</family></prefer></alias></fontconfig>\n'


def font_inputs(definition):
    fonts=definition.get('fonts',{})
    if not fonts:return {}
    worker.require(set(fonts)=={'DejaVuSans.ttf','DejaVuSansMono.ttf','DejaVuSerif.ttf'},'Pin the three existing public font files')
    result={}
    for name,item in fonts.items():
        source=worker.checked_artifact(item)
        worker.require(source.is_relative_to('/usr/share/fonts') and source.suffix=='.ttf','Font must be an existing public system TTF')
        result[name]=source
    return result


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    result={}
    for path in sorted(root.rglob('*')):
        relative=str(path.relative_to(root));info=path.lstat()
        if stat.S_ISLNK(info.st_mode):result[relative]={'link':os.readlink(path)}
        elif path.is_file():result[relative]={'sha256':digest(path),'mode':stat.S_IMODE(info.st_mode)}
        elif path.is_dir():result[relative]={'directory':True,'mode':stat.S_IMODE(info.st_mode)}
        else:raise ValueError('Unexpected runtime device/socket')
    return result


def build(profile,destination):
    worker.require(os.getuid()!=0 and sys.version_info>=(3,12),'Run as the normal Python3.12 coordinator')
    definition=worker.read(worker.safe(profile))
    worker.require({'schema_version','python','node','kilo','ripgrep'}<=set(definition)<={'schema_version','python','node','kilo','ripgrep','brave','fonts'} and definition['schema_version']==1,'Invalid native runtime profile')
    pins={key:worker.checked_artifact(definition[key]) for key in ['python','node','kilo','ripgrep']}
    fonts=font_inputs(definition)
    worker.require(pins['python'].resolve()==Path(sys.executable).resolve(),'Build with the pinned interpreter')
    destination=worker.safe(destination);identity={'profile':definition,'builder_sha256':digest(Path(__file__))}
    if destination.exists():
        receipt=worker.read(destination/'receipt.json')
        worker.require(receipt['identity']==identity,'Runtime input changed; choose a fresh destination')
        worker.require(receipt['files']==inventory(destination/'rootfs') and worker.tree(destination/'rootfs')==receipt['rootfs_tree_sha256'],'Native runtime changed')
        return dict(receipt,reused=True)
    destination.mkdir(mode=0o700,parents=True)
    root=destination/'rootfs';root.mkdir(mode=0o755)
    for name in ['usr/bin','usr/lib','lib','etc/ssl/certs','opt/modelbench','proc','dev','tmp','run','home','root','workspace']:(root/name).mkdir(parents=True,exist_ok=True)
    (root/'bin').symlink_to('usr/bin');elf=set()
    def copy(source,target):
        source=Path(source);target=root/target.lstrip('/')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        mode=0o755 if source.stat().st_mode&0o111 else 0o644;target.chmod(mode)
        with source.open('rb') as stream:
            if stream.read(4)==b'\x7fELF':elf.add(source.resolve())
    for key,target in [('python','/usr/bin/python3.12'),('node','/usr/bin/node'),('kilo','/opt/modelbench/kilo'),('ripgrep','/usr/bin/rg')]:
        copy(pins[key],target)
        worker.require(digest(root/target.lstrip('/'))==definition[key]['sha256'],'Pinned executable changed during copy: '+key)
    for name,source in fonts.items():
        copy(source,'/usr/share/fonts/truetype/dejavu/'+name)
        worker.require(digest(root/'usr/share/fonts/truetype/dejavu'/name)==definition['fonts'][name]['sha256'],'Font changed during copy')
    if fonts:
        (root/'etc/fonts').mkdir(mode=0o755)
        (root/'etc/fonts/fonts.conf').write_text(FONTCONFIG)
    if 'brave' in definition:
        brave=worker.checked_artifact(definition['brave']);elf.add(brave.resolve())
        (root/'opt/brave.com/brave').mkdir(parents=True)
        (root/'opt/modelbench/node_modules').mkdir()
        (root/'sys/devices/system/cpu').mkdir(parents=True)
        (root/'.oldroot').mkdir()
        for extra in brave.parent.glob('*.so'):
            # Desktop Qt bridges are not used by this fixed headless command.
            # Their optional Qt packages are absent on the existing host too.
            if extra.name in {'libqt5_shim.so','libqt6_shim.so'}:continue
            if extra.is_file():elf.add(extra.resolve())
    (root/'usr/bin/python3').symlink_to('python3.12')
    stdlib=Path(sysconfig.get_path('stdlib'))
    worker.require(stdlib==Path('/usr/lib/python3.12'),'Use the native system standard library only')
    for path in stdlib.rglob('*'):
        if path.name in {'sitecustomize.py','usercustomize.py'}:continue
        if any(part in {'__pycache__','site-packages','dist-packages'} for part in path.relative_to(stdlib).parts):continue
        if path.is_file():
            worker.require(str(path.resolve()).startswith(('/usr/lib/','/lib/')),'Standard-library link escapes public system libraries')
            copy(path,str(path))
    for command in COMMANDS:
        source=shutil.which(command)
        worker.require(source is not None,'Required existing worker utility missing: '+command)
        copy(Path(source).resolve(),'/usr/bin/'+command)
    (root/'usr/bin/sh').symlink_to('dash')
    probe=subprocess.run(['/usr/bin/ldd',*map(str,sorted(elf))],capture_output=True,text=True,timeout=90,env={'PATH':'/usr/bin:/bin',**({'LD_LIBRARY_PATH':str(brave.parent)} if 'brave' in definition else {})})
    worker.require('not found' not in probe.stdout+probe.stderr,'Native ELF dependency missing')
    libraries=set(re.findall(r'(/[^\s:]+)\s+\(',probe.stdout))
    worker.require(libraries and len(libraries)<=256,'Invalid ELF dependency closure')
    for library in sorted(libraries):
        worker.require(library.startswith(('/lib/','/usr/lib/')),'ELF dependency outside public system library directories')
        copy(library,library)
    copy('/etc/ssl/certs/ca-certificates.crt','/etc/ssl/certs/ca-certificates.crt')
    for name,text in {'passwd':'root:x:0:0:root:/root:/bin/sh\nworker:x:'+str(os.getuid())+':'+str(os.getgid())+':worker:/home/worker:/bin/bash\n','group':'root:x:0:\nworker:x:'+str(os.getgid())+':\n','hosts':'127.0.0.1 localhost\n::1 localhost\n','resolv.conf':'','nsswitch.conf':'passwd: files\ngroup: files\nhosts: files\n'}.items():(root/'etc'/name).write_text(text)
    (root/'opt/modelbench/worker_inner.py').touch()
    for path in root.rglob('*'):
        if path.is_symlink():continue
        if path.is_dir():path.chmod(0o755)
        elif not path.stat().st_mode&0o111:path.chmod(0o644)
    receipt={'schema_version':1,'status':'BUILT_NOT_READY','identity':identity,'files':inventory(root),'rootfs_tree_sha256':worker.tree(root),'reused':False}
    worker.write(destination/'receipt.json',receipt)
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--profile',required=True,type=Path);parser.add_argument('--destination',required=True,type=Path);args=parser.parse_args()
    try:
        result=build(args.profile,args.destination);print(json.dumps({key:result[key] for key in ['status','rootfs_tree_sha256','reused']}));return 0
    except (OSError,ValueError,RuntimeError,KeyError,subprocess.SubprocessError) as exc:print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
