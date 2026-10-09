"""Compose existing native Development components for a pinned multi-task repo.

Does not clone, raise capacity, install configuration or authorize inference.
An operator must prepare a fresh owned root/session/adapter/tasks/registry and
separately authorize exact budgets before --execute. --prepare has zero inference.
"""
import argparse
import json
from pathlib import Path
import sys
import threading
import uuid

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from orchestrator.contracts import ContractError, canonical, fingerprint
from orchestrator.development import NativeDevelopmentRunner
from orchestrator.evidence import digest, frozen_bytes, guarded
from orchestrator.phase2 import Phase2Queue
from orchestrator.policy import load
from orchestrator.repo_adapter import RepoAdapter
from orchestrator.supervisor import Supervisor
from orchestrator.tasks import validate_tasks
from orchestrator.validators import ValidatorRegistry
from orchestrator.workspaces import allocate
from tools.game_repo_campaign import native_check


def check_contracts(queue, adapter, tasks):
    if not adapter.campaign or set(adapter.campaign['tasks']) != {t['task_id'] for t in tasks}:
        raise ContractError('CAMPAIGN_TASK_SET')
    validate_tasks(tasks, queue.policy)
    for task in tasks:
        adapter.authorize_task(task)
    adapter.bind(queue, adapter.root, adapter.repo)


def open_campaign(root, runtime):
    adapter = RepoAdapter(root)
    session, _ = load(root / 'controller/session.json')
    tasks, tasks_hash = load(root / 'controller/tasks.json', max_bytes=2 * 1024 * 1024)
    isolation_path = root / 'controller/failure-isolation.json'
    isolation = {'mode': 'legacy_campaign', 'version': 1}
    if isolation_path.exists():
        isolation, _ = load(isolation_path)
        if (type(isolation) is not dict or set(isolation) != {'mode', 'version'}
                or isolation['mode'] != 'independent_tasks_v1'
                or type(isolation['version']) is not int or isolation['version'] != 1):
            raise ContractError('FAILURE_ISOLATION_SCHEMA')
    queue = Phase2Queue(root / 'controller/queue.sqlite', adapter.repo, session=session, evidence_mode='DEVELOPMENT',
                        failure_isolation=isolation['mode'])
    check_contracts(queue, adapter, tasks)
    path = root / 'controller/validator-registry.json'
    registry = ValidatorRegistry(queue, path, digest(path.read_bytes()))
    expectations, expectations_hash = load(root / 'controller/expected-stdout.json')
    oracles = {name for task in tasks for name in task['tests'] if name not in adapter.authorize_task(task)}
    if (not oracles or type(expectations) is not dict or set(expectations) != oracles
            or any(not isinstance(text, str) or not 1 <= len(text) <= 4096 for text in expectations.values())):
        raise ContractError('CAMPAIGN_ORACLE_COMPLETION_MARKERS_REQUIRED')
    runner = NativeDevelopmentRunner(queue, root, adapter.repo, runtime, registry,
                                    repo_adapter=adapter, expected_stdout=expectations)
    binding = {'campaign_id': root.name, 'adapter_hash': adapter.hash, 'tasks_hash': tasks_hash,
               'policy_hash': queue.policy['policy_hash'], 'registry_hash': registry.sha256,
               'expectations_hash': expectations_hash,
               'failure_isolation_hash': queue.failure_isolation_hash,
               'native_config_hash': runner.config_hash}
    return queue, adapter, tasks, runner, binding


def prepare(root, runtime):
    queue, adapter, tasks, runner, binding = open_campaign(root, runtime)
    if queue.snapshot()['tasks'] or (root / 'execute-once.json').exists():
        raise ContractError('FRESH_CAMPAIGN_REQUIRED')
    folder = root / 'controller/parallel-readiness'
    folder.mkdir(exist_ok=False)
    results = {}
    for n, task in enumerate(tasks):
        workspace, _ = allocate(root, adapter.repo, {'attempt_id': uuid.uuid4().hex, 'task': task})
        (workspace / '.tmp').mkdir()
        adapter.prepare(workspace)
        before = adapter.scan(workspace, ignore_scratch=True)
        results['worker-' + str(n)] = native_check(runner, workspace, folder, 'readiness-' + str(n),
            ['/usr/bin/true'], write=True, allowed_files=task['allowed_files'])
        tools_folder = folder / ('tools-' + str(n))
        tools_folder.mkdir()
        results['tools-' + str(n)] = runner.tool_readiness(workspace, tools_folder, task['execution'],
            task['allowed_files'], {**binding, 'task_hash': fingerprint(task), 'probe_nonce': uuid.uuid4().hex},
            threading.Event(), [])
        # thread/start is checked by these exact existing readiness probe names.
        if n == 0:
            results['session'] = native_check(runner, workspace, folder, 'readiness', ['/usr/bin/true'])
            results['review'] = native_check(runner, workspace, folder, 'review-readiness', ['/usr/bin/true'], role='reviewer')
        commands = runner.validators._commands(task, workspace)
        for command in commands:
            if command['validator'] in adapter.authorize_task(task):
                name = 'baseline-' + str(n) + '-' + command['validator']
                results[name] = native_check(runner, workspace, folder, name, command['argv'])
        if adapter.scan(workspace, ignore_scratch=True) != before:
            raise ContractError('READINESS_CHANGED_SOURCE')
    ready = {**binding, 'status': 'READY_ZERO_PROVIDER', 'worker_turns': 0, 'review_turns': 0,
             'checks': results, 'merge_executed': False}
    frozen_bytes(root / 'parallel-preflight.json', canonical(ready).encode())
    return ready


def execute(root, runtime, *, worker_budget, review_budget, active_cap, authorization_reference):
    queue, adapter, tasks, runner, binding = open_campaign(root, runtime)
    ready, _ = load(root / 'parallel-preflight.json', max_bytes=2 * 1024 * 1024)
    c = adapter.campaign
    if (ready.get('status') != 'READY_ZERO_PROVIDER' or any(ready.get(k) != v for k, v in binding.items())
            or queue.snapshot()['tasks'] or worker_budget != c['worker_budget'] or review_budget != c['review_budget']
            or active_cap != c['max_active'] or active_cap != queue.policy['settings']['scheduler']['max_active']
            or not isinstance(authorization_reference, str) or not 1 <= len(authorization_reference) <= 1000):
        raise ContractError('CAMPAIGN_READINESS_OR_BUDGET')
    frozen_bytes(root / 'execute-once.json', canonical({**binding, 'worker_budget': worker_budget,
        'review_budget': review_budget, 'active_cap': active_cap, 'attempt_retry': 0,
        'authorization_reference': authorization_reference,
        'authorization_assurance': 'TRUSTED_OPERATOR_REFERENCE_NOT_CRYPTOGRAPHIC_HUMAN_ATTESTATION'}).encode())
    queue.enqueue(tasks)
    result = Supervisor(queue, root, adapter.repo, max_active=active_cap, native_runner=runner,
                        capabilities={t['capability'] for t in tasks}).run(max_seconds=600)
    result.update(binding, status='BLOCKED_NO_RETRY', attempt_retry=0)
    try:
        if all(r['state'] == 'PASSED' for r in queue.snapshot()['tasks']):
            result['parallel'] = runner.parallel_evidence([t['task_id'] for t in tasks])
            if result['parallel']['status'] == 'OVERLAP':
                result['integration'] = runner.integrate([t['task_id'] for t in tasks], threading.Event())
                if result['integration']['status'] == 'PASS':
                    reopened, _, _, restarted, _ = open_campaign(root, runtime)
                    result['restart_parallel'] = restarted.parallel_evidence([t['task_id'] for t in tasks])
                    from orchestrator.merge_validation import verify_integration
                    verify_integration(reopened, result['integration']['prepared'])
                    result['status'] = 'PASS'
    except Exception as error:
        result['reason'] = str(error)
    with queue.transaction() as db:
        result['review_turns'] = db.execute('SELECT count(*) FROM development_review_dispatch').fetchone()[0]
    result.update(worker_turns=queue.snapshot()['budget']['used'], merge_queue=queue.merge_snapshot())
    frozen_bytes(root / 'parallel-result.json', canonical(result).encode())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    phase = parser.add_mutually_exclusive_group(required=True)
    phase.add_argument('--prepare', action='store_true')
    phase.add_argument('--execute', action='store_true')
    parser.add_argument('--worker-budget', type=int)
    parser.add_argument('--review-budget', type=int)
    parser.add_argument('--active-cap', type=int)
    parser.add_argument('--authorization-reference')
    args = parser.parse_args()
    root, runtime = guarded(args.root), guarded(args.runtime)
    result = (prepare(root, runtime) if args.prepare else execute(root, runtime,
        worker_budget=args.worker_budget, review_budget=args.review_budget, active_cap=args.active_cap,
        authorization_reference=args.authorization_reference))
    print(json.dumps({k: result.get(k) for k in ('campaign_id', 'status', 'worker_turns', 'review_turns', 'merge_executed')}))
    raise SystemExit(0 if result['status'] in {'PASS', 'READY_ZERO_PROVIDER'} else 1)
