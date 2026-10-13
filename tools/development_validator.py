"""One controller-pinned command through official app-server command/exec.

No inference turns, local command fallback or permission prompts. Readiness may
load a native thread without starting a turn; startup metadata HTTP is possible.
The parent owns this process tree using the existing cgroup lifecycle helper.
"""
import hashlib
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time


def public_config(config):
    """Only the native settings needed to audit admission enter durable output."""
    fields = ('default_permissions', 'approval_policy',
              'approvals_reviewer', 'model', 'model_reasoning_effort')
    # Environment values and provider/MCP configuration are deliberately omitted.
    value = {key: config.get(key) for key in fields}
    profiles = config.get('permissions')
    profile = profiles.get('worker-minimal') if isinstance(profiles, dict) else None
    if isinstance(profile, dict):
        network = profile.get('network')
        enabled = network.get('enabled') if isinstance(network, dict) else None
        value['permission_summary'] = {
            'profile': 'worker-minimal',
            'network_enabled': enabled if type(enabled) is bool else None,
            'filesystem_sha256': hashlib.sha256(json.dumps(profile.get('filesystem'),
                sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
    return value


def public_response(method, result):
    """RPC transport receipts are not a license to persist arbitrary config."""
    receipt = {'id': result.get('id')}
    if 'error' in result:
        receipt['error'] = {'classification': 'NATIVE_RPC_REJECTED'}
    elif method == 'config/read':
        receipt['result'] = {'config': public_config(result['result']['config'])}
    elif method == 'thread/start':
        started = result['result']
        receipt['result'] = {key: started.get(key) for key in
            ('model', 'reasoningEffort', 'approvalPolicy', 'approvalsReviewer')}
        receipt['result']['thread'] = {'id': started['thread']['id']}
    elif method == 'initialize':
        receipt['result'] = {'initialized': True}
    else:
        receipt['result'] = result['result']
    return receipt


def execute(plan):
    process = subprocess.Popen(plan['server_argv'], cwd=plan['workspace'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True)
    inbox = queue.Queue(maxsize=64)
    trace = []
    def read():
        try:
            for line in iter(process.stdout.readline, ''):
                if len(line) > 262144:
                    raise ValueError('RPC_OUTPUT_CAP')
                inbox.put(json.loads(line), timeout=1)
            inbox.put({'error': 'RPC_EOF'}, timeout=1)
        except Exception:
            inbox.put({'error': 'RPC_READER'}, timeout=1)
    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    def rpc(method, params, number, seconds=10):
        if method not in {'initialize', 'config/read', 'command/exec', 'thread/start'}:
            raise ValueError('RPC_NOT_ALLOWED')
        request = {'id': number, 'method': method, 'params': params}
        trace.append(request)
        process.stdin.write(json.dumps(request) + '\n')
        process.stdin.flush()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = inbox.get(timeout=max(.01, deadline - time.monotonic()))
            if result.get('id') == number:
                trace.append(public_response(method, result))
                if 'error' in result:
                    raise ValueError('NATIVE_RPC_REJECTED')
                return result['result']
            if 'error' in result:
                raise ValueError('NATIVE_RPC_EOF')
        raise TimeoutError(method)
    report = {'mode': 'DEVELOPMENT', 'local_fallback': False,
              'plan_hash': plan['plan_hash'], 'trace': trace,
              'inference_turns': 0, 'background_metadata_http': 'POSSIBLE_NATIVE_STARTUP'}
    try:
        rpc('initialize', {'clientInfo': {'name': 'development_validator', 'version': '1'},
                          'capabilities': {'experimentalApi': True}}, 1)
        process.stdin.write('{"method":"initialized","params":{}}\n')
        process.stdin.flush()
        config = rpc('config/read', {'cwd': plan['workspace'], 'includeLayers': False}, 2)['config']
        # Only public native safety/config fields enter evidence; never credentials.
        report['effective_config'] = public_config(config)
        if config.get('default_permissions') != 'worker-minimal':
            raise ValueError('NATIVE_PROFILE_MISMATCH')
        if config.get('approval_policy') != 'never':
            raise ValueError('NATIVE_APPROVAL_MISMATCH')
        permission = config['permissions']['worker-minimal']
        if permission['network']['enabled'] is not False or permission['filesystem'].get(':minimal') != 'read':
            raise ValueError('NATIVE_PERMISSION_MISMATCH')
        expected = plan['expected_filesystem']
        if permission['filesystem'] != expected:
            raise ValueError('NATIVE_FILESYSTEM_MISMATCH')
        if plan.get('check_thread_start') is True:
            # Official thread/start loads native instructions but starts no turn.
            # turn/start is deliberately absent from the RPC allowlist.
            started = rpc('thread/start', {'cwd': plan['workspace'], 'ephemeral': True,
                           'model': config['model'], 'permissions': 'worker-minimal',
                           'approvalPolicy': 'never', 'approvalsReviewer': 'auto_review',
                           'allowProviderModelFallback': False}, 4)
            report['native_session_start'] = {'thread_id': started['thread']['id'],
                                             'status': 'STARTED_NO_INFERENCE_TURN'}
        report['result'] = rpc('command/exec', {
            'command': plan['command']['argv'], 'cwd': plan['workspace'],
            'permissionProfile': 'worker-minimal', 'timeoutMs': plan['command']['timeout_seconds'] * 1000,
            'outputBytesCap': 65536}, 3, plan['command']['timeout_seconds'] + 10)
        report['status'] = 'PASS' if report['result']['exitCode'] == 0 else 'FAIL'
        if plan.get('validator_probe') and report['status'] == 'PASS':
            probe = plan['validator_probe']
            report['validator_probe'] = rpc('command/exec', {
                'command': probe['argv'], 'cwd': plan['workspace'],
                'permissionProfile': 'worker-minimal', 'timeoutMs': probe['timeout_seconds'] * 1000,
                'outputBytesCap': 65536}, 5, probe['timeout_seconds'] + 10)
            if (report['validator_probe']['exitCode'] != 0
                    or report['validator_probe']['stdout'] != probe['expected_stdout']):
                report['status'] = 'FAIL'
    except Exception as error:
        report['status'] = 'BLOCKED'
        report['error'] = type(error).__name__ + ':' + str(error)
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        thread.join(timeout=2)
        report['server_exit'] = process.returncode
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(execute(json.loads(Path(sys.argv[1]).read_text())))
