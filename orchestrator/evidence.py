"""Controller-owned immutable evidence and bounded public-key verification."""
import base64
import hashlib
import os
from pathlib import Path
import tempfile
import re
import time
from .contracts import ContractError, canonical, fingerprint, relative_file
from .policy import load
from .processes import bounded_run


def digest(data):
    return hashlib.sha256(data).hexdigest()


def guarded(path):
    path = Path(path).absolute()
    for node in [path, *path.parents]:
        if node.is_symlink() or node.is_junction():
            raise ContractError('EVIDENCE_REPARSE')
    return path


def frozen_bytes(path, data):
    path = guarded(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def clean_env(temp):
    # Runtime plumbing only; no inherited secrets, Python/Git/OpenSSL injection.
    env = {k: v for k, v in os.environ.items() if k.upper() in {'SYSTEMROOT', 'WINDIR', 'COMSPEC'}}
    env.update(TEMP=str(temp), TMP=str(temp), OPENSSL_CONF=os.devnull,
               PYTHONDONTWRITEBYTECODE='1')
    return env


class ReviewTrust:
    def __init__(self, registry, sha256, controller_root, repo):
        self.path = guarded(registry)
        self.root = guarded(controller_root)
        if self.path.resolve().is_relative_to(Path(repo).resolve()):
            raise ContractError('TRUST_OUTSIDE_REVIEWED_REPO_REQUIRED')
        value, actual = load(self.path)
        if actual != sha256 or set(value) != {'openssl', 'openssl_sha256', 'reviewers'}:
            raise ContractError('TRUST_PIN_MISMATCH')
        self.sha256, self.value = actual, value
        executable = guarded(value['openssl'])
        if not Path(value['openssl']).is_absolute() or digest(executable.read_bytes()) != value['openssl_sha256']:
            raise ContractError('VERIFIER_PIN_MISMATCH')
        self.executable = executable
        if type(value['reviewers']) is not dict or not value['reviewers']:
            raise ContractError('TRUST_SCHEMA')
        for identity, record in value['reviewers'].items():
            if (not isinstance(identity, str) or type(record) is not dict
                    or set(record) != {'public_key', 'sha256', 'kind'}
                    or record['kind'] not in {'offline_fixture', 'human', 'native_attester'}):
                raise ContractError('TRUST_SCHEMA')
            key = guarded(record['public_key'])
            if key.resolve().is_relative_to(Path(repo).resolve()) or digest(key.read_bytes()) != record['sha256']:
                raise ContractError('KEY_PIN_MISMATCH')

    def verify(self, envelope):
        if type(envelope) is not dict or set(envelope) != {'payload', 'signature'}:
            raise ContractError('REVIEW_SCHEMA')
        payload = envelope['payload']
        record = self.value['reviewers'].get(payload.get('reviewer_id')) if type(payload) is dict else None
        if not record:
            raise ContractError('UNKNOWN_REVIEWER')
        if load(self.path)[1] != self.sha256 or digest(self.executable.read_bytes()) != self.value['openssl_sha256']:
            raise ContractError('TRUST_DRIFT')
        key_bytes = guarded(record['public_key']).read_bytes()
        if digest(key_bytes) != record['sha256']:
            raise ContractError('KEY_DRIFT')
        try:
            signature = base64.b64decode(envelope['signature'], validate=True)
        except (ValueError, TypeError):
            raise ContractError('INVALID_SIGNATURE') from None
        if not 64 <= len(signature) <= 1024 or len(canonical(payload).encode()) > 65536:
            raise ContractError('REVIEW_SIZE')
        self.root.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix='verify-', dir=self.root))
        frozen_bytes(folder / 'public.pem', key_bytes)
        frozen_bytes(folder / 'signature.bin', signature)
        result = bounded_run([str(self.executable), 'dgst', '-sha256', '-verify', str(folder / 'public.pem'),
                              '-signature', str(folder / 'signature.bin'), '-sigopt', 'rsa_padding_mode:pkcs1'], cwd=folder,
                             stdin=canonical(payload).encode(), timeout=5, env=clean_env(folder))
        if result['returncode'] != 0 or result['reason'] or not result['tree_empty']:
            raise ContractError('INVALID_SIGNATURE')
        return record['kind'], record['sha256']


class ArtifactStore:
    def __init__(self, queue):
        self.queue = queue
        self.root = guarded(queue.path.parent / 'artifacts')
        with queue.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS artifact_manifests(task TEXT PRIMARY KEY, attempt TEXT, epoch INTEGER, hash TEXT, manifest TEXT)')

    def authenticate(self, claim, states, *, timeout=10):
        self.queue._fresh()
        if not isinstance(claim.get('attempt_id'), str) or not re.fullmatch('[a-f0-9]{32}', claim['attempt_id']):
            raise ContractError('INVALID_ATTEMPT_ID')
        with self.queue.transaction(timeout=timeout) as db:
            if not self.queue._current(db, claim, states, time.time()):
                raise ContractError('STALE_ARTIFACT_PUBLICATION')

    def publish(self, claim, worktree, expected=None):
        self.authenticate(claim, {'VALIDATING'})
        self.queue._fresh()
        task = claim['task']
        folder = self.root / claim['attempt_id']
        artifacts = {}
        total = 0
        for name in task['expected_artifacts']:
            relative_file(name)
            if name not in task['allowed_files']:
                raise ContractError('EXPECTED_ARTIFACT_SCOPE')
            source = guarded(Path(worktree) / name)
            if source.stat().st_size > 2 * 1024 * 1024:
                raise ContractError('ARTIFACT_SIZE_LIMIT')
            data = source.read_bytes()
            total += len(data)
            if total > 2 * 1024 * 1024:
                raise ContractError('ARTIFACT_SIZE_LIMIT')
            artifacts[name] = digest(data)
            if expected is not None and artifacts[name] != expected.get(name):
                raise ContractError('VALIDATED_ARTIFACT_DRIFT')
            self.authenticate(claim, {'VALIDATING'})
            frozen_bytes(folder / name, data)
        if expected is not None and set(expected) != set(artifacts):
            raise ContractError('VALIDATED_ARTIFACT_SCOPE')
        manifest = {'task_id': task['task_id'], 'task_hash': claim['task_hash'],
                    'attempt_id': claim['attempt_id'], 'epoch': claim['epoch'],
                    'base_sha': task['base_sha'], 'policy_hash': self.queue.policy['policy_hash'],
                    'worker_actor': 'worker:' + claim['attempt_id'], 'queue_id': self.queue.queue_id,
                    'mode': self.queue.evidence_mode, 'artifacts': artifacts}
        hash_value = fingerprint(manifest)
        frozen_bytes(folder / 'manifest.json', canonical(manifest).encode())
        with self.queue.transaction() as db:
            if not self.queue._current(db, claim, {'VALIDATING'}, time.time()):
                raise ContractError('STALE_ARTIFACT_PUBLICATION')
            db.execute('INSERT INTO artifact_manifests VALUES(?,?,?,?,?)',
                       (task['task_id'], claim['attempt_id'], claim['epoch'], hash_value, canonical(manifest)))
        return hash_value

    def verified(self, db, row):
        record = db.execute('SELECT * FROM artifact_manifests WHERE task=?', (row['id'],)).fetchone()
        if not record or record['attempt'] != row['attempt_id'] or record['epoch'] != row['epoch']:
            raise ContractError('STALE_OR_MISSING_MANIFEST')
        import json
        manifest = json.loads(record['manifest'])
        task = json.loads(row['contract'])
        if (manifest['queue_id'] != self.queue.queue_id or manifest['mode'] != self.queue.evidence_mode
                or manifest['task_hash'] != row['hash'] or manifest['policy_hash'] != self.queue.policy['policy_hash']
                or manifest['task_id'] != row['id'] or manifest['base_sha'] != task['base_sha']
                or manifest['attempt_id'] != row['attempt_id'] or manifest['epoch'] != row['epoch']
                or set(manifest['artifacts']) != set(task['expected_artifacts'])):
            raise ContractError('MANIFEST_BINDING_DRIFT')
        folder = guarded(self.root / record['attempt'])
        if (fingerprint(manifest) != record['hash'] or
                guarded(folder / 'manifest.json').read_bytes() != canonical(manifest).encode()):
            raise ContractError('MANIFEST_DRIFT')
        for name, sha in manifest['artifacts'].items():
            relative_file(name)
            data = guarded(folder / name).read_bytes()
            if len(data) > 2 * 1024 * 1024 or digest(data) != sha:
                raise ContractError('ARTIFACT_DRIFT')
        return manifest, record['hash']

    @staticmethod
    def bind_receipt(manifest, hash_value, receipt):
        if receipt.get('artifact_manifest_hash') != hash_value or receipt.get('artifacts') != manifest['artifacts']:
            raise ContractError('VALIDATION_RECEIPT_ARTIFACT_DRIFT')
