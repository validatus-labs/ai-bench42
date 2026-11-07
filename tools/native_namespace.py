#!/usr/bin/env python3
"""Ephemeral native namespace constructor; no installation or host policy writes.

native_namespace.py
|-- validate     sealed coordinator manifest, regular sources and explicit mounts
|-- parent       root opens sources; writes child UID/GID maps; owns cleanup
|-- child        seven namespaces, read-only root, private proc/dev/home/network
`-- exec         non-root UID, empty capabilities, no-new-privs and namespace filter

Only the trusted coordinator invokes this with sudo. No worker-supplied command
is ever executed with root privileges. No host home, /usr or root is mounted.
The parent-written map avoids a dependency on newuidmap or Bubblewrap.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile


def require(ok, message):
    if not ok: raise ValueError(message)


def safe(value):
    path = Path(value)
    require(path.is_absolute() and '..' not in path.parts, 'Absolute non-traversing path required')
    for parent in (path,) + tuple(path.parents):
        require(not parent.is_symlink(), 'Source symlink refused')
    return path


def validate(path, checksum):
    path = safe(path); raw = path.read_bytes()
    require(len(raw) <= 256*1024 and hashlib.sha256(raw).hexdigest() == checksum, 'Manifest hash/size differs')
    value = json.loads(raw)
    require(set(value) in ({'schema_version','uid','gid','rootfs','mounts','environment','argv','cwd'},{'schema_version','uid','gid','rootfs','mounts','environment','argv','cwd','role'}), 'Unknown native manifest fields')
    require(value.get('role','worker') in {'worker','browser'},'Unknown namespace role')
    browser=value.get('role')=='browser'
    if browser:require(value['argv']==['/usr/bin/python3','-B','/run/browser_inner.py'],'Fixed browser entrypoint required')
    require(value['schema_version'] == 1 and type(value['uid']) is int and value['uid'] > 0
            and type(value['gid']) is int and value['gid'] > 0, 'Non-root worker identity required')
    require(path.stat().st_uid == value['uid'] and stat.S_IMODE(path.stat().st_mode) == 0o600, 'Private coordinator-owned manifest required')
    root = safe(value['rootfs']); require(root.is_dir() and root != Path('/'), 'Dedicated rootfs required')
    for name in ['proc','dev','tmp','run','home','root','workspace','opt/modelbench']:
        require((root/name).is_dir() and not (root/name).is_symlink(), 'Missing runtime mountpoint: '+name)
    require(isinstance(value['mounts'],list) and len(value['mounts']) <= 256, 'Mount count exceeded')
    seen = set()
    for row in value['mounts']:
        require(set(row)=={'source','target','writable'}, 'Unknown mount fields')
        source=safe(row['source']); info=source.stat(); target=PurePosixPath(row['target'])
        require(source != Path('/') and (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISSOCK(info.st_mode)), 'Invalid mount source')
        require(target.is_absolute() and '..' not in target.parts and str(target) not in seen, 'Duplicate/unsafe target')
        require(any(str(target)==p or str(target).startswith(p+'/') for p in ['/workspace','/run','/home/worker/.config/kilo','/opt/modelbench']+(['/opt/brave.com/brave','/sys/devices/system/cpu'] if browser else [])), 'Target outside managed locations')
        require(type(row['writable']) is bool, 'Explicit mount access required');seen.add(str(target))
    env=value['environment']; require(isinstance(env,dict) and len(env)<=64, 'Invalid environment')
    require(all(isinstance(k,str) and isinstance(v,str) and '\0' not in k+v and '=' not in k for k,v in env.items()), 'Invalid environment value')
    require(not any(k.endswith(('_KEY','_TOKEN','_PASSWORD')) or k in {'SSH_AUTH_SOCK','DBUS_SESSION_BUS_ADDRESS','LD_PRELOAD','PYTHONPATH'} for k in env), 'Inherited credential/loader environment denied')
    require(isinstance(value['argv'],list) and value['argv'] and all(isinstance(a,str) and '\0' not in a for a in value['argv']), 'Explicit argv required')
    require(value['argv'][0].startswith('/') and value['cwd']=='/workspace', 'Executable/workspace required')
    return value


LIBC=ctypes.CDLL(None,use_errno=True)


def prctl(option, a=0, b=0, c=0, d=0):
    if LIBC.prctl(option,a,b,c,d) != 0: raise OSError(ctypes.get_errno(), 'prctl failed')


def mount(source, target, filesystem=None, flags=0, data=None):
    asbytes=lambda x: None if x is None else os.fsencode(x)
    if LIBC.mount(asbytes(source),asbytes(target),asbytes(filesystem),ctypes.c_ulong(flags),asbytes(data)) != 0:
        raise OSError(ctypes.get_errno(), 'mount failed: '+str(target)+' flags='+str(flags)+' source='+str(source))


def filter_instructions(machine):
    """Deny nested namespaces; clone3 ENOSYS preserves libc's clone fallback."""
    values={'aarch64':(0xc00000b7,97,268,220,435),'x86_64':(0xc000003e,272,308,56,435)}
    require(machine in values,'Unsupported seccomp architecture')
    arch,unshare,setns,clone,clone3=values[machine]
    code=[(0x20,0,0,4),(0x15,1,0,arch),(0x06,0,0,0x80000000),(0x20,0,0,0)]
    # x32 shares AUDIT_ARCH_X86_64 but uses a syscall-number ABI flag.
    # Deny it explicitly rather than let namespace syscalls bypass number checks.
    if machine=='x86_64':code += [(0x45,0,1,0x40000000),(0x06,0,0,0x00050001)]
    for number,error in [(unshare,1),(setns,1),(clone3,38)]:code += [(0x15,0,1,number),(0x06,0,0,0x00050000|error)]
    code += [(0x15,0,3,clone),(0x20,0,0,16),(0x45,0,1,0x7e020080),(0x06,0,0,0x00050001),(0x06,0,0,0x7fff0000)]
    return code


def no_nested_namespaces():
    class Filter(ctypes.Structure):_fields_=[('code',ctypes.c_ushort),('jt',ctypes.c_ubyte),('jf',ctypes.c_ubyte),('k',ctypes.c_uint32)]
    class Program(ctypes.Structure):_fields_=[('length',ctypes.c_ushort),('filters',ctypes.POINTER(Filter))]
    instructions=filter_instructions(platform.machine());filters=(Filter*len(instructions))(*(Filter(*i) for i in instructions));program=Program(len(instructions),filters)
    if LIBC.prctl(22,2,ctypes.byref(program),0,0) != 0:raise OSError(ctypes.get_errno(),'seccomp installation failed')


def drop_identity(uid,gid,browser=False):
    prctl(38,1)  # PR_SET_NO_NEW_PRIVS
    prctl(47,4)  # PR_CAP_AMBIENT_CLEAR_ALL
    for capability in range(41):
        if LIBC.prctl(23,capability,0,0,0) == 1:prctl(24,capability)
    # Supplementary groups were cleared before creating the user namespace.
    os.setresgid(gid,gid,gid);os.setresuid(uid,uid,uid)
    prctl(1,signal.SIGKILL)
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    require(os.getuid()==uid and os.geteuid()==uid and not os.getgroups(), 'Worker identity/group drop failed')
    require(all(int(status[k].strip(),16)==0 for k in ['CapEff','CapPrm','CapInh','CapBnd','CapAmb']) and status['NoNewPrivs'].strip()=='1','Capabilities survived')
    # Brave needs its own child namespaces for its existing Chromium sandbox.
    # Its separate role retains the outer offline namespaces and dropped caps.
    if not browser:no_nested_namespaces()


def filesystem(value,root_fd,mount_fds,directory):
    mount(None,'/',flags=(1<<18)|(1<<14))  # recursively private; no propagation
    # Pre-unshare O_PATH descriptors refer to the OLD mount namespace. Validate
    # their inode identity, then resolve only reviewed paths in the NEW one.
    original=os.fstat(root_fd);current=os.stat(value['rootfs'])
    require((original.st_dev,original.st_ino)==(current.st_dev,current.st_ino),'Runtime replaced during namespace creation')
    LIBC.setfsuid(value['uid'])
    mount(value['rootfs'],directory,flags=4096)
    LIBC.setfsuid(0)
    mount(None,directory,flags=4096|32|1|2|4)  # bind remount readonly/nosuid/nodev
    for name,size,mode in [('tmp','256m','1777'),('run','16m','0755'),('home','128m','0755'),('root','1m','0700'),('dev','16m','0755')]:
        mount('tmpfs',directory+'/'+name,'tmpfs',2|4,'size='+size+',mode='+mode)
    home=Path(directory)/'home/worker';home.mkdir();os.chown(home,value['uid'],value['gid']);home.chmod(0o700)
    for name in ['null','zero','random','urandom']:
        target=Path(directory)/'dev'/name;target.touch();mount('/dev/'+name,str(target),flags=4096)
    for name,target in [('fd','/proc/self/fd'),('stdin','/proc/self/fd/0'),('stdout','/proc/self/fd/1'),('stderr','/proc/self/fd/2')]:
        (Path(directory)/'dev'/name).symlink_to(target)
    (Path(directory)/'dev/shm').mkdir();mount('tmpfs',directory+'/dev/shm','tmpfs',2|4|8,'size=64m,mode=1777')
    browser=value.get('role')=='browser'
    mount('proc',directory+'/proc','proc',2|4|8|(0 if browser else 1))
    if browser:
        # Chromium must write its own child uid/gid maps in private PID procfs.
        # Global controls remain RO/masked; no host PID tree is exposed.
        for name in ['sys','irq','fs','bus']:
            target=directory+'/proc/'+name
            if os.path.exists(target):
                mount(target,target,flags=4096)
                mount(None,target,flags=4096|32|1|2|4|8)
        for name in ['kcore','keys','timer_list','sched_debug','sysrq-trigger']:
            target=directory+'/proc/'+name
            if os.path.exists(target):
                mount(directory+'/dev/null',target,flags=4096)
                mount(None,target,flags=4096|32|1|2|4|8)
    for row,fd in zip(value['mounts'],mount_fds):
        # Private workspace directories are mode0700 for the coordinator UID.
        # setfsuid changes pathname access, while SYS_ADMIN stays only in this
        # ephemeral user namespace; restore it before creating root-owned /run.
        LIBC.setfsuid(value['uid'])
        original=os.fstat(fd);current=os.stat(row['source'])
        require((original.st_dev,original.st_ino)==(current.st_dev,current.st_ino),'Mount source replaced during namespace creation')
        if not row['target'].startswith(('/workspace','/home/worker')):LIBC.setfsuid(0)
        target=Path(directory)/row['target'].lstrip('/')
        # A symlink in a writable ancestor can never redirect a privileged mount.
        for part in (target,)+tuple(target.parents):require(not part.is_symlink(),'Mount target symlink refused')
        target.parent.mkdir(parents=True,exist_ok=True)
        info=os.fstat(fd)
        if stat.S_ISDIR(info.st_mode):target.mkdir(exist_ok=True)
        else:
            if not target.exists():target.touch()
        # Source traversal uses the mapped coordinator fsuid; destination setup
        # above uses root only for its synthetic /run and immutable runtime.
        LIBC.setfsuid(value['uid'])
        mount(row['source'],str(target),flags=4096)
        mount(None,str(target),flags=4096|32|2|4|(8 if row['target'].startswith('/sys/') else 0)|(0 if row['writable'] else 1))
        LIBC.setfsuid(0)
    if value.get('role')=='browser':
        # Make this mount namespace's root the actual root, so the existing
        # native Brave AppArmor attachment resolves at /opt/brave.com/brave.
        os.chdir(directory)
        number={'aarch64':41,'x86_64':155}[platform.machine()]
        if LIBC.syscall(number,ctypes.c_char_p(b'.'),ctypes.c_char_p(b'.oldroot'))!=0:raise OSError(ctypes.get_errno(),'browser pivot_root failed')
        os.chdir('/')
        if LIBC.umount2(ctypes.c_char_p(b'/.oldroot'),2)!=0:raise OSError(ctypes.get_errno(),'old browser root detach failed')
    else:os.chroot(directory)
    for fd in [root_fd]+mount_fds:os.close(fd)
    # The new network namespace has no interfaces except its own loopback.
    import fcntl
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
        interface=struct.pack('16sh',b'lo',1)
        fcntl.ioctl(sock.fileno(),0x8914,interface)  # SIOCSIFFLAGS IFF_UP
    drop_identity(value['uid'],value['gid'],value.get('role')=='browser')
    os.chdir(value['cwd'])
    os.execve(value['argv'][0],value['argv'],value['environment'])


def launch(value):
    require(os.getuid()==0,'Native constructor requires scoped sudo')
    uid=value['uid'];gid=value['gid'];root_fd=os.open(value['rootfs'],os.O_PATH|os.O_DIRECTORY)
    mount_fds=[os.open(row['source'],os.O_PATH) for row in value['mounts']]
    directory=tempfile.mkdtemp(prefix='bench42-ns-');os.chmod(directory,0o755)
    ready_r,ready_w=os.pipe();go_r,go_w=os.pipe();child=os.fork()
    if child==0:
        try:
            os.close(ready_r);os.close(go_w);prctl(1,signal.SIGKILL)
            os.setgroups([]);os.unshare(os.CLONE_NEWUSER);os.write(ready_w,b'1');os.close(ready_w)
            require(os.read(go_r,1)==b'1','Namespace parent disappeared');os.close(go_r)
            os.unshare(os.CLONE_NEWNS|os.CLONE_NEWPID|os.CLONE_NEWNET|os.CLONE_NEWIPC|os.CLONE_NEWUTS|os.CLONE_NEWCGROUP)
            grandchild=os.fork()
            if grandchild==0:
                prctl(1,signal.SIGKILL);filesystem(value,root_fd,mount_fds,directory)
            _,status=os.waitpid(grandchild,0);os._exit(os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 128+os.WTERMSIG(status))
        except BaseException as exc:
            print('Native constructor failed: '+str(exc),file=sys.stderr,flush=True);os._exit(2)
    os.close(ready_w);os.close(go_r)
    reaped=False
    try:
        require(os.read(ready_r,1)==b'1','Namespace creation failed');os.close(ready_r)
        for name,identifier in [('uid_map',uid),('gid_map',gid)]:
            fd=os.open('/proc/'+str(child)+'/'+name,os.O_WRONLY)
            try:os.write(fd,('0 0 1\n'+str(identifier)+' '+str(identifier)+' 1\n').encode())
            finally:os.close(fd)
        os.write(go_w,b'1');os.close(go_w)
        _,status=os.waitpid(child,0);reaped=True
        return os.waitstatus_to_exitcode(status) if os.WIFEXITED(status) else 128+os.WTERMSIG(status)
    finally:
        if not reaped:
            try:os.kill(child,signal.SIGKILL)
            except ProcessLookupError:pass
            os.waitpid(child,0)
        for fd in [root_fd]+mount_fds:os.close(fd)
        # All mounts lived only in the now-dead child mount namespace.
        os.rmdir(directory)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--sha256',required=True)
    args=parser.parse_args()
    try:return launch(validate(args.manifest,args.sha256))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print('Native namespace BLOCKED: '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
