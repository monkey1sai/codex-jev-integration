"""One real-game worker and one independent review; no attempt retry or merge.

--prepare is zero inference. --execute requires immutable readiness for the
same campaign and an exclusive execution marker. All validators use native RPC.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import uuid

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from orchestrator.contracts import canonical, fingerprint, ContractError
from orchestrator.development import NativeDevelopmentRunner, process_clean
from orchestrator.evidence import digest, frozen_bytes, guarded
from orchestrator.phase2 import Phase2Queue
from orchestrator.repo_adapter import RepoAdapter, repository_scan
from orchestrator.supervisor import Supervisor
from orchestrator.validators import ValidatorRegistry
from orchestrator.workspaces import allocate, git

GAME_BASE = '805db86f67ab2be152dea8abe57ca47f4e735fb7'
BUNDLE_SHA = 'cb4c1ecbb3626c46a4c9f81f7d97b8a970462a73dd7d67053f7781e70b793602'
ALLOWED = ['scripts/zip.mjs', 'tests/zip.test.ts']
PROTECTED = ['AGENTS.md', 'CONTEXT.md', 'package.json', 'package-lock.json', 'vite.config.ts',
             'tsconfig.json', '.codex/orchestrator.json', '.codex/jev.json']
VALIDATORS = {'game_unit': {'argv': ['npm', 'test'], 'timeout_seconds': 120},
              'game_build': {'argv': ['npm', 'run', 'build'], 'timeout_seconds': 120},
              'game_acceptance': {'argv': ['controller-pinned-zip-acceptance'], 'timeout_seconds': 15}}
SESSION = {'routing': {'strategy': 'rules_only', 'jev_enabled': False},
           'scheduler': {'max_active': 1, 'max_attempts': 1, 'max_dispatches': 1},
           'capabilities': {'game_packaging': {'role': 'worker', 'description': 'Real-game ZIP packaging hardening',
               'allowed_files': ALLOWED, 'validators': list(VALIDATORS)}}, 'validators': VALIDATORS}


def task(queue):
    return {'schema_version': 2, 'task_id': 'game-zip-' + queue.queue_id[:12],
        'goal': 'Harden scripts/zip.mjs createZip filename validation and extend tests/zip.test.ts. '
                'Reject empty name, empty/dot/dot-dot segments, forward absolute path, backslash, '
                'Windows drive prefix, NUL, ill-formed Unicode, duplicate encoded names and UTF-8 byte length >65535. '
                'Preserve valid nested/Unicode names, roundtrip, CRC32, deterministic bytes and empty archive. '
                'Do not add case-folding, NFC normalization or Windows device-name policy. '
                'Read scripts/zip.d.mts and tsconfig.json as readonly context: createZip is declared to return Uint8Array. '
                'Keep that public contract; use DataView and TextDecoder in TypeScript tests, not Buffer-only readUInt methods or toString(encoding). '
                'First add one real negative Vitest regression and run only tests/zip.test.ts to observe its expected failing assertion; '
                'then fix source and extend boundary cases within the SAME turn recovery budget (3 failures/60s). '
                'Use node --v8-pool-size=2 node_modules/vitest/vitest.mjs run tests/zip.test.ts --configLoader native --maxWorkers 1 --no-file-parallelism --pool threads. '
                'Before completing the SAME turn run node --v8-pool-size=2 node_modules/typescript/bin/tsc --noEmit, '
                'and fix any ordinary TypeScript error within the existing recovery budget. '
                'Node is on PATH. Use Code Mode tools. Do not run npm install, full suite or Vite Build; Controller runs them. '
                'Do not change gameplay/assets/Unity/config/instructions or other files. Keep existing tests.',
        'inputs': [], 'dependencies': [], 'allowed_files': ALLOWED, 'capability': 'game_packaging',
        'execution': {'role': 'worker', **queue.policy['settings']['roles']['worker'], 'native_children': 0},
        'acceptance_criteria': ['Controller-owned ZIP positive/negative/boundary cases pass',
            'All game Vitest tests and tsc/Vite build pass; only two allowed files change',
            'Independent review PASS; no merge; no gameplay or visual changes'],
        'tests': list(VALIDATORS), 'expected_artifacts': ALLOWED,
        'budgets': {'runtime_seconds': 300, 'attempts': 1}, 'resource_locks': [], 'base_sha': GAME_BASE,
        'authorization': {'external_writes': False, 'scope': 'allocated_attempt_only'},
        'review': {'required': True, 'independent': True}}


def native_check(runner, workspace, folder, name, argv, *, write=False, role='worker'):
    expected_role = runner.queue.policy['settings']['roles'][role]
    settings, fs = runner._settings(workspace, ALLOWED if write else [], expected_role, [argv[0]])
    command = {'argv': argv, 'timeout_seconds': 120}
    plan = {'plan_hash': fingerprint(command), 'workspace': str(workspace), 'command': command,
            'server_argv': runner._argv(workspace, settings, server=True), 'expected_filesystem': fs,
            'check_thread_start': name in {'readiness', 'review-readiness'}}
    path = folder / (name + '-plan.json')
    frozen_bytes(path, canonical(plan).encode())
    driver = SOURCE / 'tools/development_validator.py'
    result = runner._run([str(Path('/usr/bin/python3').resolve()), '-I', '-B', str(driver), str(path)],
                         folder, name, workspace, 135, threading.Event())
    data = json.loads((folder / (name + '.jsonl')).read_bytes())
    if (not process_clean(result) or result['status'] != 'EXITED' or result['exit_code'] != 0
            or data.get('status') != 'PASS' or data['result']['exitCode'] != 0):
        raise ContractError('ZERO_PROVIDER_CHECK_FAILED:' + name)
    observed = data['effective_config']
    if (observed.get('model') != expected_role['model']
            or observed.get('model_reasoning_effort') != expected_role['reasoning_effort']
            or observed.get('approvals_reviewer') != 'auto_review'):
        raise ContractError('ZERO_PROVIDER_ROLE_MISMATCH:' + name)
    if plan['check_thread_start']:
        started = next(item['result'] for item in data['trace'] if item.get('id') == 4 and 'result' in item)
        if (started.get('model') != expected_role['model']
                or started.get('reasoningEffort') != expected_role['reasoning_effort']
                or started.get('approvalPolicy') != 'never'
                or started.get('approvalsReviewer') != 'auto_review'):
            raise ContractError('ZERO_PROVIDER_SESSION_MISMATCH:' + name)
    return {'execution': result, 'native': data}


def build_argv(node):
    # Literal argv composition, not a shell or an untrusted task command.
    # configLoader native avoids writes to readonly node_modules/.vite-temp.
    return [str(node), '--v8-pool-size=2', '-e', "const{spawnSync}=require('node:child_process');for(const a of "
            "[['--v8-pool-size=2','node_modules/typescript/bin/tsc'],['--v8-pool-size=2','node_modules/vite/bin/vite.js','build','--configLoader','native','--outDir','.tmp/build']])"
            "{const r=spawnSync(process.execPath,a,{stdio:'inherit'});if(r.error||r.status!==0)process.exit(r.status||1)}"]


def open_runner(root, runtime):
    adapter = RepoAdapter(root)
    queue = Phase2Queue(root / 'controller/queue.sqlite', adapter.repo, session=SESSION, evidence_mode='DEVELOPMENT')
    path = root / 'controller/validator-registry.json'
    registry = ValidatorRegistry(queue, path, digest(path.read_bytes()))
    runner = NativeDevelopmentRunner(queue, root, adapter.repo, runtime, registry, repo_adapter=adapter,
        expected_stdout={'game_acceptance': 'GAME_ZIP_ACCEPTANCE_PASS:16_negative+2_duplicate+5_roundtrip+2_maximum+empty_archive\n'})
    return queue, adapter, runner


def prepare(args):
    root, runtime, prep = guarded(args.run_root), guarded(args.runtime), guarded(args.prep)
    if (sys.platform != 'linux' or os.getuid() == 0 or root.parent != runtime or root.exists()):
        raise ContractError('FRESH_OWNED_LINUX_CAMPAIGN_REQUIRED')
    if digest(guarded(args.bundle).read_bytes()) != BUNDLE_SHA:
        raise ContractError('GAME_BUNDLE_PIN')
    root.mkdir()
    (root / 'controller').mkdir()
    for name in ('controller-git-hooks', 'controller-git-template'):
        (root / name).mkdir()
    repo = root / 'source-repo'
    # No network/remotes fetched; bundle captures the exact authorized game HEAD.
    clone = subprocess.run(['git', '-c', 'core.hooksPath=' + str(root / 'controller-git-hooks'),
        '-c', 'init.templateDir=' + str(root / 'controller-git-template'), 'clone', '--no-hardlinks',
        '--no-checkout', str(args.bundle), str(repo)], capture_output=True, timeout=60)
    if clone.returncode:
        raise ContractError('LOCAL_BUNDLE_CLONE_FAILED')
    dependencies = root / 'controller/dependencies'
    # npm preparation was outside Worker, ignore-scripts, lockfile pinned.
    shutil.copytree(prep / 'dependencies/node_modules', dependencies, symlinks=False)
    node = prep / 'node-v22.22.0-linux-x64/bin/node'
    # The first marker permits only this campaign's controlled Git helper.
    frozen_bytes(root / 'controller/repo-adapter.json', canonical({
        'mode': 'DEVELOPMENT_REPO', 'repo': str(repo), 'source': 'monkey1sai/changshan-longdan',
        'base_sha': GAME_BASE, 'bundle_sha256': BUNDLE_SHA, 'allowed_files': ALLOWED,
        'node': str(node), 'node_sha256': digest(node.read_bytes()), 'dependencies': str(dependencies),
        'dependency_hashes': repository_scan(dependencies), 'protected_hashes': {
            name: digest(Path('/mnt/c/Repos/changshan-longdan', name).read_bytes()) for name in PROTECTED}}).encode())
    git(repo, 'checkout', '--detach', GAME_BASE)
    adapter = RepoAdapter(root)
    queue = Phase2Queue(root / 'controller/queue.sqlite', repo, session=SESSION, evidence_mode='DEVELOPMENT')
    acceptance = root / 'controller/game_repo_acceptance.mjs'
    frozen_bytes(acceptance, (SOURCE / 'tools/game_repo_acceptance.mjs').read_bytes())
    commands = {'game_unit': [str(node), '--v8-pool-size=2', 'node_modules/vitest/vitest.mjs', 'run', '--configLoader', 'native', '--maxWorkers', '1', '--no-file-parallelism', '--pool', 'threads'],
                'game_build': build_argv(node), 'game_acceptance': [str(node), str(acceptance)]}
    registry = {'mode': 'DEVELOPMENT', 'policy_hash': queue.policy['policy_hash'], 'validators': {
        name: {'config_hash': fingerprint(config), 'argv': commands[name], 'files': {
            str(node): digest(node.read_bytes()), str(acceptance): digest(acceptance.read_bytes())}}
        for name, config in VALIDATORS.items()}}
    frozen_bytes(root / 'controller/validator-registry.json', canonical(registry).encode())
    queue, adapter, runner = open_runner(root, args.runtime)
    envelope = {'campaign_id': root.name, 'baseline_controller': 'e966826a9e772ad22448a88f43adbc236b63f19d',
        'game_base': GAME_BASE, 'worker_budget': 1, 'review_budget': 1, 'attempt_retry': 0,
        'destination': 'Official Codex provider via existing authenticated Linux CLI',
        'purpose': 'Public game ZIP hardening and independent review',
        'allowed_operations': ['one Worker turn', 'one readonly Review turn', 'native validators', 'local checkpoints'],
        'data_transmitted': 'Public tracked game source, scoped task, diff and validation evidence',
        'forbidden': ['Global changes', 'secret contents', 'Jev', 'push', 'PR', 'merge', 'new attempt retry'],
        'stop_conditions': ['fatal Failure Policy', 'UNKNOWN', 'required validation/review failed'],
        'adapter_hash': adapter.hash, 'policy_hash': queue.policy['policy_hash']}
    frozen_bytes(root / 'envelope.json', canonical(envelope).encode())
    frozen_bytes(root / 'effective-policy.json', canonical(queue.policy).encode())
    workspace, _ = allocate(root, repo, {'attempt_id': uuid.uuid4().hex, 'task': {'base_sha': GAME_BASE}})
    (workspace / '.tmp').mkdir()
    adapter.prepare(workspace)
    before = adapter.scan(workspace, ignore_scratch=True)
    results = {}
    try:
        results['readiness'] = native_check(runner, workspace, root / 'controller', 'readiness',
            [str(Path('/usr/bin/python3').resolve()), '-c', 'print("GAME_NATIVE_READY")'], write=True)
        results['review_readiness'] = native_check(runner, workspace, root / 'controller', 'review-readiness',
            [str(Path('/usr/bin/python3').resolve()), '-c', 'print("GAME_REVIEW_READY")'], role='reviewer')
        results['baseline_unit'] = native_check(runner, workspace, root / 'controller', 'baseline-unit', commands['game_unit'])
        results['baseline_build'] = native_check(runner, workspace, root / 'controller', 'baseline-build', commands['game_build'])
        if before != adapter.scan(workspace, ignore_scratch=True):
            raise ContractError('ZERO_PROVIDER_SCOPE_DRIFT')
        results['status'] = 'READY_ZERO_PROVIDER'
        results['baseline_tree_hash'] = fingerprint(before)
    except Exception as error:
        results.update(status='BLOCKED_ZERO_PROVIDER', reason=str(error))
    results.update(worker_dispatches=0, review_turns=0, merge_executed=False,
                   campaign_id=root.name, adapter_hash=adapter.hash, policy_hash=queue.policy['policy_hash'],
                   native_config_hash=runner.config_hash, envelope_hash=fingerprint(envelope))
    frozen_bytes(root / 'preflight.json', canonical(results).encode())
    print(json.dumps({'campaign_id': root.name, 'status': results['status']}))
    return 0 if results['status'] == 'READY_ZERO_PROVIDER' else 1


def execute(args):
    root = guarded(args.run_root)
    if json.loads((root / 'preflight.json').read_bytes())['status'] != 'READY_ZERO_PROVIDER':
        raise ContractError('ZERO_PROVIDER_READINESS_REQUIRED')
    queue, adapter, runner = open_runner(root, args.runtime)
    verify_readiness(root, queue, adapter, runner)
    if queue.snapshot()['tasks']:
        raise ContractError('CAMPAIGN_ALREADY_ENQUEUED_NO_RETRY')
    frozen_bytes(root / 'execute-once.json', canonical({'authorization': 'USER_ONE_WORKER_ONE_REVIEW',
        'adapter_hash': adapter.hash, 'policy_hash': queue.policy['policy_hash'], 'preflight_hash': digest((root / 'preflight.json').read_bytes())}).encode())
    queue.enqueue([task(queue)])
    supervisor = Supervisor(queue, root, adapter.repo, max_active=1, native_runner=runner, capabilities={'game_packaging'})
    result = supervisor.run(max_seconds=600)
    result.update(campaign_id=root.name, status='PASS' if all(t['state'] == 'PASSED' for t in queue.snapshot()['tasks']) else 'BLOCKED_NO_RETRY',
                  worker_dispatches=queue.snapshot()['budget']['used'], review_turns=0, attempt_retry=0)
    with queue.transaction() as db:
        result['review_turns'] = db.execute('SELECT count(*) FROM development_review_dispatch').fetchone()[0]
    if result['status'] == 'PASS':
        reopened, _, _ = open_runner(root, args.runtime)
        with reopened.transaction() as db:
            row = db.execute('SELECT * FROM tasks').fetchone()
            manifest, sha = reopened.artifacts.verified(db, row)
            reopened.artifacts.bind_receipt(manifest, sha, json.loads(row['receipt']))
            result['restart_custody'] = {'status': 'PASS', 'manifest_hash': sha}
        result['merge_queue'] = reopened.merge_snapshot()
    frozen_bytes(root / 'result.json', canonical(result).encode())
    print(json.dumps({k: result[k] for k in ('campaign_id', 'status', 'worker_dispatches', 'review_turns', 'merge_executed')}))
    return 0 if result['status'] == 'PASS' else 1


def verify_readiness(root, queue, adapter, runner):
    envelope = json.loads((root / 'envelope.json').read_bytes())
    ready = json.loads((root / 'preflight.json').read_bytes())
    if (ready.get('status') != 'READY_ZERO_PROVIDER' or ready.get('envelope_hash') != fingerprint(envelope)
            or any(v.get('campaign_id') != root.name or v.get('adapter_hash') != adapter.hash
                   or v.get('policy_hash') != queue.policy['policy_hash'] for v in (ready, envelope))
            or ready.get('native_config_hash') != runner.config_hash):
        raise ContractError('REPO_READINESS_BINDING_DRIFT')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--prep', type=Path)
    args = parser.parse_args()
    if args.prepare == args.execute:
        parser.error('choose exactly one phase')
    raise SystemExit(prepare(args) if args.prepare else execute(args))
