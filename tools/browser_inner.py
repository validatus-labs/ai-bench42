#!/usr/bin/env python3
"""Fixed existing Brave/MCP command inside its offline native namespace.
browser_inner.py: private root/network -> unchanged native Brave sandbox -> MCP stdio.
No candidate source, TRAIN, host HOME, network route or model service is mounted.
"""
import json,os,re,socket,sys
from pathlib import Path
cfg=json.loads(Path('/run/browser-config.json').read_text())
def denied(host,port,family):
    try:
        with socket.socket(family) as c:c.settimeout(1);c.connect((host,port));return False
    except OSError:return True
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
checks={'namespaces':all(os.readlink('/proc/self/ns/'+n)!=v for n,v in cfg['host_namespaces'].items()),'nonroot_caps_dropped':os.getuid()!=0 and all(int(status[k].strip(),16)==0 for k in ['CapEff','CapPrm','CapBnd','CapAmb']),'no_new_privileges':status['NoNewPrivs'].strip()=='1','ipv4_denied':all(denied(h,p,socket.AF_INET) for h,p in [('127.0.0.1',8000),('10.0.0.1',443),('169.254.169.254',80),('198.51.100.1',443)]),'ipv6_denied':denied('::1',8000,socket.AF_INET6),'host_home_absent':not Path('/home/validatus').exists(),'candidate_absent':not Path('/workspace/melusense').exists(),'train_absent':not Path('/workspace/build/hpi-train-visible.jsonl').exists(),'empty_dns':Path('/etc/resolv.conf').read_bytes()==b''}
import subprocess
probe=subprocess.run(['/usr/bin/python3','-c','import os;os.unshare(os.CLONE_NEWUSER);print("CREATED")'],capture_output=True,text=True)
Path('/workspace/userns-diagnostic.json').write_text(json.dumps({'exit':probe.returncode,'stdout':probe.stdout,'stderr':probe.stderr,'profile':Path('/proc/self/attr/current').read_text()},indent=2)+'\n')
Path('/workspace/browser-boundary.json').write_text(json.dumps({'checks':checks,'status':'PASS' if all(checks.values()) else 'BLOCKED'},indent=2)+'\n')
if not all(checks.values()):raise RuntimeError('Browser offline boundary failed')
argv=['/usr/bin/node','/opt/modelbench/node_modules/@playwright/mcp/cli.js',
'--config','/run/playwright-config.json','--headless','--isolated','--sandbox','--executable-path','/opt/brave.com/brave/brave',
'--block-service-workers','--allowed-origins',';'.join(cfg['origins']),
'--init-page','/run/route.cjs','--output-dir','/workspace/browser']
# Observe only descendants in this private PID namespace; retain no credentials.
import threading,signal,time
observed={};done=threading.Event()
def sample():
    while not done.is_set():
        for proc in Path('/proc').glob('[0-9]*'):
            try:
                exe=os.readlink(proc/'exe')
                if exe!='/opt/brave.com/brave/brave':continue
                state=dict(line.split(':',1) for line in (proc/'status').read_text().splitlines() if ':' in line)
                command=(proc/'cmdline').read_bytes().decode().replace('\x00',' ')
                role_match=re.search(r'(?:^|\s)--type=([a-z-]+)',command)
                role=role_match[1] if role_match else 'browser' if command else 'unknown'
                observed[proc.name]={'executable':exe,'process_type':role,'cmdline_bytes':len(command),'parent_pid':state['PPid'].strip(),'no_sandbox':bool(re.search(r'(?:^|\s)--no-sandbox(?:\s|$)',command)),'profile':(proc/'attr/current').read_text().strip(),'uid':state['Uid'].strip(),'caps':{k:state[k].strip() for k in ['CapEff','CapBnd','NoNewPrivs','Seccomp']},'uid_map':(proc/'uid_map').read_text().strip()}
            except OSError:pass
        if observed:Path('/workspace/brave-processes.json').write_text(json.dumps(observed,indent=2)+'\n')
        done.wait(.003)
threading.Thread(target=sample,daemon=True).start()
child=subprocess.Popen(argv)
def stop(*args):raise KeyboardInterrupt
signal.signal(signal.SIGTERM,stop)
try:child.wait()
finally:
    done.set()
    if child.poll() is None:
        child.terminate()
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.kill();child.wait()


sys.exit(child.returncode if child.returncode>=0 else 128-child.returncode)
