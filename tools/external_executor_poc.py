"""Bounded, zero-provider release exec-server experiment, not worker admission.

Only a controller launches this entry point. It has no provider credentials,
retry, local execution fallback, queue integration, or production PASS path.
The outer namespace is inspected from the controller before any modifying RPC.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.linux_containment import closest_mount, parse_mountinfo
from tools.linux_mount_diagnostics import check_network_boundary
from tools.linux_worker_smoke import (CLI_SHA, BWRAP_SHA, sha, tree, write_new,
                                     run_cgroup, check_resource_limits)

BOOTSTRAP = '''import ctypes,json,os,sys
if ctypes.CDLL(None,use_errno=True).prctl(38,1,0,0,0)!=0: raise RuntimeError("NNP_FAILED")
print(json.dumps({"ready":sys.argv[1]}),flush=True)
if sys.stdin.buffer.read(1)!=b"G": raise RuntimeError("GATE_CLOSED")
os.execv("/runtime/codex",["/runtime/codex","exec-server","--listen","stdio","--concurrent-requests","1","--exit-on-stdin-close","--strict-config"])
'''
POLICY = {'scope': 'EXTERNAL_EXEC_SERVER_ONLY', 'provider': False,
          'host_writes': ['/workspace'], 'private_writes': ['/scratch'],
          'root': 'readonly_private_tmpfs', 'network': 'new_offline_namespace',
          'local_fallback': False, 'worker_admission': 'BLOCKED'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def final_verdict(report, execution, changed):
    """A partial observation never overrides failed process containment cleanup."""
    try:
        check_resource_limits(execution.get('kernel_resource_limits'))
        if (report.get('status') != 'EXEC_SERVER_SUBSET_VERIFIED' or report.get('server_exit') != 0
            or execution.get('status') != 'EXITED' or execution.get('exit_code') != 0
            or execution.get('output_limit_exceeded') is not False
            or execution.get('remaining_cgroup_pids') != []
            or execution.get('output_readers_closed') is not True
            or report.get('stderr_limit_exceeded') is not False
            or report.get('stderr_reader_closed') is not True
            or changed != ['mathutil.py']):
            return 'BLOCKED'
    except (ValueError, TypeError, KeyError):
        return 'BLOCKED'
    return 'EXEC_SERVER_SUBSET_VERIFIED'


def validate_boundary(value):
    """Only OS measurements made by the external controller qualify here."""
    for ns in ('mnt', 'pid', 'net', 'user'):
        if value['namespaces'][ns] == value['controller_namespaces'][ns]:
            raise ValueError('SHARED_NAMESPACE:'+ns)
    if value['exe_sha256'] != value['expected_exe_sha256']:
        raise ValueError('EXECUTABLE_MISMATCH')
    if value['policy_sha256'] != digest(POLICY):
        raise ValueError('POLICY_MISMATCH')
    mounts = parse_mountinfo(value['mountinfo'])
    root = closest_mount(mounts, '/')
    if root['fstype'] != 'tmpfs' or 'ro' not in root['options']:
        raise ValueError('PRIVATE_READONLY_ROOT_REQUIRED')
    if any(any(s.startswith(('shared:', 'master:', 'propagate_from:')) for s in m['optional']) for m in mounts):
        raise ValueError('MOUNT_PROPAGATION_NOT_PRIVATE')
    for point in ('/usr', '/runtime/codex', '/workspace/.git', '/gate.py'):
        if 'ro' not in closest_mount(mounts, point)['options']:
            raise ValueError('READONLY_BIND_REQUIRED:'+point)
    # Device and inode identity independently bind the only host write scope.
    if value['workspace_identity'] != value['host_workspace_identity']:
        raise ValueError('WORKSPACE_BIND_MISMATCH')
    for m in mounts:
        if 'rw' in m['options'] and not any(m['point'] == p or m['point'].startswith(p+'/')
                                            for p in ('/workspace', '/scratch', '/proc', '/dev')):
            raise ValueError('UNEXPECTED_WRITABLE_MOUNT:'+m['point'])
    if value['visible_forbidden_paths']:
        raise ValueError('PROTECTED_PATH_VISIBLE')
    check_network_boundary(value['network'], value['controller_namespaces']['net'])


def identity(path):
    s = path.stat()
    return [s.st_dev, s.st_ino]


def open_bootstrap_gate(value, run, challenge, stream):
    validate_boundary(value)
    write_new(run/'pre-execution-gate.json', {'challenge': challenge, 'evidence': value,
                                            'status': 'VERIFIED_EXEC_SERVER_BOOTSTRAP_ONLY'})
    stream.write(b'G'); stream.flush()


def measure(pid, workspace, forbidden, expected_exe):
    proc = Path('/proc')/str(pid)
    status = dict(line.split(':', 1) for line in (proc/'status').read_text().splitlines() if ':' in line)
    namespaces = {n: os.readlink(proc/'ns'/n) for n in ('mnt', 'pid', 'net', 'user')}
    interfaces = sorted(line.split(':')[0].strip() for line in (proc/'net/dev').read_text().splitlines()[2:])
    return {'pid': pid, 'namespaces': namespaces,
            'controller_namespaces': {n: os.readlink('/proc/self/ns/'+n) for n in namespaces},
            'mountinfo': (proc/'mountinfo').read_text(), 'cgroup': (proc/'cgroup').read_text(),
            'exe_sha256': sha(proc/'exe'), 'expected_exe_sha256': expected_exe,
            'policy_sha256': digest(POLICY), 'workspace_identity': identity(proc/'root/workspace'),
            'host_workspace_identity': identity(workspace),
            'visible_forbidden_paths': [p for p in forbidden if (proc/'root'/p.lstrip('/')).exists()],
            'network': {'namespace': namespaces['net'], 'uid': int(status['Uid'].split()[0]),
                        'interfaces': interfaces, 'route': (proc/'net/route').read_text(),
                        'ipv6_route': (proc/'net/ipv6_route').read_text(),
                        'cap_eff': status['CapEff'].strip(), 'no_new_privs': status['NoNewPrivs'].strip()}}


def outer_argv(runtime, run, info_fd, challenge):
    workspace = run/'fixture'
    return [str(runtime/'bin/codex-resources/bwrap'), '--unshare-user', '--unshare-pid',
            '--unshare-net', '--unshare-ipc', '--unshare-uts', '--cap-drop', 'ALL',
            '--die-with-parent', '--new-session', '--clearenv', '--tmpfs', '/',
            '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
            '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
            '--proc', '/proc', '--dev', '/dev', '--dir', '/runtime',
            '--ro-bind', str(runtime/'bin/codex'), '/runtime/codex',
            '--ro-bind', str(runtime/'bin/codex-resources'), '/runtime/codex-resources',
            '--ro-bind', str(run/'gate.py'), '/gate.py',
            '--bind', str(workspace), '/workspace',
            '--ro-bind', str(workspace/'.git'), '/workspace/.git',
            '--tmpfs', '/scratch', '--dir', '/scratch/home', '--dir', '/scratch/codex',
            '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'HOME', '/scratch/home',
            '--setenv', 'CODEX_HOME', '/scratch/codex', '--setenv', 'LANG', 'C.UTF-8',
            '--setenv', 'PYTHONDONTWRITEBYTECODE', '1', '--chdir', '/workspace',
            '--remount-ro', '/', '--info-fd', str(info_fd),
            '/usr/bin/python3', '-I', '-B', '/gate.py', challenge]


class Rpc:
    """Bounded stdio client. Disconnect/error never executes a local substitute."""
    ALLOWED = {'initialize', 'initialized', 'process/start', 'process/read',
               'process/terminate', 'fs/readFile', 'fs/writeFile'}

    def __init__(self, process, trace):
        self.process, self.trace, self.sequence = process, trace, 0
        self.messages = queue.Queue(maxsize=256)
        self.closed = threading.Event()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            total = 0
            while line := self.process.stdout.readline(65537):
                total += len(line)
                if len(line) > 65536 or total > 262144:
                    raise ValueError('RPC_OUTPUT_LIMIT')
                self.messages.put(json.loads(line), timeout=1)
        except Exception:
            pass
        finally:
            self.closed.set()

    def call(self, method, params, notification=False):
        if method not in self.ALLOWED:
            raise ValueError('UNLISTED_RPC')
        self.sequence += 1
        message = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if not notification:
            message['id'] = self.sequence
        self.trace.append({'send': message})
        self.process.stdin.write((json.dumps(message)+'\n').encode()); self.process.stdin.flush()
        if notification:
            return None
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            try:
                reply = self.messages.get(timeout=.1)
            except queue.Empty:
                if self.closed.is_set():
                    raise ValueError('RPC_DISCONNECTED_NO_FALLBACK')
                continue
            self.trace.append({'receive': reply})
            if reply.get('id') == message['id']:
                return reply
        raise ValueError('RPC_TIMEOUT_NO_FALLBACK')


def result(reply):
    if 'error' in reply or 'result' not in reply:
        raise ValueError('RELEASE_RPC_REJECTED:'+json.dumps(reply))
    return reply['result']


def filesystem_denied(reply):
    error = reply.get('error', {})
    if error.get('code') in (-32600, -32601, -32602):
        return False
    return bool(re.search(r'permission denied|read-only file system|no such file or directory',
                          str(error.get('message', '')), flags=re.IGNORECASE))


def process_read(rpc, process_id, seconds=8):
    deadline = time.monotonic()+seconds
    sequence = None; output = bytearray()
    while time.monotonic() < deadline:
        value = result(rpc.call('process/read', {'processId': process_id, 'afterSeq': sequence,
                                                'maxBytes': 65536, 'waitMs': 200}))
        for chunk in value['chunks']:
            output.extend(base64.b64decode(chunk['chunk'], validate=True))
        if len(output) > 65536:
            raise ValueError('PROCESS_OUTPUT_LIMIT')
        sequence = value['nextSeq']
        if value['exited']:
            return {'receipt': value, 'output': output.decode()}
    raise ValueError('PROCESS_TIMEOUT')


def start(rpc, argv):
    process_id = str(uuid.uuid4())
    # Deliberately omit optional inner sandbox: adversarial RPC must still be
    # bounded by the outer OS floor. This is not a native policy verification.
    value = result(rpc.call('process/start', {'processId': process_id, 'argv': argv,
        'cwd': '/workspace', 'env': {'PATH': '/usr/bin:/bin', 'HOME': '/scratch/home'}, 'tty': False}))
    return process_id, value


def experiment(runtime, run, challenge):
    trace = []; record = {'scope': POLICY['scope'], 'admission': 'BLOCKED',
                          'status': 'BLOCKED', 'policy': POLICY, 'challenge': challenge,
                          'live_unified_exec': 'NOT_RUN', 'live_apply_patch': 'NOT_RUN'}
    process = None; rpc = None
    stderr = run/'server-stderr.log'
    error_reader = None; error_limit = threading.Event()
    def drain_errors():
        try:
            with stderr.open('xb') as output:
                count = 0
                while chunk := process.stderr.read(4096):
                    count += len(chunk)
                    if count > 65536:
                        error_limit.set(); process.kill(); break
                    output.write(chunk)
        except Exception:
            error_limit.set()
    read_info, write_info = os.pipe()
    try:
        argv = outer_argv(runtime, run, write_info, challenge)
        record['argv'] = argv
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, pass_fds=(write_info,), env={'PATH': '/usr/bin:/bin'})
        error_reader = threading.Thread(target=drain_errors, daemon=True); error_reader.start()
        os.close(write_info); write_info = None
        # Startup is bounded by the enclosing cgroup; no gate opens on missing info.
        import select
        if not select.select([read_info], [], [], 5)[0]:
            raise ValueError('BWRAP_PID_EVIDENCE_MISSING')
        info = json.loads(os.read(read_info, 65536))
        record['bwrap_info'] = info
        if not select.select([process.stdout], [], [], 5)[0]:
            raise ValueError('BOOTSTRAP_READY_MISSING')
        if json.loads(process.stdout.readline(1024)) != {'ready': challenge}:
            raise ValueError('BOOTSTRAP_CHALLENGE_MISMATCH')
        child = int(info['child-pid'])
        forbidden = [str(run/'controller'), str(run/'credentials'), str(run/'other-worktree'),
                     str(runtime/'runtime-home'), '/mnt/c', '/init', '/sys/fs/cgroup', '/run/user']
        before = measure(child, run/'fixture', forbidden, sha(Path('/usr/bin/python3').resolve()))
        record['before'] = before
        open_bootstrap_gate(before, run, challenge, process.stdin)
        for _ in range(50):
            try:
                if sha(Path('/proc')/str(child)/'exe') == CLI_SHA:
                    break
            except OSError:
                pass
            time.sleep(.02)
        after = measure(child, run/'fixture', forbidden, CLI_SHA)
        validate_boundary(after)
        if after['namespaces'] != before['namespaces'] or after['mountinfo'] != before['mountinfo']:
            raise ValueError('EXEC_NAMESPACE_CONTINUITY_MISSING')
        record['server'] = after
        rpc = Rpc(process, trace)
        initialize = result(rpc.call('initialize', {'clientName': 'zero-provider-external-poc'}))
        record['initialize'] = initialize
        rpc.call('initialized', {}, notification=True)
        # Filesystem RPC mutation and controller-owned artifact verification.
        data = b'def add(a, b):\n    return a + b\n'
        result(rpc.call('fs/writeFile', {'path': '/workspace/mathutil.py',
            'dataBase64': base64.b64encode(data).decode(), 'followSymlinks': False}))
        if (run/'fixture/mathutil.py').read_bytes() != data:
            raise ValueError('CONTROLLER_ARTIFACT_MISMATCH')
        readback = result(rpc.call('fs/readFile', {'path': '/workspace/mathutil.py', 'followSymlinks': False}))
        if base64.b64decode(readback['dataBase64'], validate=True) != data:
            raise ValueError('FS_READBACK_MISMATCH')
        record['readback'] = readback
        record['denials'] = {}
        for path in [*forbidden, '/workspace/.git/config', '/runtime/codex']:
            response = rpc.call('fs/writeFile', {'path': path+'/write-canary' if path in forbidden else path,
                'dataBase64': base64.b64encode(b'public-canary').decode(), 'followSymlinks': False})
            record['denials'][path] = response
            if not filesystem_denied(response):
                raise ValueError('PROTECTED_WRITE_NOT_DENIED:'+path)
        record['read_denials'] = {}
        for path in forbidden:
            response = rpc.call('fs/readFile', {'path': path+'/canary', 'followSymlinks': False})
            record['read_denials'][path] = response
            if not filesystem_denied(response):
                raise ValueError('PROTECTED_READ_NOT_DENIED:'+path)
        code = 'from mathutil import add; assert add(2,3)==5; assert add(-1,1)==0; print("VALIDATOR_OK")'
        # Literal shell argv; task inputs cannot supply commands to this PoC.
        pid, launch = start(rpc, ['/bin/sh', '-c',
            '/usr/bin/python3 -I -B -c '+"'import sys; sys.path.insert(0,\"/workspace\"); "+code+"'"])
        validation = process_read(rpc, pid)
        if validation['receipt']['exitCode'] != 0 or validation['output'].strip() != 'VALIDATOR_OK':
            raise ValueError('ACTUAL_VALIDATOR_FAILED')
        record['process_start'] = launch; record['validation'] = validation
        pid, _ = start(rpc, ['/usr/bin/sleep', '30'])
        record['cancel'] = result(rpc.call('process/terminate', {'processId': pid}))
        record['cancel_read'] = process_read(rpc, pid)
        if record['cancel_read']['receipt']['exitCode'] in (None, 0):
            raise ValueError('PROCESS_CANCEL_NOT_VERIFIED')
        process.stdin.close()
        record['server_exit'] = process.wait(timeout=5)
        record['status'] = 'EXEC_SERVER_SUBSET_VERIFIED'
    except Exception as exc:
        record['error'] = type(exc).__name__+':'+str(exc)
    finally:
        if write_info is not None:
            os.close(write_info)
        os.close(read_info)
        if process is not None and process.poll() is None:
            process.kill(); process.wait(timeout=5)
        record['launcher_exit'] = process.returncode if process else None
        if rpc:
            rpc.reader.join(timeout=2)
        if error_reader:
            error_reader.join(timeout=2)
        record['stderr_limit_exceeded'] = error_limit.is_set()
        record['stderr_reader_closed'] = error_reader is not None and not error_reader.is_alive()
        write_new(run/'rpc-trace.json', trace)
        write_new(run/'executor-result.json', record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--driver', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--audit', action='store_true')
    args = parser.parse_args()
    if args.audit:
        report = json.loads((args.run_root/'custody.json').read_text())
        for name, expected in report['hashes'].items():
            if sha(args.run_root/name) != expected:
                raise ValueError('CUSTODY_HASH_MISMATCH:'+name)
        result_report = json.loads((args.run_root/'executor-result.json').read_text())
        execution = json.loads((args.run_root/'cgroup-execution.json').read_text())
        verdict = final_verdict(result_report, execution, report['changed_files'])
        if verdict != report['verdict']:
            raise ValueError('RESTART_VERDICT_MISMATCH')
        print(json.dumps({'custody': 'HASHES_VERIFIED', 'verdict': verdict,
                          'admission': 'BLOCKED', 'run_id': report['run_id']})); return
    if sys.platform != 'linux' or os.getuid() == 0:
        raise ValueError('NON_ROOT_LINUX_REQUIRED')
    runtime = args.runtime_root
    if runtime is None or runtime.resolve() != runtime or args.run_root.resolve() != args.run_root:
        raise ValueError('LITERAL_ABSOLUTE_PATH_REQUIRED')
    if sha(runtime/'bin/codex') != CLI_SHA or sha(runtime/'bin/codex-resources/bwrap') != BWRAP_SHA:
        raise ValueError('RELEASE_PIN_MISMATCH')
    if args.driver:
        intent = json.loads((args.run_root/'poc-intent.json').read_text())
        if intent['source_sha256'] != sha(Path(__file__)) or intent['policy_sha256'] != digest(POLICY):
            raise ValueError('DRIVER_BINDING_MISMATCH')
        print(json.dumps({'status': experiment(runtime, args.run_root, intent['challenge'])['status']})); return
    # Exclusive fresh synthetic run. Never reuse a worker attempt or credential home.
    args.run_root.mkdir(mode=0o700)
    fixture = args.run_root/'fixture'; fixture.mkdir(); (fixture/'.git').mkdir()
    (fixture/'.git/config').write_text('public-git-canary\n')
    (fixture/'mathutil.py').write_text('def add(a, b):\n    return a - b\n')
    for name in ('controller', 'credentials', 'other-worktree'):
        (args.run_root/name).mkdir(); (args.run_root/name/'canary').write_text('public-'+name+'\n')
    (args.run_root/'gate.py').write_text(BOOTSTRAP)
    before = tree(fixture)
    run_id = str(uuid.uuid4()); challenge = os.urandom(32).hex()
    write_new(args.run_root/'poc-intent.json', {'run_id': run_id, 'challenge': challenge,
        'source_sha256': sha(Path(__file__)), 'policy_sha256': digest(POLICY),
        'cli_sha256': CLI_SHA, 'bwrap_sha256': BWRAP_SHA, 'before': before})
    execution = run_cgroup(['/usr/bin/python3', '-I', '-B', str(Path(__file__).resolve()),
        '--driver', '--runtime-root', str(runtime), '--run-root', str(args.run_root)],
        'external-executor-'+run_id+'.service', 45, args.run_root,
        {'PATH': '/usr/bin:/bin', 'HOME': str(args.run_root), 'LANG': 'C.UTF-8',
         'PYTHONDONTWRITEBYTECODE': '1'}, args.run_root, 'cgroup')
    after = tree(fixture)
    changed = [p for p in before.keys() | after.keys() if before.get(p) != after.get(p)]
    report = json.loads((args.run_root/'executor-result.json').read_text()) if (args.run_root/'executor-result.json').exists() else {}
    if changed not in ([], ['mathutil.py']) or any((args.run_root/p/'write-canary').exists()
                                                for p in ('controller', 'credentials', 'other-worktree')):
        raise ValueError('HOST_CUSTODY_OR_SCOPE_VIOLATION')
    verdict = final_verdict(report, execution, changed)
    write_new(args.run_root/'custody.json', {'run_id': run_id, 'admission': 'BLOCKED',
        'observed_result': report.get('status', 'BLOCKED'), 'verdict': verdict, 'execution_status': execution['status'],
        'changed_files': changed, 'artifact_sha256': sha(fixture/'mathutil.py'),
        'hashes': {str(p.relative_to(args.run_root)): sha(p) for p in args.run_root.rglob('*') if p.is_file()}})
    print(json.dumps({'run_id': run_id, 'verdict': verdict,
                      'error': report.get('error'), 'admission': 'BLOCKED'}))


if __name__ == '__main__':
    main()
