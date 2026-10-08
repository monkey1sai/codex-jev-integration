"""Bounded v2 synthetic execution through the production-shaped lifecycle.

Controller validation uses fixed code or an explicit external pinned registry.
Native launch and observed native independent review remain unavailable.
"""
import hashlib
import json
from pathlib import Path
import sys

from .contracts import ContractError, canonical, fingerprint, relative_file
from .phase2 import Phase2Queue
from .policy import compile_policy
from .processes import bounded_run
from .workspaces import allocate, fixture_repo, git, scan, write_new


def rule_route(policy, candidate_ids, *, capability, loads=None):
    """Route only pre-authorized exact capabilities; deterministic tie breaking."""
    loads = loads or {}
    legal = [key for key in candidate_ids if key in policy['settings']['capabilities'] and key == capability]
    if not legal:
        raise ContractError('NO_LEGAL_CANDIDATE')
    return {'selected_id': min(legal, key=lambda k: (loads.get(k, 0), k)),
            'source': 'deterministic', 'provider_called': False, 'executed': False}


def artifact_manifest(worktree, claim, baseline, *, general=False, ignore_scratch=False):
    task = claim['task']
    after = scan(worktree, ignore_scratch=ignore_scratch)
    changed = sorted(k for k in set(baseline) | set(after) if baseline.get(k) != after.get(k))
    if git(worktree, 'rev-parse', 'HEAD') != task['base_sha']:
        raise ContractError('WORKER_CHANGED_HEAD')
    if not changed or not set(changed) <= set(task['allowed_files']):
        raise ContractError('OUT_OF_SCOPE_DIFF')
    for item in task['inputs']:
        if after.get(item['path']) != item['sha256']:
            raise ContractError('INPUT_DRIFT')
    for name in task['expected_artifacts']:
        relative_file(name)
        if name not in task['allowed_files'] or name not in after:
            raise ContractError('EXPECTED_ARTIFACT_MISSING')
    if not general and task['tests'] != ['constant-json-v1']:
        raise ContractError('EXECUTABLE_VALIDATOR_NOT_REGISTERED')
    # This oracle is deliberately narrow; worker-generated code is never imported.
    for name in ([] if general else task['expected_artifacts']):
        content = (worktree / name).read_bytes()
        value = json.loads(content)
        if (len(content) > 4096 or type(value) is not dict or set(value) != {'answer'}
                or type(value['answer']) is not int or value['answer'] != 42):
            raise ContractError('ORACLE_MISMATCH')
    return {'task_hash': claim['task_hash'], 'attempt_id': claim['attempt_id'], 'epoch': claim['epoch'],
            'base_sha': task['base_sha'], 'changed_files': changed,
            'artifacts': {name: after[name] for name in task['expected_artifacts']},
            'validator': 'registered-general' if general else 'constant-json-v1',
            'validator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope': 'PASS', 'validation': 'PASS', 'independent_review': 'NOT_RUN',
            'evidence_kind': 'MOCK_WORKER', 'sandbox_boundary': 'UNVERIFIED'}


def mock_attempt(queue, root, repo, *, behavior='valid', timeout=5, claim=None, stop=None, validators=None):
    if type(timeout) not in (int, float) or not 0 < timeout <= 600:
        raise ContractError('RUNTIME_BOUND')
    claim = claim or queue.claim(lease_seconds=min(600, timeout + 30), capabilities={'synthetic'})
    if claim is None:
        return {'status': 'NO_READY_TASK'}
    timeout = min(timeout, claim['task']['budgets']['runtime_seconds'])
    if not queue.heartbeat(claim, lease_seconds=min(600, timeout + 30)):
        raise ContractError('STALE_LEASE')
    if not queue.start(claim):
        raise ContractError('STALE_START')
    worker = Path(__file__).with_name('mock_v2_worker.py')
    try:
        path, temp = allocate(root, repo, claim)
        snapshot = None
        if isinstance(queue, Phase2Queue):
            from .snapshots import materialize
            snapshot = materialize(queue, claim, path)
        for item in claim['task']['inputs']:
            if scan(path).get(item['path']) != item['sha256']:
                raise ContractError('INPUT_SNAPSHOT_MISSING')
        baseline = scan(path)
        argv = [sys.executable, '-I', '-S', '-B', str(worker)]
        if behavior == 'timeout':
            argv.append('--timeout')
        result = bounded_run(argv, cwd=path, stdin=canonical(claim['task']).encode(),
                             timeout=timeout, stop=stop, before_terminate=lambda: queue.fence(claim, 'process_stop'))
        if result['reason'] or result['returncode'] or not result['tree_empty']:
            queue.fence(claim, result['reason'] or 'process_failure')
            queue.cleanup(claim, tree_empty=result['tree_empty'])
            return {'status': 'REJECTED', 'reason': result['reason'], 'tree_empty': result['tree_empty']}
        if not queue.validating(claim):
            raise ContractError('STALE_RESULT')
        validation = validators.run(claim, path, stop=stop) if validators else []
        receipt = artifact_manifest(path, claim, baseline, general=validators is not None)
        receipt['validator_evidence'] = validation
        receipt['snapshot_hash'] = snapshot['snapshot_hash'] if snapshot else None
        receipt['process_tree_empty'] = result['tree_empty']
        receipt['process_boundary'] = result['process_boundary']
        receipt['returncode'] = result['returncode']
        folder = Path(root) / 'controller-artifacts' / claim['attempt_id']
        folder.mkdir(parents=True)
        receipt['artifact_manifest_hash'] = queue.artifacts.publish(claim, path, receipt['artifacts'])
        write_new(folder / 'manifest.json', receipt)
        if not queue.finish(claim, receipt, True):
            raise ContractError('STALE_PUBLICATION')
        return {'status': 'REVIEW', 'receipt_hash': fingerprint(receipt), 'attempt_id': claim['attempt_id'],
                'model_calls': 0, 'merge_executed': False}
    except BaseException:
        queue.fence(claim, 'controller_exception')
        # Recovery cannot infer cleanup from an exception or vanished PID.
        raise


def smoke(root, *, behavior='valid'):
    root = Path(root).absolute()
    source = Path(__file__).resolve().parents[1]
    if not any(root.is_relative_to(source / name) for name in ('runs', '.test-runs')):
        raise ContractError('RUN_OUTSIDE_TASK_WORKSPACE')
    for node in [root, *root.parents]:
        if node.is_symlink() or node.is_junction():
            raise ContractError('REPARSE_PATH')
    if root.exists():
        raise ContractError('RUN_OUTPUT_COLLISION')
    root.mkdir(parents=True)
    repo, base = fixture_repo(root)
    (repo / '.codex').mkdir()
    write_new(repo / '.codex/orchestrator.json', {
        'routing': {'strategy': 'rules_only', 'jev_enabled': False},
        'capabilities': {'synthetic': {'role': 'worker', 'description': 'Fixed mock data task',
                                    'allowed_files': ['result.json'], 'validators': ['constant-json-v1']}},
        'validators': {'constant-json-v1': {'argv': ['controller-owned:constant-json-v1'], 'timeout_seconds': 5}}})
    queue = Phase2Queue(root / 'controller/queue.sqlite', repo)
    execution = {'role': 'worker', **queue.policy['settings']['roles']['worker'], 'native_children': 0}
    task = {'schema_version': 2, 'task_id': 'smoke', 'goal': 'Write the fixed synthetic JSON answer 42',
            'inputs': [], 'dependencies': [], 'allowed_files': ['result.json'], 'capability': 'synthetic',
            'execution': execution, 'acceptance_criteria': ['Fixed JSON oracle succeeds'],
            'tests': ['constant-json-v1'], 'expected_artifacts': ['result.json'],
            'budgets': {'runtime_seconds': 5, 'attempts': 1}, 'resource_locks': [], 'base_sha': base,
            'authorization': {'external_writes': False, 'scope': 'allocated_attempt_only'},
            'review': {'required': True, 'independent': True}}
    queue.enqueue([task])
    result = mock_attempt(queue, root, repo, behavior=behavior, timeout=.2 if behavior == 'timeout' else 5)
    write_new(root / 'smoke-report.json', {'result': result, 'queue': queue.snapshot(),
              'merge_queue': queue.merge_snapshot(), 'effective': compile_policy(repo),
              'native_worker': 'NOT_RUN', 'independent_review': 'NOT_RUN'})
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root', required=True)
    parser.add_argument('--behavior', choices=['valid', 'timeout'], default='valid')
    args = parser.parse_args()
    print(json.dumps(smoke(args.run_root, behavior=args.behavior)))
