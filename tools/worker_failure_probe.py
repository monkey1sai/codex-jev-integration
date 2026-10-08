"""Zero-provider fault injection into the existing Development control/lifecycle.

The payload is a fixed synthetic event emitter, never Codex, Jev or model inference.
This measures controller cancellation, not native tool/sandbox equivalence.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from orchestrator.contracts import canonical, fingerprint
from orchestrator.development import NativeDevelopmentRunner, process_clean
from orchestrator.evidence import digest, frozen_bytes, guarded
from orchestrator.phase2 import Phase2Queue
from orchestrator.validators import ValidatorRegistry
from orchestrator.worker_failures import POLICY, audit_failure_log
from orchestrator.workspaces import fixture_repo, allocate, git

CASES = ('ordinary', 'permission', 'count', 'recovery_time', 'cancel', 'timeout',
         'provider_unknown', 'lease', 'callback_unknown', 'watchdog_unknown', 'cancellation_unknown', 'restart', 'database_busy', 'database_watchdog')


def emit(case, workspace):
    def event(value):
        print(canonical(value), flush=True)
    event({'type': 'thread.started', 'thread_id': str(uuid.uuid4())})
    event({'type': 'turn.started'})
    if case not in {'ordinary', 'provider_unknown'}:
        child = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
                                  '--child-marker', str(workspace / '.tmp/late-child')])
        frozen_bytes(workspace / '.tmp/pids.json', canonical({'main': os.getpid(), 'child': child.pid}).encode())
    time.sleep(.4)  # Let actual cgroup identity/resource observations become available.
    if case == 'provider_unknown':
        return 0  # Exit 0 with missing provider completion must stop, not pass.
    if case in {'ordinary', 'permission', 'count', 'recovery_time', 'callback_unknown', 'database_busy'}:
        for index in range(4 if case == 'count' else 1):
            text = 'Permission denied' if case in {'permission', 'callback_unknown', 'database_busy'} else 'python: command not found'
            frozen_bytes(workspace / '.tmp' / ('stimulus-%s.json' % index),
                         canonical({'emitted_unix': time.time(), 'index': index}).encode())
            event({'type': 'item.completed', 'item': {'id': 'fault-' + str(index),
                'type': 'command_execution', 'status': 'failed', 'command': 'python missing-fixture',
                'exit_code': 1 if case in {'permission', 'callback_unknown', 'database_busy'} else 127, 'aggregated_output': text}})
            time.sleep(.04)
    if case == 'ordinary':
        frozen_bytes(workspace / 'artifact/result.json', b'{"answer":42}\n')
        event({'type': 'item.completed', 'item': {'id': 'corrected', 'type': 'file_change', 'status': 'completed'}})
        event({'type': 'turn.completed', 'usage': {}})
        return 0
    time.sleep(3)
    frozen_bytes(workspace / '.tmp/late-main', b'NOT_STOPPED')
    event({'type': 'turn.completed', 'usage': {}})
    return 0


def make_case(root, runtime, case):
    root.mkdir()
    repo, _ = fixture_repo(root)
    (repo / '.codex').mkdir(); (repo / 'artifact').mkdir()
    overlay = {'scheduler': {'max_active': 1, 'max_dispatches': 1, 'max_attempts': 1},
        'routing': {'strategy': 'rules_only', 'jev_enabled': False},
        'capabilities': {'probe': {'role': 'worker', 'description': 'Zero-provider control fixture',
                       'allowed_files': ['artifact/result.json'], 'validators': ['never']}},
        'validators': {'never': {'argv': ['not-executed'], 'timeout_seconds': 1}}}
    frozen_bytes(repo / '.codex/orchestrator.json', canonical(overlay).encode())
    git(repo, 'add', '--', '.codex/orchestrator.json')
    git(repo, '-c', 'user.name=Local Fixture', '-c', 'user.email=fixture@localhost.invalid', 'commit', '-m', 'test: failure probe')
    base = git(repo, 'rev-parse', 'HEAD')
    queue = Phase2Queue(root / 'controller/queue.sqlite', repo, evidence_mode='DEVELOPMENT')
    role = queue.policy['settings']['roles']['worker']
    task = {'schema_version': 2, 'task_id': 'probe-' + case, 'goal': 'Zero-provider synthetic failure injection only',
        'inputs': [], 'dependencies': [], 'allowed_files': ['artifact/result.json'], 'capability': 'probe',
        'execution': {'role': 'worker', **role, 'native_children': 0}, 'acceptance_criteria': ['No Task PASS is attempted'],
        'tests': ['never'], 'expected_artifacts': ['artifact/result.json'], 'budgets': {'runtime_seconds': 2, 'attempts': 1},
        'resource_locks': [], 'base_sha': base, 'authorization': {'external_writes': False, 'scope': 'allocated_attempt_only'},
        'review': {'required': True, 'independent': True}}
    queue.enqueue([task]); claim = queue.claim(lease_seconds=3); queue.start(claim); queue.dispatch_intent(claim)
    executable = Path('/usr/bin/python3').resolve()
    registry_file = root / 'controller/registry.json'
    registry_value = {'mode': 'DEVELOPMENT', 'policy_hash': queue.policy['policy_hash'], 'validators': {
        'never': {'config_hash': fingerprint(overlay['validators']['never']), 'argv': [str(executable), '-V'],
                  'files': {str(executable): digest(executable.read_bytes())}}}}
    frozen_bytes(registry_file, canonical(registry_value).encode())
    registry = ValidatorRegistry(queue, registry_file, digest(registry_file.read_bytes()))
    runner = NativeDevelopmentRunner(queue, root, repo, runtime, registry)
    workspace, _ = allocate(root, repo, claim); (workspace / '.tmp').mkdir()
    folder = root / 'controller/execution'; folder.mkdir()
    local, shared, done = threading.Event(), threading.Event(), threading.Event()
    policy = {**POLICY, 'recovery_seconds': .25} if case == 'recovery_time' else POLICY
    monitor = runner._monitor_claim(claim, folder, local, shared, policy=policy)
    database_locked, database_release = threading.Event(), threading.Event()
    locker = None
    if case in {'database_busy', 'database_watchdog'}:
        def hold_database():
            if case == 'database_watchdog':
                time.sleep(.7)  # Acquire after the owned payload process has started.
            with queue.transaction():
                database_locked.set()
                database_release.wait(2)
        locker = threading.Thread(target=hold_database, daemon=True)
        locker.start()
        if case == 'database_busy' and not database_locked.wait(1):
            raise RuntimeError('FAULT_DATABASE_LOCK_NOT_ESTABLISHED')
    watcher = threading.Thread(target=runner._maintain_claim, args=(claim, done, monitor, local, shared), daemon=True)
    # Isolate stdout-origin contention from the separate watchdog contention case.
    if case != 'database_busy':
        watcher.start()
    timer = None
    restart_observation = None
    if case in {'cancel', 'watchdog_unknown', 'cancellation_unknown'}:
        timer = threading.Timer(.7, shared.set)
    if case == 'lease':
        timer = threading.Timer(.7, lambda: queue.fence(claim, 'zero_provider_lease_injection'))
    if case == 'restart':
        def reopen_during_execution():
            nonlocal restart_observation
            fresh = Phase2Queue(queue.path, repo, evidence_mode='DEVELOPMENT')
            expired = fresh.expired(now=time.time() + 60)  # Explicit injected lease-expiry clock.
            restart_observation = {'at': time.time(), 'expired': len(expired),
                'stale_intent_denied': not fresh.dispatch_intent(claim),
                'held': fresh.snapshot()['tasks'][0]['state'] == 'HELD'}
        timer = threading.Timer(.7, reopen_during_execution)
    if timer:
        timer.start()
    original_fence = queue.fence
    if case in {'callback_unknown', 'watchdog_unknown'}:
        def unavailable(*args, **kwargs):
            raise OSError('INJECTED_CONTROL_WRITE_FAILURE')
        queue.fence = unavailable
    # Fixed control-result injection: actually stop the owned unit, then report
    # an unknown cancellation result. Never leave processes on purpose.
    from tools import linux_worker_smoke as lifecycle
    original_run = lifecycle.subprocess.run
    if case == 'cancellation_unknown':
        def stop_unknown(argv, *args, **kwargs):
            value = original_run(argv, *args, **kwargs)
            if argv[:3] == ['/usr/bin/systemctl', '--user', 'stop']:
                return subprocess.CompletedProcess(argv, 1, b'INJECTED_UNKNOWN_STOP_RESULT', b'')
            return value
        lifecycle.subprocess.run = stop_unknown
    try:
        execution = runner._run([str(executable), '-I', '-B', str(Path(__file__).resolve()),
            '--emit-case', case, '--workspace', str(workspace)], folder, 'payload', workspace, 2, local,
            lambda: monitor.stop('NATIVE_PROCESS_STOP'), monitor=monitor)
    finally:
        queue.fence = original_fence
        lifecycle.subprocess.run = original_run
        database_release.set()
        if locker:
            locker.join(timeout=3)
        done.set()
        if case != 'database_busy':
            watcher.join(timeout=3)
        if timer:
            timer.cancel(); timer.join(timeout=2)
    status = monitor.finish()
    binding = monitor.binding
    chain = audit_failure_log(folder / 'failure-policy', binding)
    clean = process_clean(execution)
    queue.fence(claim, 'zero_provider_probe_finished')
    queue.cleanup(claim, tree_empty=clean, retry=False, provider_completion_unknown=True)
    reopened = Phase2Queue(queue.path, repo, evidence_mode='DEVELOPMENT')
    stale_denied = (not reopened.dispatch_intent(claim)
                    and not reopened.finish(claim, {'process_tree_empty': True}, True)
                    and reopened.claim(halt_on_failure=True) is None)
    late_paths = [p.name for p in (workspace / '.tmp').glob('late-*')]
    records = chain['records']
    fatal_rows = [r for r in records if r['action'] == 'STOP']
    stimulus = list((workspace / '.tmp').glob('stimulus-*.json'))
    latency = None
    if stimulus and fatal_rows:
        first = min(json.loads(p.read_bytes())['emitted_unix'] for p in stimulus)
        latency = fatal_rows[0]['observed_unix'] - first
    with reopened.transaction() as db:
        fenced_events = [json.loads(r['event']) for r in db.execute('SELECT event FROM events')
                         if json.loads(r['event']).get('event') == 'fenced']
        stop_rows = [dict(r) for r in db.execute('SELECT * FROM events')
                     if json.loads(r['event']).get('event') == 'worker_failure_stop']
    fence_order = bool(stop_rows and execution.get('stop_requested_unix')
                       and stop_rows[0]['at'] <= execution['stop_requested_unix'])
    expected = (not status['stopped'] and clean and status['recoverable_failures'] == 1) if case == 'ordinary' else status['stopped']
    reasons = {'ordinary': None, 'permission': 'PROTECTION_OR_CONTROL_FAILURE',
        'count': 'RECOVERY_COUNT_EXHAUSTED', 'recovery_time': 'RECOVERY_TIME_EXHAUSTED',
        'cancel': 'CANCELLED', 'timeout': 'TASK_TIMEOUT', 'provider_unknown': 'PROVIDER_UNKNOWN',
        'lease': 'LEASE_OR_CONTROL_UNKNOWN', 'callback_unknown': 'PROTECTION_OR_CONTROL_FAILURE',
        'watchdog_unknown': 'CANCELLED', 'cancellation_unknown': 'CANCELLED',
        'restart': 'LEASE_OR_CONTROL_UNKNOWN', 'database_busy': 'PROTECTION_OR_CONTROL_FAILURE',
        'database_watchdog': 'LEASE_OR_CONTROL_UNKNOWN'}
    expected = expected and status['reason'] == reasons[case]
    expected = (expected and stale_denied and not late_paths
                and execution.get('remaining_cgroup_pids') == [] and execution.get('output_readers_closed') is True)
    unknown_cleanup = case in {'callback_unknown', 'watchdog_unknown', 'cancellation_unknown', 'database_busy', 'database_watchdog'} or (case == 'provider_unknown' and not clean)
    if unknown_cleanup:
        expected = expected and not clean and reopened.snapshot()['tasks'][0]['state'] == 'HELD' and bool(reopened.snapshot()['locks'])
    else:
        expected = expected and clean
    if case in {'permission', 'count', 'recovery_time', 'timeout', 'cancel', 'lease', 'cancellation_unknown', 'restart'}:
        expected = expected and fence_order
    if case == 'restart':
        expected = (expected and restart_observation and restart_observation['expired'] == 1
                    and restart_observation['held'] and restart_observation['stale_intent_denied']
                    and restart_observation['at'] < execution['ended_unix'])
    if case == 'watchdog_unknown':
        expected = expected and status['control_unknown'] and status['reason'] == 'CANCELLED'
    if case in {'database_busy', 'database_watchdog'}:
        expected = expected and status['control_unknown'] and database_locked.is_set() and not locker.is_alive()
    report = {'case': case, 'status': 'PASS' if expected else 'FAIL', 'provider_turns': 0,
        'scope': 'SYNTHETIC_EVENT_CONTROLLER_AND_CGROUP_ONLY', 'native_sandbox_equivalence': 'NOT_CLAIMED',
        'claim': claim, 'failure': status, 'execution': execution, 'ledger': reopened.snapshot(),
        'failure_log': chain, 'stale_result_denied': stale_denied, 'late_markers': late_paths,
        'fault_observation_seconds': latency, 'fence_before_cgroup_stop': fence_order,
        'fenced_events': fenced_events, 'process_cleanup_verified': clean,
        'restart_observation': restart_observation, 'hard_controller_crash': 'NOT_TESTED',
        'database_lock_injected': case in {'database_busy', 'database_watchdog'},
        'watchdog_enabled': case != 'database_busy',
        'cancellation_result_injected': case == 'cancellation_unknown'}
    frozen_bytes(root / 'result.json', canonical(report).encode())
    return {key: report[key] for key in ('case', 'status', 'provider_turns', 'failure',
            'fault_observation_seconds', 'fence_before_cgroup_stop', 'process_cleanup_verified')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path); parser.add_argument('--run-root', type=Path)
    parser.add_argument('--emit-case', choices=CASES); parser.add_argument('--workspace', type=Path)
    parser.add_argument('--child-marker', type=Path)
    args = parser.parse_args()
    if args.child_marker:
        time.sleep(3.5)
        frozen_bytes(args.child_marker, b'CHILD_NOT_STOPPED')
        return 0
    if args.emit_case:
        return emit(args.emit_case, args.workspace)
    runtime, root = guarded(args.runtime), guarded(args.run_root)
    if sys.platform != 'linux' or os.getuid() == 0 or root.parent != runtime or root.exists():
        raise ValueError('FRESH_OWNED_LINUX_PROBE_REQUIRED')
    root.mkdir()
    values = []
    for case in CASES:
        value = make_case(root / case, runtime, case)
        values.append(value)
        print(json.dumps(value), flush=True)
        if value['status'] != 'PASS':
            break
    result = {'probe_id': root.name, 'scope': 'ZERO_PROVIDER_FAULT_INJECTION',
        'status': 'PASS' if len(values) == len(CASES) and all(v['status'] == 'PASS' for v in values) else 'FAIL',
        'provider_turns': 0, 'jev_calls': 0, 'cases': values}
    frozen_bytes(root / 'result.json', canonical(result).encode())
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
