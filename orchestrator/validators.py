"""Pinned repo validator commands; execution requires actual containment.

Offline tests use fixed synthetic commands. Production is held until the
native execution boundary is verified, including worker-generated test code.
"""
import json
from pathlib import Path
import sys
import time
import uuid
from .contracts import ContractError, canonical, fingerprint
from .evidence import guarded, digest, frozen_bytes, clean_env
from .processes import bounded_run


class ValidatorRegistry:
    def __init__(self, queue, registry, sha256):
        self.queue, self.path = queue, guarded(registry)
        if self.path.resolve().is_relative_to(Path(queue.repo).resolve()):
            raise ContractError('VALIDATOR_TRUST_OUTSIDE_REPO_REQUIRED')
        from .policy import load
        self.value, actual = load(self.path)
        if actual != sha256 or set(self.value) != {'policy_hash', 'mode', 'validators'}:
            raise ContractError('VALIDATOR_TRUST_PIN')
        if self.value['policy_hash'] != queue.policy['policy_hash'] or self.value['mode'] != queue.evidence_mode:
            raise ContractError('VALIDATOR_POLICY_DRIFT')
        self.sha256 = actual
        with queue.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS validator_binding(id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT)')
            db.execute('INSERT OR IGNORE INTO validator_binding VALUES(1,?)', (sha256,))
            if db.execute('SELECT hash FROM validator_binding').fetchone()[0] != sha256:
                raise ContractError('VALIDATOR_BINDING_DRIFT')

    def plan(self, claim, workspace):
        """Verify the complete pinned command chain without launching anything."""
        self.queue.artifacts.authenticate(claim, {'VALIDATING'})
        self.queue._fresh()
        from .policy import load
        if load(self.path)[1] != self.sha256:
            raise ContractError('VALIDATOR_TRUST_DRIFT')
        plans = []
        workspace = guarded(workspace).resolve(strict=True)
        if not workspace.is_dir():
            raise ContractError('VALIDATOR_WORKSPACE')
        for name in claim['task']['tests']:
            config = self.queue.policy['settings']['validators'].get(name)
            pinned = self.value['validators'].get(name)
            if not config or not pinned or set(pinned) != {'config_hash', 'argv', 'files'} or pinned['config_hash'] != fingerprint(config):
                raise ContractError('VALIDATOR_NOT_TRUSTED')
            argv = pinned['argv']
            if (type(argv) is not list or not 1 <= len(argv) <= 256
                    or any(not isinstance(a, str) or not a or '\x00' in a or len(a) > 8192 for a in argv)
                    or not Path(argv[0]).is_absolute() or type(pinned['files']) is not dict or not pinned['files']):
                raise ContractError('VALIDATOR_ARGV')
            for path, expected in pinned['files'].items():
                if not isinstance(path, str) or not Path(path).is_absolute():
                    raise ContractError('VALIDATOR_PIN_PATH')
                target = guarded(path)
                if target.resolve().is_relative_to(workspace) or digest(target.read_bytes()) != expected:
                    raise ContractError('VALIDATOR_EXECUTABLE_DRIFT')
            if argv[0] not in pinned['files']:
                raise ContractError('VALIDATOR_EXECUTABLE_UNPINNED')
            # Literal argv only, no task interpolation, PATH lookup or shell=True.
            timeout = min(config['timeout_seconds'], claim['task']['budgets']['runtime_seconds'])
            plans.append({'validator': name, 'argv': list(argv), 'files': dict(pinned['files']),
                          'timeout_seconds': timeout, 'argv_hash': fingerprint(argv)})
        return {'queue_id': self.queue.queue_id, 'task_id': claim['task']['task_id'],
                'task_hash': claim['task_hash'], 'attempt_id': claim['attempt_id'], 'epoch': claim['epoch'],
                'policy_hash': self.queue.policy['policy_hash'], 'trusted_registry': self.sha256,
                'workspace': str(workspace), 'mode': self.queue.evidence_mode, 'commands': plans,
                'execution_authorized': False}

    def _blocked(self, claim, plan, reason):
        receipt = {'plan': plan, 'execution': 'NOT_RUN', 'admission': 'BLOCKED', 'reason': reason,
                   'controller_custody': 'UNVERIFIED', 'native_containment': 'UNVERIFIED'}
        folder = self.queue.path.parent / 'validator-admission' / claim['attempt_id']
        frozen_bytes(folder / (uuid.uuid4().hex + '.json'), canonical(receipt).encode())
        with self.queue.transaction() as db:
            self.queue._event(db, claim['task']['task_id'], 'validator_admission_blocked',
                              attempt_id=claim['attempt_id'], epoch=claim['epoch'],
                              receipt_hash=fingerprint(receipt), reason=reason)
        return receipt

    def run(self, claim, workspace, *, stop=None):
        plan = self.plan(claim, workspace)
        if self.queue.evidence_mode != 'OFFLINE_TEST':
            self._blocked(claim, plan, 'VALIDATOR_NATIVE_SANDBOX_BLOCKED')
            raise ContractError('VALIDATOR_NATIVE_SANDBOX_BLOCKED')
        evidence = []
        for command in plan['commands']:
            name, argv, timeout = command['validator'], command['argv'], command['timeout_seconds']
            if stop is not None and stop.is_set():
                self._blocked(claim, plan, 'CANCELLED_BEFORE_LAUNCH')
                self.queue.fence(claim, 'validator_stop')
                raise ContractError('VALIDATOR_FAILED:CANCELLED')
            # Recheck registry, all pins and lease immediately before each launch.
            if self.plan(claim, workspace) != plan:
                raise ContractError('VALIDATOR_PLAN_DRIFT')
            if not self.queue.heartbeat(claim, lease_seconds=min(600, timeout + 30)):
                raise ContractError('STALE_VALIDATOR')
            self.queue.artifacts.authenticate(claim, {'VALIDATING'})
            temp = guarded(self.queue.path.parent / 'validator-temp' / claim['attempt_id'] / name)
            temp.mkdir(parents=True, exist_ok=False)
            result = bounded_run(argv, cwd=workspace, timeout=timeout, stop=stop, env=clean_env(temp),
                                 before_terminate=lambda: self.queue.fence(claim, 'validator_stop'))
            row = {'validator': name, 'trusted_registry': self.sha256, 'argv_hash': fingerprint(argv),
                   'queue_id': plan['queue_id'], 'task_hash': plan['task_hash'],
                   'attempt_id': plan['attempt_id'], 'epoch': plan['epoch'],
                   'policy_hash': plan['policy_hash'], 'plan_hash': fingerprint(plan),
                   'returncode': result['returncode'], 'reason': result['reason'],
                   'process_tree_empty': result['tree_empty'], 'elapsed_seconds': result['elapsed_seconds'],
                   'stdout_sha256': digest(result['stdout']), 'stderr_sha256': digest(result['stderr']),
                   'mode': self.queue.evidence_mode}
            folder = self.queue.path.parent / 'validator-evidence' / claim['attempt_id'] / name
            frozen_bytes(folder / 'stdout.bin', result['stdout'])
            frozen_bytes(folder / 'stderr.bin', result['stderr'])
            frozen_bytes(folder / 'receipt.json', canonical(row).encode())
            if result['reason'] or not result['tree_empty'] or result['returncode'] != 0:
                raise ContractError('VALIDATOR_FAILED:' + (result['reason'] or 'EXIT_CODE'))
            evidence.append(row)
        return evidence
