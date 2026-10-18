#!/usr/bin/env python3
"""Native Ubuntu prerequisites and existing Berlin-time maintenance contract.

bootstrap-host.py
|-- [J01] inspect()      OS/native Node/APT/user-manager prerequisites
|-- [J02] targets()      exact existing maintenance sources and OS destinations
`-- [J03] install()      preflight -> non-upgrading APT -> missing files -> timers

Run inspect as validatus; install through sudo on native spark-a922 only.
Never changes NVIDIA drivers, security profiles, SSH, firewall or an APT origin.
Missing Node22+ requires an already approved signed native APT repository.
VS Code: Ctrl+Shift+O for functions, Ctrl+F [J01]...[J03].
"""
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
STATE=Path('/var/lib/ai-model-apt-maintenance')
DEPLOY_USER='validatus'
INSTALL_MAINTENANCE=True
PACKAGES=['ca-certificates','curl','gnupg','python3-venv','rsync','bubblewrap','unattended-upgrades','nodejs']


def command(args):
    return subprocess.run(args,capture_output=True,text=True,timeout=30)


def targets():
    return [(ROOT/'scripts/deploy/spark-apt-maintenance.sh',Path('/usr/local/libexec/ai-model/apt-maintenance'),0o755),
        (ROOT/'config/99ai-model-updates',Path('/etc/apt/apt.conf.d/99ai-model-updates'),0o644)]+[
        (ROOT/'config/systemd'/name,Path('/etc/systemd/system')/name,0o644) for name in
        ['ai-model-apt-update@.service','ai-model-security-updates.timer','ai-model-weekly-updates.timer']]


def inspect():
    release=platform.freedesktop_os_release()
    incompatible=[]
    if release.get('ID')!='ubuntu' or release.get('VERSION_ID')!='24.04':incompatible.append('Requires Ubuntu24.04/NVIDIA OEM image')
    missing=[]
    for package in PACKAGES:
        r=command(['dpkg-query','-W','-f=${db:Status-Status}',package])
        if r.returncode or r.stdout!='installed':missing.append(package)
    node=command(['/usr/bin/node','--version']) if Path('/usr/bin/node').exists() else None
    if node and (node.returncode or not re.match(r'^v(2[2-9]|[3-9][0-9])\.',node.stdout)):
        incompatible.append('Existing Node is incompatible; never upgrade it implicitly')
    if node and (not Path('/usr/bin/npm').exists() or not Path('/usr/bin/npx').exists()):
        incompatible.append('Existing native Node package lacks npm/npx; repair explicitly')
    if not node:
        candidate=command(['apt-cache','policy','nodejs']).stdout
        match=re.search(r'Candidate:\s+(?:[0-9]+:)?([0-9]+)\.',candidate)
        if not match or int(match[1])<22:incompatible.append('Approved signed Node22+ APT source/lists required')
    for source,dest,mode in targets():
        for path in [dest]+list(dest.parents):
            if path.is_symlink():incompatible.append('Symlink in native target path: '+str(path))
        if dest.exists():
            if (not dest.is_file() or dest.stat().st_uid!=0 or dest.stat().st_mode&0o022
                    or dest.read_bytes()!=source.read_bytes() or dest.stat().st_mode&0o777!=mode):
                incompatible.append('Preserve divergent native target: '+str(dest))
    return {'missing_packages':missing,'incompatible':incompatible,'node_version':node.stdout.strip() if node else None,
            'status':'BLOCKED' if incompatible else ('MISSING' if missing or any(not d.exists() for _,d,_ in targets()) else 'READY')}


def install():
    if os.geteuid()!=0:raise RuntimeError('Use sudo for native host install')
    facts=inspect()
    if facts['incompatible']:raise RuntimeError(json.dumps(facts))
    state=STATE;state.mkdir(mode=0o700,exist_ok=True)
    with (state/'maintenance.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        facts=inspect()
        if facts['incompatible']:raise RuntimeError(json.dumps(facts))
        report={'before':facts,'started':datetime.datetime.now(datetime.timezone.utc).isoformat(),'created_files':[]}
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        receipt=state/('bootstrap-'+stamp+'.json')
        def save():receipt.write_text(json.dumps(report,indent=2)+'\n');receipt.chmod(0o600)
        save()
        try:
            if facts['missing_packages']:
                env=dict(os.environ,DEBIAN_FRONTEND='noninteractive',NEEDRESTART_MODE='l',LC_ALL='C')
                subprocess.run(['apt-get','-o','DPkg::Lock::Timeout=1800','-o','APT::Update::Error-Mode=any','update'],check=True,env=env,timeout=1800)
                base=['apt-get','-o','DPkg::Lock::Timeout=1800','--no-upgrade','--no-remove','--no-install-recommends']
                planned=subprocess.run(base+['--simulate','install']+facts['missing_packages'],capture_output=True,text=True,check=True,env=env,timeout=120).stdout
                report['apt_plan']=planned;save()
                if re.search(r'^Remv |^Inst \S+ \[',planned,re.M):raise RuntimeError('APT proposes installed-package upgrade/removal')
                subprocess.run(base+['--yes','install']+facts['missing_packages'],check=True,env=env,timeout=3600)
            for source,dest,mode in targets():
                if dest.exists():continue
                dest.parent.mkdir(parents=True,exist_ok=True,mode=0o755)
                with dest.open('xb') as out:os.fchmod(out.fileno(),mode);out.write(source.read_bytes())
                report['created_files'].append(str(dest));save()
            if INSTALL_MAINTENANCE:
                if report['created_files']:subprocess.run(['systemctl','daemon-reload'],check=True,timeout=30)
                subprocess.run(['systemd-analyze','verify']+[str(d) for _,d,_ in targets() if d.suffix in {'.service','.timer'}],check=True,timeout=30)
                for timer in ['apt-daily.timer','apt-daily-upgrade.timer']:
                    if command(['systemctl','show',timer,'-p','LoadState','--value']).stdout.strip()!='not-found':
                        subprocess.run(['systemctl','disable','--now',timer],check=True,timeout=30)
                for timer in ['ai-model-security-updates.timer','ai-model-weekly-updates.timer']:
                    subprocess.run(['systemctl','enable','--now',timer],check=True,timeout=30)
                if command(['loginctl','show-user',DEPLOY_USER,'-p','Linger','--value']).stdout.strip()!='yes':
                    subprocess.run(['loginctl','enable-linger',DEPLOY_USER],check=True,timeout=30)
            report['after']=inspect()
            if report['after']['status']!='READY':raise RuntimeError('Native prerequisites incomplete')
            report['status']='COMPLETED';return report
        except BaseException as exc:
            report.update(status='FAILED',error=type(exc).__name__+': '+str(exc));raise
        finally:save()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['inspect','install']);args=parser.parse_args()
    if platform.node()!='spark-a922' or platform.machine()!='aarch64' or ROOT!=Path('/home/validatus/workspace/AI-Model'):
        parser.error('Native mirrored Spark workspace required')
    print(json.dumps(install() if args.action=='install' else inspect(),indent=2))


if __name__=='__main__':main()
