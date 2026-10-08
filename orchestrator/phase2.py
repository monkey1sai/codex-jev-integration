"""Incremental controller over CoreQueue's storage and v2 policy/contracts.

No live-admission bypass, trusted-review forgery, or merge executor.
"""
import json
import time
import uuid
from .core_queue import CoreQueue
from .contracts import ContractError, canonical, fingerprint

STATES = {'PENDING', 'READY', 'CLAIMED', 'RUNNING', 'VALIDATING', 'REVIEW',
          'PASSED', 'FAILED', 'HELD', 'CANCELLED'}
ACTIVE = {'CLAIMED', 'RUNNING', 'VALIDATING', 'HELD'}


class Phase2Queue(CoreQueue):
    def __init__(self, *args, evidence_mode='production', review_registry=None, registry_sha256=None, **kwargs):
        if evidence_mode not in {'production', 'OFFLINE_TEST', 'DEVELOPMENT'}:
            raise ContractError('EVIDENCE_MODE')
        self.evidence_mode = evidence_mode
        mode = 'development' if evidence_mode == 'DEVELOPMENT' else 'high_assurance'
        if 'execution_mode' in kwargs and kwargs['execution_mode'] != mode:
            raise ContractError('EXECUTION_MODE_MISMATCH')
        kwargs['execution_mode'] = mode
        super().__init__(*args, **kwargs)
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS phase2_binding(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER)')
            if not db.execute('SELECT 1 FROM phase2_binding').fetchone():
                if db.execute('SELECT 1 FROM tasks').fetchone():
                    raise ContractError('LEGACY_QUEUE_MIGRATION_REQUIRED')
                db.execute('INSERT INTO phase2_binding VALUES(1,1)')
            db.execute('CREATE TABLE IF NOT EXISTS merge_queue(task TEXT PRIMARY KEY, receipt_hash TEXT, status TEXT, reason TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS evidence_binding(id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT, registry_hash TEXT, queue_id TEXT)')
            db.execute('INSERT OR IGNORE INTO evidence_binding VALUES(1,?,?,?)', (evidence_mode, registry_sha256, uuid.uuid4().hex))
            binding = db.execute('SELECT * FROM evidence_binding').fetchone()
            if binding['mode'] != evidence_mode or binding['registry_hash'] != registry_sha256:
                raise ContractError('EVIDENCE_BINDING_DRIFT')
            self.queue_id = binding['queue_id']
            db.execute('CREATE TABLE IF NOT EXISTS review_challenges(nonce TEXT PRIMARY KEY, task TEXT, target TEXT, used INTEGER DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS reviews(task TEXT PRIMARY KEY, envelope TEXT, hash TEXT, source TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS review_runtime(nonce TEXT PRIMARY KEY, hash TEXT UNIQUE, receipt TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS development_native_slots(actor TEXT PRIMARY KEY, task TEXT, nonce TEXT)')
        from .evidence import ReviewTrust, ArtifactStore
        self.trust = ReviewTrust(review_registry, registry_sha256, self.path.parent / 'review-verification', self.repo) if review_registry else None
        if bool(review_registry) != bool(registry_sha256):
            raise ContractError('TRUST_PIN_REQUIRED')
        self.artifacts = ArtifactStore(self)

    @staticmethod
    def _event(db, key, name, **data):
        db.execute('INSERT INTO events(task,event,at) VALUES(?,?,?)',
                   (key, canonical({'event': name, **data}), time.time()))

    def enqueue(self, tasks):
        self._fresh()
        if type(tasks) is list:
            tasks = [normalize_task(t) for t in tasks]
        # CoreQueue's validator validates the complete DAG, policy and exact scope.
        with self.transaction() as db:
            existing = {r['id']: json.loads(r['contract']) for r in db.execute('SELECT * FROM tasks')}
            if type(tasks) is not list or not tasks:
                raise ContractError('CONTRACT_SCHEMA')
            ids = [t.get('task_id') for t in tasks if type(t) is dict]
            if len(ids) != len(tasks) or len(set(ids)) != len(ids):
                raise ContractError('DUPLICATE_TASK_ID')
            for task in tasks:
                key = task['task_id']
                if key in existing and fingerprint(existing[key]) != fingerprint(task):
                    raise ContractError('IMMUTABLE_TASK_DRIFT')
                existing[key] = task
            self.validator(list(existing.values()))
            for task in tasks:
                inserted = db.execute('INSERT OR IGNORE INTO tasks(id,contract,hash,state) VALUES(?,?,?,?)',
                                      (task['task_id'], canonical(task), fingerprint(task), 'PENDING')).rowcount
                if inserted:
                    self._event(db, task['task_id'], 'PENDING', contract_hash=fingerprint(task))
            self._ready(db)

    def _ready(self, db):
        states = dict(db.execute('SELECT id,state FROM tasks'))
        for row in db.execute("SELECT * FROM tasks WHERE state='PENDING'").fetchall():
            task = json.loads(row['contract'])
            if all(states.get(dep) == 'PASSED' for dep in task['dependencies']):
                db.execute("UPDATE tasks SET state='READY' WHERE id=?", (row['id'],))
                self._event(db, row['id'], 'READY')

    def claim(self, lease_seconds=180, now=None, *, capabilities=None):
        self._fresh()
        if type(lease_seconds) not in (int, float) or not 0 < lease_seconds <= 600:
            raise ContractError('LEASE_BOUND')
        now = time.time() if now is None else now
        with self.transaction() as db:
            self._ready(db)
            cap = db.execute('SELECT active_cap FROM controller_binding').fetchone()[0]
            active = db.execute("SELECT count(*) FROM tasks WHERE state IN ('CLAIMED','RUNNING','VALIDATING','HELD')").fetchone()[0]
            active += db.execute('SELECT count(*) FROM development_native_slots').fetchone()[0]
            budget = db.execute('SELECT * FROM budget').fetchone()
            if active >= cap or budget['used'] >= budget['max_dispatches']:
                return None
            for row in db.execute("SELECT * FROM tasks WHERE state='READY' ORDER BY rowid").fetchall():
                task = json.loads(row['contract'])
                if capabilities is not None and task['capability'] not in capabilities:
                    continue
                if row['attempts'] >= task['budgets']['attempts'] or row['provider_unknown']:
                    continue
                resources = sorted(set(task['resource_locks'] + ['file:' + p.casefold() for p in task['allowed_files']]))
                if any(db.execute('SELECT 1 FROM locks WHERE resource=?', (r,)).fetchone() for r in resources):
                    continue
                token, epoch = uuid.uuid4().hex, row['epoch'] + 1
                db.execute("UPDATE tasks SET state='CLAIMED',epoch=?,attempts=attempts+1,attempt_id=?,expires=? WHERE id=?",
                           (epoch, token, now + lease_seconds, row['id']))
                db.executemany('INSERT INTO locks VALUES(?,?)', [(r, row['id']) for r in resources])
                db.execute('UPDATE budget SET used=used+1 WHERE id=1')
                self._event(db, row['id'], 'CLAIMED', epoch=epoch, attempt_id=token)
                return {'task': task, 'task_hash': row['hash'], 'attempt_id': token, 'epoch': epoch}
        return None

    def _transition(self, claim, before, after, now=None):
        self._fresh()
        now = time.time() if now is None else now
        with self.transaction() as db:
            if not self._current(db, claim, before, now):
                return False
            key = claim['task']['task_id']
            db.execute('UPDATE tasks SET state=? WHERE id=?', (after, key))
            self._event(db, key, after, epoch=claim['epoch'], attempt_id=claim['attempt_id'])
            return True

    def start(self, claim, now=None):
        return self._transition(claim, {'CLAIMED'}, 'RUNNING', now)

    def validating(self, claim, now=None):
        return self._transition(claim, {'RUNNING'}, 'VALIDATING', now)

    def heartbeat(self, claim, lease_seconds=180, now=None):
        self._fresh()
        if type(lease_seconds) not in (int, float) or not 0 < lease_seconds <= 600:
            raise ContractError('LEASE_BOUND')
        now = time.time() if now is None else now
        with self.transaction() as db:
            if not self._current(db, claim, {'CLAIMED', 'RUNNING', 'VALIDATING'}, now):
                return False
            key = claim['task']['task_id']
            db.execute('UPDATE tasks SET expires=? WHERE id=?', (now + lease_seconds, key))
            self._event(db, key, 'heartbeat', epoch=claim['epoch'], expires=now + lease_seconds)
            return True

    def finish(self, claim, receipt, passed, now=None):
        self._fresh()
        now = time.time() if now is None else now
        if type(receipt) is not dict or receipt.get('process_tree_empty') is not True:
            raise ContractError('CLEANUP_EVIDENCE_REQUIRED')
        if type(passed) is not bool:
            raise ContractError('VALIDATION_RESULT')
        with self.transaction() as db:
            if not self._current(db, claim, {'VALIDATING'}, now):
                return False
            key, state = claim['task']['task_id'], 'REVIEW' if passed else 'FAILED'
            if passed and receipt.get('artifact_manifest_hash'):
                row = db.execute('SELECT * FROM tasks WHERE id=?', (key,)).fetchone()
                manifest, sha = self.artifacts.verified(db, row)
                self.artifacts.bind_receipt(manifest, sha, receipt)
            db.execute('UPDATE tasks SET state=?,receipt=?,expires=NULL WHERE id=?', (state, canonical(receipt), key))
            db.execute('DELETE FROM locks WHERE task=?', (key,))
            self._event(db, key, state, receipt_hash=fingerprint(receipt), epoch=claim['epoch'])
            if passed:
                db.execute('INSERT INTO merge_queue VALUES(?,?,?,?)',
                           (key, fingerprint(receipt), 'HELD', 'TRUSTED_REVIEW_IMPORT_NOT_IMPLEMENTED'))
            return True

    def fence(self, claim, reason='cancelled'):
        with self.transaction() as db:
            key = claim['task']['task_id']
            row = db.execute('SELECT * FROM tasks WHERE id=?', (key,)).fetchone()
            if not self._identity(row, claim) or row['state'] not in {'CLAIMED', 'RUNNING', 'VALIDATING'}:
                return False
            db.execute("UPDATE tasks SET state='HELD',epoch=epoch+1,reason=? WHERE id=?", (reason, key))
            self._event(db, key, 'fenced', reason=reason, epoch=claim['epoch'] + 1)
            return True

    def expired(self, now=None):
        now = time.time() if now is None else now
        with self.transaction() as db:
            claims = [{'task': json.loads(r['contract']), 'task_hash': r['hash'], 'attempt_id': r['attempt_id'], 'epoch': r['epoch']}
                      for r in db.execute("SELECT * FROM tasks WHERE state IN ('CLAIMED','RUNNING','VALIDATING') AND expires<=?", (now,))]
            for claim in claims:
                key = claim['task']['task_id']
                db.execute("UPDATE tasks SET state='HELD',epoch=epoch+1,reason='lease_expired' WHERE id=?", (key,))
                self._event(db, key, 'lease_expired', epoch=claim['epoch'] + 1)
            return claims

    def cleanup(self, claim, *, tree_empty, retry=False, provider_completion_unknown=False):
        self._fresh()
        with self.transaction() as db:
            key = claim['task']['task_id']
            row = db.execute('SELECT * FROM tasks WHERE id=?', (key,)).fetchone()
            if not self._identity(row, claim, 1) or row['state'] != 'HELD' or tree_empty is not True:
                return False
            if provider_completion_unknown:
                db.execute('UPDATE tasks SET provider_unknown=1 WHERE id=?', (key,))
            if retry and (provider_completion_unknown or row['provider_unknown'] or row['attempts'] >= claim['task']['budgets']['attempts']):
                return False
            state = 'PENDING' if retry else 'CANCELLED'
            db.execute('UPDATE tasks SET state=?,expires=NULL WHERE id=?', (state, key))
            db.execute('DELETE FROM locks WHERE task=?', (key,))
            self._event(db, key, 'cleanup', tree_empty=True, retry=retry, state=state)
            self._ready(db)
            return True

    def dispatch_intent(self, claim):
        self._fresh()
        with self.transaction() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=?', (claim['task']['task_id'],)).fetchone()
            if not self._current(db, claim, {'RUNNING'}, time.time()) or row['provider_unknown']:
                return False
            key = claim['task']['task_id']
            db.execute('UPDATE tasks SET provider_unknown=1 WHERE id=?', (key,))
            self._event(db, key, 'dispatch_intent', epoch=claim['epoch'], provider_completion='UNKNOWN')
            return True

    def merge_snapshot(self):
        with self.transaction() as db:
            return [dict(r) for r in db.execute('SELECT * FROM merge_queue ORDER BY rowid')]

    def review_challenge(self, task_id, ttl=300):
        self._fresh()
        if type(ttl) is not int or not 1 <= ttl <= 600:
            raise ContractError('REVIEW_TTL')
        with self.transaction() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not row or row['state'] != 'REVIEW':
                raise ContractError('REVIEW_STATE')
            manifest, artifact_hash = self.artifacts.verified(db, row)
            self.artifacts.bind_receipt(manifest, artifact_hash, json.loads(row['receipt']))
            target = {'queue_id': self.queue_id, 'task_id': task_id, 'task_hash': row['hash'],
                      'attempt_id': row['attempt_id'], 'epoch': row['epoch'], 'policy_hash': self.policy['policy_hash'],
                      'receipt_hash': fingerprint(json.loads(row['receipt'])), 'artifact_hash': artifact_hash,
                      'nonce': uuid.uuid4().hex, 'expires': time.time() + ttl,
                      'worker_actor': manifest['worker_actor'], 'mode': self.evidence_mode,
                      'purpose': 'codex-orchestrator/task-review/v1', 'registry_hash': self.trust.sha256 if self.trust else None}
            db.execute('INSERT INTO review_challenges(nonce,task,target) VALUES(?,?,?)', (target['nonce'], task_id, canonical(target)))
            return target

    def import_review(self, envelope):
        try:
            return self._import_review(envelope)
        except ContractError as error:
            if self.evidence_mode == 'production':
                self._review_rejection(envelope, str(error))
            raise

    def _review_rejection(self, envelope, reason):
        """Audit a rejection without trusting or persisting caller content."""
        from .evidence import frozen_bytes
        target = None
        try:
            data = canonical(envelope).encode()
            envelope_hash = fingerprint(envelope) if len(data) <= 65536 else None
            if type(envelope) is dict and type(envelope.get('payload')) is dict:
                target = envelope['payload'].get('target')
        except (TypeError, ValueError):
            envelope_hash = None
        evidence_id = uuid.uuid4().hex
        receipt = {'evidence_id': evidence_id, 'queue_id': self.queue_id,
                   'policy_hash': self.policy['policy_hash'], 'envelope_hash': envelope_hash,
                   'admission': 'BLOCKED', 'reason': reason, 'mode': 'production'}
        frozen_bytes(self.path.parent / 'review-admission' / (evidence_id + '.json'), canonical(receipt).encode())
        with self.transaction() as db:
            key = None
            if type(target) is dict and isinstance(target.get('nonce'), str):
                challenge = db.execute('SELECT task,target FROM review_challenges WHERE nonce=?', (target['nonce'],)).fetchone()
                if challenge and challenge['target'] == canonical(target):
                    key = challenge['task']
            self._event(db, key, 'review_admission_rejected', evidence_id=evidence_id,
                        receipt_hash=fingerprint(receipt), reason=reason)

    def _import_review(self, envelope):
        self._fresh()
        if self.evidence_mode == 'DEVELOPMENT':
            raise ContractError('DEVELOPMENT_REVIEW_REQUIRES_CONTROLLER_EXECUTION')
        if self.trust is None:
            raise ContractError('TRUST_REGISTRY_REQUIRED')
        kind, key_hash = self.trust.verify(envelope)
        payload = envelope['payload']
        if set(payload) != {'target', 'reviewer_id', 'decision', 'observed_model', 'observed_effort', 'execution_evidence_hash'}:
            raise ContractError('REVIEW_SCHEMA')
        target = payload['target']
        if type(target) is not dict or payload['decision'] not in {'PASS', 'REJECT'}:
            raise ContractError('REVIEW_SCHEMA')
        if self.evidence_mode == 'production' and kind != 'native_attester':
            raise ContractError('REQUIRED_MODEL_REVIEW_HELD')
        if self.evidence_mode == 'OFFLINE_TEST' and kind != 'offline_fixture':
            raise ContractError('REVIEW_REALM_MISMATCH')
        rank = {'high': 0, 'xhigh': 1, 'max': 2, 'ultra': 3}
        required = self.policy['settings']['roles']['reviewer']
        if (payload['observed_model'] != required['model']
                or rank.get(payload['observed_effort'], -1) < rank[required['reasoning_effort']]):
            raise ContractError('REVIEW_MODEL_FLOOR')
        import re
        if not isinstance(payload['execution_evidence_hash'], str) or not re.fullmatch('[a-f0-9]{64}', payload['execution_evidence_hash']):
            raise ContractError('REVIEW_EXECUTION_EVIDENCE')
        with self.transaction() as db:
            challenge = db.execute('SELECT * FROM review_challenges WHERE nonce=?', (target.get('nonce'),)).fetchone()
            row = db.execute('SELECT * FROM tasks WHERE id=?', (target.get('task_id'),)).fetchone()
            if not challenge or challenge['used'] or challenge['target'] != canonical(target):
                raise ContractError('REVIEW_REPLAY_OR_UNKNOWN')
            if (not row or row['state'] != 'REVIEW' or target['expires'] <= time.time()
                    or row['attempt_id'] != target['attempt_id'] or row['epoch'] != target['epoch']
                    or row['hash'] != target['task_hash'] or self.queue_id != target['queue_id']
                    or self.policy['policy_hash'] != target['policy_hash']
                    or fingerprint(json.loads(row['receipt'])) != target['receipt_hash']):
                raise ContractError('STALE_REVIEW')
            manifest, artifact_hash = self.artifacts.verified(db, row)
            self.artifacts.bind_receipt(manifest, artifact_hash, json.loads(row['receipt']))
            if artifact_hash != target['artifact_hash'] or payload['reviewer_id'] == manifest['worker_actor']:
                raise ContractError('REVIEW_NOT_INDEPENDENT')
            receipt = json.loads(row['receipt'])
            if self.evidence_mode == 'production':
                # A signed model-name assertion is not observed native provenance.
                # Until the native reviewer execution ledger is wired and proven,
                # even a pinned attester cannot release the production floor.
                runtime = db.execute('SELECT * FROM review_runtime WHERE nonce=?', (target['nonce'],)).fetchone()
                if not runtime:
                    reason = 'MISSING_EXECUTION_RECEIPT'
                elif runtime['hash'] != payload['execution_evidence_hash']:
                    reason = 'EXECUTION_RECEIPT_MISMATCH'
                else:
                    self._runtime_file(target['nonce'], runtime['hash'])
                    reason = 'CONFIGURED_METADATA_IS_NOT_EXECUTION_PROVENANCE'
                raise ContractError('REQUIRED_NATIVE_REVIEW_PROVENANCE_UNAVAILABLE:' + reason)
            db.execute('UPDATE review_challenges SET used=1 WHERE nonce=?', (target['nonce'],))
            db.execute('INSERT INTO reviews VALUES(?,?,?,?)', (row['id'], canonical(envelope), fingerprint(envelope), kind))
            state = 'PASSED' if payload['decision'] == 'PASS' else 'FAILED'
            db.execute('UPDATE tasks SET state=? WHERE id=?', (state, row['id']))
            db.execute('UPDATE merge_queue SET reason=? WHERE task=?', ('HUMAN_MERGE_AUTHORIZATION_REQUIRED' if state == 'PASSED' else 'REVIEW_REJECTED', row['id']))
            self._event(db, row['id'], state, review_hash=fingerprint(envelope), reviewer_key=key_hash, evidence_mode=self.evidence_mode)
            self._ready(db)
            return {'state': state, 'evidence_mode': self.evidence_mode, 'review_hash': fingerprint(envelope), 'merge_executed': False}

    def record_review_runtime(self, target, started, completed):
        """Durably bind diagnostic metadata; this does not enroll an attester.

        Reuses the review challenge and artifact custody checks. Recording does
        not consume a nonce, change task state, or grant production admission.
        """
        self._fresh()
        if type(target) is not dict:
            raise ContractError('REVIEW_RUNTIME_TARGET')
        from .admission import app_server_review_metadata
        from .evidence import frozen_bytes, digest
        with self.transaction() as db:
            challenge = db.execute('SELECT * FROM review_challenges WHERE nonce=?', (target.get('nonce'),)).fetchone()
            row = db.execute('SELECT * FROM tasks WHERE id=?', (target.get('task_id'),)).fetchone()
            if not challenge or challenge['used'] or challenge['target'] != canonical(target):
                raise ContractError('REVIEW_REPLAY_OR_UNKNOWN')
            if (not row or row['state'] != 'REVIEW' or target['expires'] <= time.time()
                    or row['attempt_id'] != target['attempt_id'] or row['epoch'] != target['epoch']
                    or row['hash'] != target['task_hash'] or self.queue_id != target['queue_id']
                    or self.policy['policy_hash'] != target['policy_hash']
                    or fingerprint(json.loads(row['receipt'])) != target['receipt_hash']):
                raise ContractError('STALE_REVIEW')
            manifest, artifact_hash = self.artifacts.verified(db, row)
            self.artifacts.bind_receipt(manifest, artifact_hash, json.loads(row['receipt']))
            if artifact_hash != target['artifact_hash']:
                raise ContractError('REVIEW_ARTIFACT_MISMATCH')
            receipt = app_server_review_metadata(target, started, completed)
            sha = fingerprint(receipt)
            previous = db.execute('SELECT * FROM review_runtime WHERE nonce=?', (target['nonce'],)).fetchone()
            if previous:
                if previous['hash'] != sha:
                    raise ContractError('REVIEW_RUNTIME_REPLAY_OR_DRIFT')
                self._runtime_file(target['nonce'], previous['hash'])
                return json.loads(previous['receipt'])
            path = self.path.parent / 'review-runtime' / (target['nonce'] + '.json')
            data = canonical(receipt).encode()
            if path.exists():
                # A controller crash after exclusive write but before DB commit
                # may leave an identical orphan. Never overwrite different bytes.
                from .evidence import guarded
                if digest(guarded(path).read_bytes()) != sha:
                    raise ContractError('REVIEW_RUNTIME_FILE_DRIFT')
            else:
                frozen_bytes(path, data)
            db.execute('INSERT INTO review_runtime VALUES(?,?,?)', (target['nonce'], sha, canonical(receipt)))
            self._event(db, row['id'], 'review_runtime_blocked', receipt_hash=sha,
                        nonce=target['nonce'], blockers=receipt['blockers'])
            return receipt

    def _runtime_file(self, nonce, sha):
        from .evidence import guarded, digest
        path = guarded(self.path.parent / 'review-runtime' / (nonce + '.json'))
        if not path.is_file() or digest(path.read_bytes()) != sha:
            raise ContractError('REVIEW_RUNTIME_FILE_DRIFT')

    def merge(self, *args, **kwargs):
        raise ContractError('MERGE_EXECUTION_DISABLED')


def normalize_task(task):
    """Named Phase 1–2 fields map losslessly onto the reused strict v2 contract."""
    if type(task) is not dict or task.get('schema_version') != 3:
        return task
    result = dict(task)
    try:
        acceptance = result.pop('acceptance')
        if type(acceptance) is not dict or set(acceptance) != {'criteria', 'validators'}:
            raise ContractError('ACCEPTANCE_SCHEMA')
        result['acceptance_criteria'] = acceptance['criteria']
        result['tests'] = acceptance['validators']
        result['execution'] = result.pop('model_policy')
        result['budgets'] = result.pop('retry_budget')
        result['schema_version'] = 2
    except KeyError:
        raise ContractError('CONTRACT_SCHEMA') from None
    return result
