"""Zero-provider lower-sandbox measurements; never claim live-tool equivalence.

Uses the official standalone command/exec API, fixed argv and existing profile.
Only public canaries may be read/written. Config, old intents and artifacts are
never modified. Run from the existing non-root isolated Linux controller.
"""
import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import queue
import re
import stat
import subprocess
import sys
import threading
import time
import uuid

if __package__ in (None,''):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.linux_containment import (classify_write, clean_path, closest_mount,
    parse_mountinfo, save_receipt, unescape)
from tools.linux_worker_smoke import CLI_SHA, BWRAP_SHA, CODE_HOST_SHA, run_cgroup, sha, tree, write_new
from tools.linux_worker_attempt import predecessor
from orchestrator.contracts import canonical, fingerprint

CONFIG_SHA='53ba30443ce753d840150c2b669285470c8ce9a85d42ece17750dfa5e24ee081'
NEW_INTENT_SHA='47dd43d71def177a121d8f96a51b57cd66fdb057fe0ce2c8172deeaa9719daee'
NEW_RESULT_SHA='4ebef86010d17358dada72983c42c5adff41a4813f6433cdd2c8d58093632c4a'
NEW_EVENTS_SHA='be26c57ce5aa97b9e34bd4afdbf40607063cfae8511de95a83f2279c7932f803'


def metadata(path):
    try:
        value=path.lstat()
        return {'realpath':os.path.realpath(path),'device':str(os.major(value.st_dev))+':'+str(os.minor(value.st_dev)),
                'inode':value.st_ino,'symlink':stat.S_ISLNK(value.st_mode),'mode':stat.S_IMODE(value.st_mode)}
    except OSError as exc:
        return {'error':exc.errno}


def check_identity(identifier,challenge):
    if str(uuid.UUID(identifier))!=identifier or not re.fullmatch('[0-9a-f]{64}',challenge):
        raise ValueError('CANONICAL_DIAGNOSTIC_ID_AND_CHALLENGE_REQUIRED')


def check_network_boundary(value,host_namespace):
    ipv4=value['route'].splitlines()
    if ipv4 and (len(ipv4)!=1 or not ipv4[0].startswith('Iface\t')):
        raise ValueError('OFFLINE_IPV4_ROUTE_NOT_VERIFIED')
    # Linux emits built-in reject entries even in a fresh empty net namespace.
    # UAPI route.h: RTF_REJECT=0x0200; RTF_UP=0x0001 denotes a usable route.
    for line in value['ipv6_route'].splitlines():
        fields=line.split()
        if (len(fields)!=10 or fields[9]!='lo' or any(fields[i]!='0'*32 for i in (0,2,4))
            or fields[1]!='00' or fields[3]!='00' or fields[5]!='ffffffff'
            or not int(fields[8],16)&0x0200 or int(fields[8],16)&0x0001):
            raise ValueError('OFFLINE_IPV6_ROUTE_NOT_VERIFIED')
    if (not re.fullmatch(r'net:\[[0-9]+\]',value['namespace']) or value['namespace']==host_namespace
        or value['uid']==0 or value['interfaces']!=['lo']
        or value['cap_eff']!='0000000000000000' or value['no_new_privs']!='1'):
        raise ValueError('OFFLINE_NETWORK_BOUNDARY_NOT_VERIFIED')


def offline_server_argv(root,evidence):
    """No filesystem mounts/permission changes; enforce zero egress before CLI."""
    parameters=canonical({'root':str(root),'evidence':str(evidence),
                          'host_network_namespace':os.readlink('/proc/self/ns/net')})
    source=('import ctypes,json,os,re,socket\nfrom pathlib import Path\n'+
            inspect.getsource(check_network_boundary)+'''
p=json.loads(PARAMETERS)
if ctypes.CDLL(None,use_errno=True).prctl(38,1,0,0,0)!=0:
    raise RuntimeError('NO_NEW_PRIVS_FAILED')
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
value={'namespace':os.readlink('/proc/self/ns/net'),'uid':os.getuid(),
       'interfaces':sorted(name for _,name in socket.if_nameindex()),
       'route':Path('/proc/net/route').read_text(),'ipv6_route':Path('/proc/net/ipv6_route').read_text(),
       'cap_eff':status['CapEff'].strip(),'no_new_privs':status['NoNewPrivs'].strip(),
       'status':'BLOCKED','cli_started':False,'filesystem_namespace_changed_by_wrapper':False}
with (Path(p['evidence'])/'offline-network-before-cli.json').open('x') as out:
    json.dump(value,out,sort_keys=True); out.flush(); os.fsync(out.fileno())
check_network_boundary(value,p['host_network_namespace'])
os.execv(p['root']+'/bin/codex',[p['root']+'/bin/codex','app-server'])
'''.replace('PARAMETERS',repr(parameters)))
    return ['/usr/bin/unshare','--user','--map-current-user','--net','--',
            '/usr/bin/python3','-I','-B','-c',source]


def open_parent(path):
    """Resolve every ancestor without following symlinks."""
    clean_path(str(path))
    directory=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for component in path.parts[1:-1]:
            following=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
            os.close(directory); directory=following
        return directory
    except Exception:
        os.close(directory)
        raise


def open_public(path,readable=False):
    """No-follow descriptor walk; inspect existing public objects without content."""
    directory=open_parent(path)
    try:
        fd=os.open(path.name,(os.O_RDONLY if readable else os.O_PATH)|os.O_NOFOLLOW|os.O_NONBLOCK,
                   dir_fd=directory)
    finally:
        os.close(directory)
    info=os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>4096:
        os.close(fd)
        raise ValueError('PUBLIC_CANARY_NOT_SMALL_SINGLE_LINK_REGULAR_FILE')
    return fd,{'realpath':str(path),'device':str(os.major(info.st_dev))+':'+str(os.minor(info.st_dev)),
               'inode':info.st_ino,'symlink':False,'mode':stat.S_IMODE(info.st_mode),
               'size':info.st_size,'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns}


def public_file(path,readback=False,expected_created=None):
    try: fd,value=open_public(path,readback)
    except FileNotFoundError: return None
    try:
        # Only a newly created, exclusive diagnostic leaf may have contents read.
        if readback:
            if expected_created is None:
                raise ValueError('EXCLUSIVE_CREATION_CUSTODY_REQUIRED')
            if any(value[k]!=expected_created[k] for k in ('device','inode','size')):
                return value  # Changed identity: no content read, classification UNKNOWN.
            data=os.read(fd,4097)
            if len(data)>4096: raise ValueError('PUBLIC_CANARY_SIZE')
            value['sha256']=hashlib.sha256(data).hexdigest()
        return value
    finally: os.close(fd)


def targets(root,identifier):
    if str(uuid.UUID(identifier))!=identifier: raise ValueError('CANONICAL_DIAGNOSTIC_ID_REQUIRED')
    name='public-mount-canary-'+identifier
    return {'credential_home':(root/'runtime-home'/name,root/'runtime-home/fake-secret-canary'),
            'controller':(root/'controller'/name,root/'controller/sentinel'),
            'other_worktree':(root/'other-worktree'/name,root/'other-worktree/sentinel'),
            'fixture_git':(root/'fixture-v2/.git'/name,root/'fixture-v2/.git/HEAD'),
            'runtime_bin':(root/'bin'/name,None),
            'private_root':(Path('/codex-public-mount-canary-'+identifier),None)}


def host_view(root,identifier,created=None):
    result={}
    for name,(path,public) in targets(root,identifier).items():
        expected=(created or {}).get(name)
        result[name]={'parent':metadata(path.parent),'file':public_file(path,readback=expected is not None,
                                                                      expected_created=expected),
                      'public_metadata':public_file(public) if public else None}
    return result


def probe_source(root,identifier,challenge,host_namespace,host_devices):
    # The fixed source is passed as one literal Python argv, not a shell string.
    imports='import hashlib,json,os,re,stat,uuid\nfrom pathlib import Path,PurePosixPath\n'
    functions='\n'.join(inspect.getsource(f) for f in (unescape,clean_path,parse_mountinfo,closest_mount,
                                                    metadata,open_parent,open_public,public_file,targets))
    parameters=canonical({'root':str(root),'id':identifier,'challenge':challenge,
                          'host_namespace':host_namespace,'host_devices':sorted(host_devices)})
    body='''
p=json.loads(PARAMETERS)
r=Path(p['root'])
ns_before=os.readlink('/proc/self/ns/mnt')
raw=Path('/proc/self/mountinfo').read_text()
parse_error=None
try: mounts=parse_mountinfo(raw)
except ValueError as exc: mounts=[]; parse_error=str(exc)
results={}
for label,(path,public) in targets(r,p['id']).items():
    record={'target':str(path),'parent':metadata(path.parent)}
    created=None
    if public:
        try:
            fd,_=open_public(public,readable=True)
            os.close(fd)  # Access test only. No existing sentinel contents read.
            record['public_read']={'access':'ALLOWED'}
        except OSError as exc: record['public_read']={'access':'DENIED','errno':exc.errno}
        except ValueError: record['public_read']={'access':'UNKNOWN','reason':'PUBLIC_IDENTITY_REJECTED'}
    # The only new top-level path is written after positive private-mount proof.
    allowed=not parse_error
    if label=='private_root' and allowed:
        mount=closest_mount(mounts,'/')
        allowed=(ns_before!=p['host_namespace'] and mount['fstype']=='tmpfs'
                 and mount['source']=='tmpfs' and mount['root']=='/'
                 and 'rw' in mount['options'] and 'rw' in mount['super_options']
                 and mount['device'] not in p['host_devices']
                 and not any(v.startswith(('shared:','master:','propagate_from:')) for v in mount['optional']))
    if not allowed:
        record['write']={'access':'NOT_RUN_MOUNT_UNPROVEN'}
    else:
        try:
            parent_fd=open_parent(path)
            try: fd=os.open(path.name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent_fd)
            finally: os.close(parent_fd)
            with os.fdopen(fd,'w+b') as target:
                target.write(('PUBLIC_CANARY_'+p['challenge']).encode())
                target.flush(); target.seek(0)
                data=target.read(4097)
                info=os.fstat(target.fileno())
                created={'device':str(os.major(info.st_dev))+':'+str(os.minor(info.st_dev)),
                         'inode':info.st_ino,'size':info.st_size,'sha256':hashlib.sha256(data).hexdigest()}
            record['write']={'access':'ALLOWED'}
        except OSError as exc: record['write']={'access':'DENIED','errno':exc.errno}
    record['file']=metadata(path)
    if record['write']['access']=='ALLOWED':
        # Hash readback uses the original O_EXCL descriptor, never a name-only reopen.
        if all(record['file'].get(k)==created[k] for k in ('device','inode')):
            record['file'].update(created)
        record['created_by_o_excl']=created
    try: record['parent_mount']=closest_mount(mounts,record['parent']['realpath'])
    except (ValueError,KeyError): record['parent_mount']=None
    results[label]=record
status=[line for line in Path('/proc/self/status').read_text().splitlines()
        if line.startswith(('CapEff:','NoNewPrivs:','Seccomp:'))]
print(json.dumps({'scope':'LOWER_SANDBOX_ONLY','diagnostic_id':p['id'],'challenge':p['challenge'],
                 'namespace_before':ns_before,'namespace_after':os.readlink('/proc/self/ns/mnt'),
                 'mountinfo':raw,'targets':results,'process_status':status,
                 'mount_parse_error':parse_error,
                 'mount_c_visible':Path('/mnt/c').exists(),'wsl_init_visible':Path('/init').exists()},sort_keys=True))
'''.replace('PARAMETERS',repr(parameters))
    return imports+functions+'\n'+body


def pinned(root,evidence):
    if sys.platform!='linux' or os.getuid()==0: raise ValueError('NON_ROOT_LINUX_REQUIRED')
    for path in (root,evidence):
        if not path.is_absolute() or path.resolve()!=path or path.stat().st_uid!=os.getuid():
            raise ValueError('OWNED_LITERAL_CONTROLLER_PATH_REQUIRED')
    pins={root/'runtime-home/config.toml':CONFIG_SHA,root/'bin/codex':CLI_SHA,
          root/'bin/codex-resources/bwrap':BWRAP_SHA,root/'bin/codex-code-mode-host':CODE_HOST_SHA,
          root/'controller/smoke-authorized-new-intent.json':NEW_INTENT_SHA,
          evidence.parent/'wsl-worker-authorized-20261008/attempt-result.json':NEW_RESULT_SHA,
          evidence.parent/'wsl-worker-authorized-20261008/worker-events.jsonl':NEW_EVENTS_SHA}
    pins.update({Path(k):v for k,v in predecessor(root,evidence.parent/'wsl-worker-20261008').items()})
    if any(path.is_symlink() or sha(path)!=digest for path,digest in pins.items()):
        raise ValueError('RUNTIME_OR_IMMUTABLE_ATTEMPT_PIN_DRIFT')
    return {str(k):v for k,v in pins.items()}


def collect(root,evidence,identifier,challenge):
    check_identity(identifier,challenge)
    env={'PATH':'/usr/bin:/bin','HOME':str(root/'runtime-home'),'CODEX_HOME':str(root/'runtime-home'),
         'LANG':'C.UTF-8','TMPDIR':str(root/'fixture-v2/.tmp')}
    argv=offline_server_argv(root,evidence)
    process=subprocess.Popen(argv,cwd=root/'fixture-v2',env=env,stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    messages=queue.Queue(maxsize=64); trace=[]
    def read():
        try:
            while line:=process.stdout.readline(262145):
                if len(line)>262144: raise ValueError('RPC_OUTPUT_CAP')
                messages.put(json.loads(line),timeout=1)
            messages.put({'error':'RPC_EOF'},timeout=1)
        except Exception: messages.put({'error':'RPC_READER_FAILED'},timeout=1)
    reader=threading.Thread(target=read,daemon=True); reader.start()
    def rpc(method,params,num):
        if method not in ('initialize','config/read','command/exec'): raise ValueError('NO_MODEL_RPC_ALLOWED')
        trace.append({'id':num,'method':method,'params':params})
        process.stdin.write(json.dumps(trace[-1])+'\n'); process.stdin.flush()
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            message=messages.get(timeout=max(.01,deadline-time.monotonic()))
            if message.get('id')==num:
                if 'error' in message: raise ValueError('RPC_REJECTED:'+str(message['error']))
                return message
            if 'error' in message: raise ValueError('RPC_READER_FAILED')
        raise TimeoutError(method)
    report={'scope':'LOWER_SANDBOX_ONLY','live_equivalence':'UNKNOWN','provider_requests':0,
            'worker_dispatches':0,'diagnostic_id':identifier,'challenge':challenge,'server_argv':argv}
    try:
        rpc('initialize',{'clientInfo':{'name':'public_mount_diagnostic','version':'1'},
                          'capabilities':{'experimentalApi':True}},1)
        network=json.loads((evidence/'offline-network-before-cli.json').read_text())
        check_network_boundary(network,os.readlink('/proc/self/ns/net'))
        report['offline_network_before_cli']=network
        report['provider_network_egress']='BLOCKED_BEFORE_CLI_START'
        report['unshare_sha256']=sha(Path('/usr/bin/unshare'))
        process.stdin.write('{"method":"initialized","params":{}}\n'); process.stdin.flush()
        effective=rpc('config/read',{'cwd':str(root/'fixture-v2'),'includeLayers':False},2)['result']['config']
        report['effective_policy']={k:effective.get(k) for k in ('permissions','default_permissions','approval_policy','approvals_reviewer','features','shell_environment_policy')}
        previous=json.loads((evidence.parent/'wsl-worker-authorized-20261008/effective-config-current.json').read_text())['effective_config']
        if report['effective_policy']!={k:previous.get(k) for k in report['effective_policy']}:
            raise ValueError('EFFECTIVE_POLICY_DRIFT')
        before=host_view(root,identifier)
        if any(v['file'] is not None for v in before.values()): raise ValueError('PUBLIC_CANARY_COLLISION')
        host_before=Path('/proc/self/mountinfo').read_text(); host_ns=os.readlink('/proc/self/ns/mnt')
        write_new(evidence/'host-before.json',before)
        source=probe_source(root,identifier,challenge,host_ns,{m['device'] for m in parse_mountinfo(host_before)})
        command=['/usr/bin/python3','-I','-B','-c',source]
        with (evidence/'fixed-probe.py').open('x') as out: out.write(source)
        response=rpc('command/exec',{'command':command,'cwd':str(root/'fixture-v2'),
                                    'permissionProfile':'worker-minimal','timeoutMs':5000,'outputBytesCap':131072},3)
        write_new(evidence/'command-response.json',response)
        result=response['result']
        if result['exitCode']!=0: raise ValueError('NATIVE_PROBE_FAILED')
        inside=json.loads(result['stdout'])
        if inside['diagnostic_id']!=identifier or inside['challenge']!=challenge: raise ValueError('DIAGNOSTIC_BINDING_FAILED')
        created={label:value['created_by_o_excl'] for label,value in inside['targets'].items()
                 if value.get('created_by_o_excl')}
        after=host_view(root,identifier,created); host_after=Path('/proc/self/mountinfo').read_text()
        with (evidence/'host-before.mountinfo').open('x') as out: out.write(host_before)
        with (evidence/'host-after.mountinfo').open('x') as out: out.write(host_after)
        with (evidence/'sandbox.mountinfo').open('x') as out: out.write(inside['mountinfo'])
        classifications={}
        for label,value in inside['targets'].items():
            observations={**value,**{k:inside[k] for k in ('namespace_before','namespace_after','mountinfo')},
                          'host_namespace':host_ns,'host_mountinfo':host_before,'host_mountinfo_after':host_after,
                          'host_before':before[label],'host_after':after[label]}
            classifications[label]=classify_write(observations)
        report.update({'host_namespace':host_ns,'inside':inside,'host_before':before,'host_after':after,
                       'classifications':classifications,'policy_sha256':fingerprint(report['effective_policy']),
                       'probe_source_sha256':sha(evidence/'fixed-probe.py'),'classification_scope':'THIS_STANDALONE_PROBE_ONLY'})
        if inside.get('mount_parse_error'): report['error']='MOUNTINFO_PARSE_FAILED:'+inside['mount_parse_error']
    except Exception as exc:
        report['error']=type(exc).__name__+':'+str(exc)
    finally:
        process.stdin.close()
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
        reader.join(timeout=2)
        report['server_exit']=process.returncode
        write_new(evidence/'rpc-trace.json',trace)
        write_new(evidence/'measurements.json',report)
    print(json.dumps({'scope':report['scope'],'provider_requests':0,'classifications':report.get('classifications'),
                      'error':report.get('error'),'server_exit':report['server_exit']}))
    return 1 if report.get('error') else 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True); parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--collect',action='store_true'); parser.add_argument('--diagnostic-id'); parser.add_argument('--challenge')
    args=parser.parse_args(); root,evidence=args.root,args.evidence
    pins=pinned(root,evidence)
    if args.collect: return collect(root,evidence,args.diagnostic_id,args.challenge)
    identifier=str(uuid.uuid4()); challenge=os.urandom(32).hex()
    check_identity(identifier,challenge)
    baseline=tree(root/'fixture-v2')
    write_new(evidence/'plan.json',{'diagnostic_id':identifier,'challenge':challenge,'pins':pins,
                                  'provider_requests':0,'scope':'LOWER_SANDBOX_ONLY','live_equivalence':'UNKNOWN'})
    env={'PATH':'/usr/bin:/bin','HOME':str(root/'runtime-home'),'CODEX_HOME':str(root/'runtime-home'),
         'LANG':'C.UTF-8','TMPDIR':str(root/'fixture-v2/.tmp')}
    command=['/usr/bin/python3','-I','-B',str(Path(__file__).resolve()),'--root',str(root),
             '--evidence',str(evidence),'--collect','--diagnostic-id',identifier,'--challenge',challenge]
    execution=run_cgroup(command,'codex-mount-diagnostic-'+identifier+'.service',20,
                         root/'fixture-v2',env,evidence,'diagnostic-controller')
    measurements=evidence/'measurements.json'
    if measurements.exists():
        report=json.loads(measurements.read_text())
    else:
        report={'scope':'LOWER_SANDBOX_ONLY','live_equivalence':'UNKNOWN',
                'error':'DIAGNOSTIC_MEASUREMENTS_UNAVAILABLE','provider_requests':0,
                'worker_dispatches':0,'diagnostic_id':identifier,'challenge':challenge}
    if pinned(root,evidence)!=pins or tree(root/'fixture-v2')!=baseline: raise ValueError('POST_DIAGNOSTIC_DRIFT')
    report['execution']=execution
    report['evidence_hashes']={p.name:sha(p) for p in evidence.iterdir() if p.is_file()}
    binding={'config_sha256':CONFIG_SHA,'cli_sha256':CLI_SHA,'bwrap_sha256':BWRAP_SHA,'host_sha256':CODE_HOST_SHA,
             'probe_sha256':report.get('probe_source_sha256'),'policy_sha256':report.get('policy_sha256'),
             'mountinfo_sha256':sha(evidence/'sandbox.mountinfo') if (evidence/'sandbox.mountinfo').exists() else None}
    digest=save_receipt(evidence/'admission-receipt.json',report,binding,diagnostic_id=identifier,challenge=challenge)
    print(json.dumps({'diagnostic_id':identifier,'scope':'LOWER_SANDBOX_ONLY','live_equivalence':'UNKNOWN',
                      'classifications':report.get('classifications'),'receipt_sha256':digest,
                      'provider_requests':0,'native_admission':'BLOCKED','error':report.get('error')},indent=2))
    return 1 if report.get('error') or execution['status']!='EXITED' or execution.get('exit_code')!=0 else 0


if __name__=='__main__':
    raise SystemExit(main())
