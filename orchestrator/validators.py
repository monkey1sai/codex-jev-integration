"""Pinned repo validator commands; execution requires actual containment.

Offline tests use fixed synthetic commands. Production is held until the
native execution boundary is verified, including worker-generated test code.
"""
import json
from pathlib import Path
import sys
import time
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

    def run(self, claim, workspace, *, stop=None):
        self.queue.artifacts.authenticate(claim, {'VALIDATING'})
        self.queue._fresh()
        from .policy import load
        if load(self.path)[1] != self.sha256:
            raise ContractError('VALIDATOR_TRUST_DRIFT')
        if self.queue.evidence_mode != 'OFFLINE_TEST':
            raise ContractError('VALIDATOR_NATIVE_SANDBOX_BLOCKED')
        evidence = []
        for name in claim['task']['tests']:
            config = self.queue.policy['settings']['validators'].get(name)
            pinned = self.value['validators'].get(name)
            if not config or not pinned or set(pinned) != {'config_hash', 'argv', 'files'} or pinned['config_hash'] != fingerprint(config):
                raise ContractError('VALIDATOR_NOT_TRUSTED')
            argv = pinned['argv']
            if not isinstance(argv, list) or not argv or not Path(argv[0]).is_absolute() or not pinned['files']:
                raise ContractError('VALIDATOR_ARGV')
            for path, expected in pinned['files'].items():
                target = guarded(path)
                if target.resolve().is_relative_to(Path(workspace).resolve()) or digest(target.read_bytes()) != expected:
                    raise ContractError('VALIDATOR_EXECUTABLE_DRIFT')
            if argv[0] not in pinned['files']:
                raise ContractError('VALIDATOR_EXECUTABLE_UNPINNED')
            # Literal argv only, no task interpolation, PATH lookup or shell=True.
            timeout = min(config['timeout_seconds'], claim['task']['budgets']['runtime_seconds'])
            if not self.queue.heartbeat(claim, lease_seconds=min(600, timeout + 30)):
                raise ContractError('STALE_VALIDATOR')
            self.queue.artifacts.authenticate(claim, {'VALIDATING'})
            temp = guarded(self.queue.path.parent / 'validator-temp' / claim['attempt_id'] / name)
            temp.mkdir(parents=True, exist_ok=False)
            result = bounded_run(argv, cwd=workspace, timeout=timeout, stop=stop, env=clean_env(temp),
                                 before_terminate=lambda: self.queue.fence(claim, 'validator_stop'))
            row = {'validator': name, 'trusted_registry': self.sha256, 'argv_hash': fingerprint(argv),
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
