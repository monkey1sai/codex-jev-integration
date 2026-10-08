"""Bounded fresh Development smoke: one worker, then two concurrent workers.

Only public arithmetic fixture data is sent via authenticated official CLI.
At most three worker turns and three independent review turns, one attempt each.
No installation, login, global changes, high-assurance probes or merge execution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from orchestrator.contracts import canonical, fingerprint
from orchestrator.development import NativeDevelopmentRunner, fixture_arithmetic, process_clean
from orchestrator.evidence import frozen_bytes, digest, guarded
from orchestrator.phase2 import Phase2Queue
from orchestrator.supervisor import Supervisor
from orchestrator.validators import ValidatorRegistry
from orchestrator.workspaces import fixture_repo, git, allocate

ACCEPTANCE = '''import importlib.util
from pathlib import Path
import sys
case = sys.argv[1]
if case == "preflight":
    print("NATIVE_DEVELOPMENT_READY")
    raise SystemExit(0)
cases = ["add", "multiply", "subtract"] if case == "integration" else [case]
for name in cases:
    path = Path.cwd() / "artifact" / (name + ".py")
    spec = importlib.util.spec_from_file_location("fixture_math_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fn = getattr(module, name)
    pairs = [(2, 3), (0, 0), (-5, 9), (100, -99)]
    for a, b in pairs:
        expected = {"add": a + b, "multiply": a * b, "subtract": a - b}[name]
        assert fn(a, b) == expected, (name, a, b)
print("ACCEPTANCE_PASS:" + case)
'''


def task(queue, base, case, dependencies=(), inputs=()):
    symbols = {'add': '+', 'multiply': '*', 'subtract': '-'}
    return {'schema_version': 2, 'task_id': 'dev-' + case + '-' + queue.queue_id[:8],
            'goal': 'Create artifact/' + case + '.py defining ' + case + '(a,b) returning a ' + symbols[case] + ' b. '
                    'Use native tools to make the real file. Use exactly one plain function def ' + case + '(a,b): return a ' + symbols[case] + ' b. '
                    'No annotations, decorators, imports or side effects.',
            'inputs': list(inputs), 'dependencies': list(dependencies),
            'allowed_files': ['artifact/' + case + '.py'], 'capability': 'arithmetic',
            'execution': {'role': 'worker', **queue.policy['settings']['roles']['worker'], 'native_children': 0},
            'acceptance_criteria': ['All four controller-owned arithmetic test cases pass; only assigned file changes'],
            'tests': [case], 'expected_artifacts': ['artifact/' + case + '.py'],
            'budgets': {'runtime_seconds': 180, 'attempts': 1}, 'resource_locks': [], 'base_sha': base,
            'authorization': {'external_writes': False, 'scope': 'allocated_attempt_only'},
            'review': {'required': True, 'independent': True}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--predecessor-run', type=Path)
    args = parser.parse_args()
    runtime = guarded(args.runtime)
    root = guarded(args.run_root)
    if (sys.platform != 'linux' or os.getuid() == 0 or not root.is_absolute()
            or root.parent != runtime or root.exists()):
        raise ValueError('FRESH_OWNED_ISOLATED_LINUX_RUN_REQUIRED')
    root.mkdir()
    repo, _ = fixture_repo(root)
    (repo / 'AGENTS.md').write_text(
        '# Public native development fixture\n\n'
        'Only modify task allowed_files. Use Codex native tools. Do not spawn agents.\n'
        'Do not change instructions, tests, Git metadata or access credentials, controller, other worktrees or networks.\n'
        'The controller runs pinned tests through native sandbox and independent review.\n')
    (repo / 'artifact').mkdir()
    (repo / '.tmp').mkdir()
    (repo / '.codex').mkdir()
    test_file = root / 'validator/acceptance.py'
    frozen_bytes(test_file, ACCEPTANCE.encode())
    validators = {case: {'argv': ['native-controller-pinned:' + case], 'timeout_seconds': 10}
                  for case in ('add', 'multiply', 'subtract')}
    overlay = {'routing': {'strategy': 'rules_only', 'jev_enabled': False},
               'scheduler': {'max_active': 2, 'max_attempts': 1, 'max_dispatches': 3},
               'capabilities': {'arithmetic': {'role': 'worker', 'description': 'Public pure arithmetic fixture',
                     'allowed_files': ['artifact/' + case + '.py' for case in validators],
                     'validators': list(validators)}}, 'validators': validators}
    frozen_bytes(repo / '.codex/orchestrator.json', canonical(overlay).encode())
    git(repo, 'add', '--', 'AGENTS.md', '.codex/orchestrator.json')
    git(repo, '-c', 'user.name=Local Fixture', '-c', 'user.email=fixture@localhost.invalid',
        'commit', '-m', 'test: native development fixture contract')
    base = git(repo, 'rev-parse', 'HEAD')
    database = root / 'controller/queue.sqlite'
    queue = Phase2Queue(database, repo, evidence_mode='DEVELOPMENT')
    executable = Path('/usr/bin/python3').resolve()
    registry_path = root / 'controller/validator-registry.json'
    value = {'mode': 'DEVELOPMENT', 'policy_hash': queue.policy['policy_hash'], 'validators': {
        case: {'config_hash': fingerprint(config), 'argv': [str(executable), '-I', '-B', str(test_file), case],
               'files': {str(executable): digest(executable.read_bytes()), str(test_file): digest(test_file.read_bytes())}}
        for case, config in validators.items()}}
    frozen_bytes(registry_path, canonical(value).encode())
    registry = ValidatorRegistry(queue, registry_path, digest(registry_path.read_bytes()))
    options = {'artifact_guard': fixture_arithmetic,
               'expected_stdout': {case: 'ACCEPTANCE_PASS:' + case + '\n' for case in validators}}
    runner = NativeDevelopmentRunner(queue, root, repo, runtime, registry, **options)
    receipt = {'run_id': uuid.uuid4().hex, 'mode': 'DEVELOPMENT', 'base_sha': base,
               'native_trust_authorized': True, 'max_worker_turns': 3, 'max_review_turns': 3,
               'retry_budget': 0, 'public_data_only': True, 'production_admission': 'BLOCKED_HISTORICAL_HIGH_ASSURANCE_STOPPED',
               'merge_executed': False, 'isolated_runtime_config_hash': runner.config_hash}
    if args.predecessor_run:
        predecessor = guarded(args.predecessor_run)
        if predecessor.parent != runtime or predecessor == root:
            raise ValueError('PREDECESSOR_SCOPE')
        file = predecessor / 'result.json'
        value = json.loads(file.read_bytes())
        receipt['retained_predecessor'] = {'path': str(file), 'sha256': digest(file.read_bytes()),
            'status': value['status'], 'prior_dispatches': value['provider_worker_turns'],
            'prior_attempts': [row['attempt_id'] for row in value.get('single', {}).get('queue', {}).get('tasks', [])],
            'new_attempt_authorization': 'USER_EXPLICIT_NEW_1_TO_2_ENVELOPE_NO_RETRIES'}
    frozen_bytes(root / 'envelope.json', canonical(receipt).encode())
    frozen_bytes(root / 'effective-policy.json', canonical(queue.policy).encode())
    # A harmless zero-provider command confirms native sandbox starts before a turn.
    readiness, _ = allocate(root, repo, {'attempt_id': uuid.uuid4().hex, 'task': {'base_sha': base}})
    (readiness / '.tmp').mkdir()
    frozen_bytes(readiness / 'artifact/add.py', b'def add(a,b): return a+b\n')
    settings, filesystem = runner._settings(readiness, ['artifact/preflight.py'], queue.policy['settings']['roles']['worker'], [test_file])
    command = {'argv': [str(executable), '-I', '-B', str(test_file), 'preflight'], 'timeout_seconds': 5}
    preflight = {'plan_hash': fingerprint(command), 'workspace': str(readiness), 'command': command,
                 'server_argv': runner._argv(readiness, settings, server=True), 'expected_filesystem': filesystem,
                 'check_thread_start': True, 'validator_probe': {
                     'argv': [str(executable), '-I', '-B', str(test_file), 'add'],
                     'timeout_seconds': 5, 'expected_stdout': 'ACCEPTANCE_PASS:add\n'}}
    plan_file = root / 'controller/preflight-plan.json'
    frozen_bytes(plan_file, canonical(preflight).encode())
    driver = SOURCE / 'tools/development_validator.py'
    execution = runner._run([str(executable), '-I', '-B', str(driver), str(plan_file)],
                            root / 'controller', 'preflight', readiness, 25, threading.Event())
    output = root / 'controller/preflight.jsonl'
    result = json.loads(output.read_bytes()) if output.exists() and output.stat().st_size else {}
    receipt['preflight'] = {'execution': execution, 'result': result}
    if (not process_clean(execution) or execution.get('status') != 'EXITED' or execution.get('exit_code') != 0
            or result.get('status') != 'PASS'
            or result.get('result', {}).get('stdout') != 'NATIVE_DEVELOPMENT_READY\n'):
        receipt['status'] = 'BLOCKED_NATIVE_PREFLIGHT_NO_PROVIDER'
    elif not args.execute:
        receipt['status'] = 'READY_NO_PROVIDER'
    else:
        single_task = task(queue, base, 'add')
        single_id = single_task['task_id']
        queue.enqueue([single_task])
        single = Supervisor(queue, root, repo, max_active=1, native_runner=runner, capabilities={'arithmetic'})
        receipt['single'] = single.run(max_seconds=400)
        if not all(row['state'] == 'PASSED' for row in queue.snapshot()['tasks']):
            receipt['status'] = 'BLOCKED_SINGLE_NO_RETRY'
        else:
            # Reopen controller and re-verify custody before releasing dependent DAG.
            queue = Phase2Queue(database, repo, evidence_mode='DEVELOPMENT')
            registry = ValidatorRegistry(queue, registry_path, digest(registry_path.read_bytes()))
            runner = NativeDevelopmentRunner(queue, root, repo, runtime, registry, **options)
            with queue.transaction() as db:
                row = db.execute('SELECT * FROM tasks WHERE id=?', (single_id,)).fetchone()
                manifest, sha = queue.artifacts.verified(db, row)
                queue.artifacts.bind_receipt(manifest, sha, json.loads(row['receipt']))
            receipt['restart_custody'] = {'status': 'PASS', 'artifact_manifest_hash': sha}
            artifact_sha = json.loads(row['receipt'])['artifacts']['artifact/add.py']
            inputs = [{'path': 'artifact/add.py', 'sha256': artifact_sha}]
            child_tasks = [task(queue, base, case, [single_id], inputs) for case in ('multiply', 'subtract')]
            queue.enqueue(child_tasks)
            pair = Supervisor(queue, root, repo, max_active=2, native_runner=runner, capabilities={'arithmetic'})
            receipt['pair'] = pair.run(max_seconds=600)
            intervals = []
            for row in queue.snapshot()['tasks']:
                if row['id'] in {task['task_id'] for task in child_tasks}:
                    file = root / 'controller/native-execution' / row['attempt_id'] / 'worker-execution.json'
                    value = json.loads(file.read_bytes())
                    intervals.append({'task_id': row['id'], 'attempt_id': row['attempt_id'], 'unit': value['unit'],
                                      'main_pid_observed_unix': value.get('main_pid_observed_unix'),
                                      'launcher_exited_unix': value.get('launcher_exited_unix')})
            overlap = (len(intervals) == 2 and all(item['main_pid_observed_unix'] and item['launcher_exited_unix'] for item in intervals)
                       and max(item['main_pid_observed_unix'] for item in intervals) < min(item['launcher_exited_unix'] for item in intervals))
            receipt['pair_concurrency'] = {'observed_overlap': overlap, 'intervals': intervals, 'active_cap': 2}
            receipt['status'] = 'PASS' if overlap and all(r['state'] == 'PASSED' for r in queue.snapshot()['tasks']) else 'BLOCKED_PAIR_NO_RETRY'
            if receipt['status'] == 'PASS':
                integration, _ = allocate(root, repo, {'attempt_id': uuid.uuid4().hex, 'task': {'base_sha': base}})
                (integration / '.tmp').mkdir()
                custody = {}
                with queue.transaction() as db:
                    for row in db.execute('SELECT * FROM tasks').fetchall():
                        manifest, manifest_hash = queue.artifacts.verified(db, row)
                        queue.artifacts.bind_receipt(manifest, manifest_hash, json.loads(row['receipt']))
                        for name, expected in manifest['artifacts'].items():
                            data = (queue.artifacts.root / row['attempt_id'] / name).read_bytes()
                            if digest(data) != expected:
                                raise ValueError('INTEGRATION_CUSTODY_DRIFT')
                            frozen_bytes(integration / name, data)
                            custody[name] = expected
                settings, filesystem = runner._settings(integration, [], queue.policy['settings']['roles']['worker'], [test_file])
                command = {'argv': [str(executable), '-I', '-B', str(test_file), 'integration'], 'timeout_seconds': 10}
                plan = {'plan_hash': fingerprint({'command': command, 'artifacts': custody}),
                        'workspace': str(integration), 'command': command,
                        'server_argv': runner._argv(integration, settings, server=True), 'expected_filesystem': filesystem}
                plan_file = root / 'controller/integration-plan.json'
                frozen_bytes(plan_file, canonical(plan).encode())
                execution = runner._run([str(executable), '-I', '-B', str(driver), str(plan_file)],
                                        root / 'controller', 'integration', integration, 25, threading.Event())
                result = json.loads((root / 'controller/integration.jsonl').read_bytes())
                passed = (process_clean(execution) and execution.get('status') == 'EXITED' and execution.get('exit_code') == 0
                          and result.get('status') == 'PASS'
                          and result.get('result', {}).get('stdout') == 'ACCEPTANCE_PASS:integration\n'
                          and all(digest((integration / name).read_bytes()) == expected for name, expected in custody.items())
                          and git(integration, 'rev-parse', 'HEAD') == base)
                receipt['integration'] = {'status': 'PASS' if passed else 'FAIL', 'custody': custody,
                                          'execution': execution, 'native_result': result,
                                          'merge_executed': False, 'base_ref_unchanged': git(repo, 'rev-parse', 'HEAD') == base}
                if not passed:
                    receipt['status'] = 'BLOCKED_INTEGRATION'
            receipt['queue'] = queue.snapshot()
            receipt['merge_queue'] = queue.merge_snapshot()
    receipt['provider_worker_turns'] = queue.snapshot()['budget']['used']
    frozen_bytes(root / 'result.json', canonical(receipt).encode())
    print(json.dumps({'status': receipt['status'], 'run_root': str(root),
                      'worker_dispatches': receipt['provider_worker_turns'], 'merge_executed': False}))
    return 0 if receipt['status'] in {'PASS', 'READY_NO_PROVIDER'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
